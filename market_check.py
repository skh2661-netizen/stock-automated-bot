import os
import re
import time
import math
import logging
import datetime
import threading
import atexit
import itertools
import copy
from dataclasses import dataclass
from collections import deque, Counter
from typing import Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from concurrent.futures.thread import BrokenThreadPool

import pytz
import numpy as np
import pandas as pd
import requests
import FinanceDataReader as fdr
import yfinance as yf
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =========================================================
# 1. Configuration (설정 중앙화)
# =========================================================
@dataclass
class MarketConfig:
    EXPECTED_KP_TOTAL: int = 950
    EXPECTED_KD_TOTAL: int = 1750
    
    CB_THRESHOLD_API: int = 3
    CB_THRESHOLD_DOM: int = 5
    CB_THRESHOLD_FDR: int = 2
    CB_THRESHOLD_YAHOO: int = 3
    CB_BASE_PENALTY: int = 1800
    CB_HALF_OPEN_SUCCESS_REQ: int = 3
    
    WORKER_COUNT: int = min(8, (os.cpu_count() or 2) * 2)
    EMA_ALPHA_GLOBAL: float = 0.1
    # [수정 5] 소스 EMA 알파 완화 (장애 시 너무 빠르게 신뢰도가 추락하는 현상 방지)
    EMA_ALPHA_SOURCE: float = 0.05 
    
    CONFIDENCE_EXP_FACTOR: float = -5.0 
    CROSS_CHECK_TOLERANCE: float = 0.05
    INDEX_REQUIRED_DAYS: int = 25

CONFIG = MarketConfig()

# =========================================================
# 2. Data Structures 
# =========================================================
@dataclass
class SourceDiag:
    status: str = "FAIL"
    error: str = ""
    elapsed: float = 0.0
    age: int = 0

# =========================================================
# 3. Global State & Locks
# =========================================================
_cache_lock = threading.Lock()
_cb_lock = threading.Lock()
_executor_lock = threading.Lock()
_fdr_semaphore = threading.Semaphore(1)  # [수정 3] FDR(KRX) 동시 호출 차단용 세마포어

_breadth_cache = {"timestamp": 0, "data": None, "time_context": False, "original_source": "", "confidence": 1.0}
_index_cache = {"timestamp": 0, "data": None, "time_context": False}

_health_history = deque(maxlen=200)
_global_health_ema = 100.0
_fdr_elapsed_ema = 3.0

_source_health_ema = {"FDR": 100.0, "API": 99.0, "DOM": 98.0, "YAHOO": 100.0}

_circuit_breakers = {
    "API": {"fails": 0, "blocked_until": 0, "last_fail_time": 0, "state": "CLOSED", "consecutive_successes": 0},
    "DOM": {"fails": 0, "blocked_until": 0, "last_fail_time": 0, "state": "CLOSED", "consecutive_successes": 0},
    "FDR": {"fails": 0, "blocked_until": 0, "last_fail_time": 0, "state": "CLOSED", "consecutive_successes": 0},
    "YAHOO": {"fails": 0, "blocked_until": 0, "last_fail_time": 0, "state": "CLOSED", "consecutive_successes": 0}
}

# =========================================================
# 4. Thread-Local Session & Safe Executor Management
# =========================================================
_thread_local = threading.local()

_GLOBAL_ADAPTER = HTTPAdapter(
    pool_connections=CONFIG.WORKER_COUNT, 
    pool_maxsize=CONFIG.WORKER_COUNT, 
    max_retries=Retry(
        total=3, connect=3, read=2, backoff_factor=1,
        respect_retry_after_header=True, allowed_methods=["GET"],
        status_forcelist=[500, 502, 503, 504]
    )
)

_global_executor = None

def _get_session():
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update({'User-Agent': 'Mozilla/5.0'})
        s.mount("https://", _GLOBAL_ADAPTER)
        s.mount("http://", _GLOBAL_ADAPTER)
        _thread_local.session = s
    return _thread_local.session

def _safe_submit(fn, *args, **kwargs):
    global _global_executor
    with _executor_lock:
        if _global_executor is None:
            _global_executor = ThreadPoolExecutor(max_workers=CONFIG.WORKER_COUNT)
            
    for _ in range(2):
        try:
            return _global_executor.submit(fn, *args, **kwargs)
        except (RuntimeError, BrokenThreadPool):
            with _executor_lock:
                logging.warning("[System] ThreadPoolExecutor dead. Resurrecting...")
                _global_executor = ThreadPoolExecutor(max_workers=CONFIG.WORKER_COUNT)
                
    raise RuntimeError("Failed to submit task to Executor.")

@atexit.register
def cleanup():
    _GLOBAL_ADAPTER.close()
    for s in getattr(_thread_local, "__dict__", {}).values():
        if hasattr(s, "close"): s.close()
    if _global_executor:
        # [수정 8] 장기 실행 프로세스의 안전한 종료를 위해 wait=True 적용
        _global_executor.shutdown(wait=True, cancel_futures=True)

# =========================================================
# 5. Core Utilities
# =========================================================
def _get_time_context() -> Dict[str, Any]:
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.datetime.now(kst)
    if now.weekday() >= 5: 
        return {"is_open": False, "ttl": 600, "ratio": 0.80}
    
    t = now.time()
    if datetime.time(9, 0) <= t < datetime.time(9, 30): 
        return {"is_open": True, "ttl": 20, "ratio": 0.70} 
    elif datetime.time(9, 30) <= t < datetime.time(14, 50): 
        return {"is_open": True, "ttl": 60, "ratio": 0.75}
    elif datetime.time(14, 50) <= t <= datetime.time(15, 30): 
        return {"is_open": True, "ttl": 5, "ratio": 0.75} 
    elif datetime.time(15, 30) < t <= datetime.time(15, 40): 
        return {"is_open": False, "ttl": 60, "ratio": 0.80}
    else: 
        return {"is_open": False, "ttl": 600, "ratio": 0.80}

def _validate_data(data: Dict[str, Any]) -> bool:
    for k, v in data.items():
        if isinstance(v, (int, float)):
            # [수정 4] 상한선 검사 추가 (비정상적으로 튀는 값 원천 차단)
            if math.isnan(v) or math.isinf(v) or v < 0 or v > 5000:
                return False
    return True

def _check_cb(source_key: str) -> bool:
    with _cb_lock:
        cb = _circuit_breakers[source_key]
        if cb["state"] == "OPEN":
            if time.time() >= cb["blocked_until"]:
                cb["state"] = "HALF_OPEN"
                return True
            return False
        return True

def _update_cb(source_key: str, success: bool, error_msg: str = ""):
    global _source_health_ema
    with _cb_lock:
        cb = _circuit_breakers[source_key]
        now = time.time()
        
        current_ema = _source_health_ema.get(source_key, 100.0)
        _source_health_ema[source_key] = (current_ema * (1 - CONFIG.EMA_ALPHA_SOURCE)) + ((100.0 if success else 0.0) * CONFIG.EMA_ALPHA_SOURCE)
        
        threshold = getattr(CONFIG, f"CB_THRESHOLD_{source_key}", 5)
        
        if success:
            if cb["state"] == "HALF_OPEN":
                cb["consecutive_successes"] += 1
                if cb["consecutive_successes"] >= CONFIG.CB_HALF_OPEN_SUCCESS_REQ:
                    cb["fails"] = 0
                    cb["state"] = "CLOSED"
                    cb["consecutive_successes"] = 0
            else:
                if (now - cb["last_fail_time"] > 1800) or _source_health_ema[source_key] > 90.0:
                    cb["fails"] = 0
                else:
                    cb["fails"] = max(0, cb["fails"] - 1)
            cb["blocked_until"] = 0
        else:
            cb["fails"] += 1
            cb["last_fail_time"] = now
            cb["consecutive_successes"] = 0
            
            if cb["state"] == "HALF_OPEN" or cb["fails"] >= threshold:
                cb["state"] = "OPEN"
                power = max(0, (cb["fails"] // threshold) - 1)
                
                base_pen = CONFIG.CB_BASE_PENALTY
                if "429" in error_msg or "Too Many" in error_msg: base_pen = 300       
                elif "Parse" in error_msg or "Validation" in error_msg: base_pen = 3600 
                elif "Timeout" in error_msg: base_pen = 900                            
                
                penalty = min(base_pen * (2 ** power), 14400)
                cb["blocked_until"] = now + penalty
                logging.error("[Circuit Breaker] %s OPEN (BLOCKED) for %d mins (Err: %s)", source_key, penalty // 60, error_msg[:30])

def _get_src_key(source_str: str) -> str:
    if "API" in source_str: return "API"
    if "DOM" in source_str: return "DOM"
    if "YAHOO" in source_str: return "YAHOO"
    return "FDR"

def _fdr_data_reader_safe(symbol: str, start_date: str):
    """[수정 3] FDR(KRX) 호출 시 글로벌 세마포어로 직렬화하여 Access Denied 방어"""
    with _fdr_semaphore:
        return fdr.DataReader(symbol, start_date)

# =========================================================
# 6. Index Loading Module
# =========================================================
def load_index():
    global _index_cache
    st_idx = time.time()
    ctx = _get_time_context()
    
    with _cache_lock:
        if _index_cache["data"] is not None and (st_idx - _index_cache["timestamp"] < ctx["ttl"]) and (_index_cache["time_context"] == ctx["is_open"]):
            cached = copy.deepcopy(_index_cache["data"])
            age = int(st_idx - _index_cache['timestamp'])
            logging.debug("[Market] Index Source=CACHE | Age=%ds", age)
            return cached

    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    idx_data = {
        "success": False, "partial": False, "error": None,
        "kp_today": 0.0, "kp_prev": 0.0, "kp_1d": 0.0, "kp_5d": 0.0, "kp_20d": 0.0,
        "kd_today": 0.0, "kd_prev": 0.0, "kd_1d": 0.0, "kd_5d": 0.0, "kd_20d": 0.0,
        "elapsed": 0.0
    }
    
    futures_map = {
        _safe_submit(_fdr_data_reader_safe, "KS11", start_date): "KS11",
        _safe_submit(_fdr_data_reader_safe, "KQ11", start_date): "KQ11"
    }
    
    done, not_done = wait(futures_map.keys(), timeout=15, return_when=ALL_COMPLETED)
    kp, kd = None, None
    
    for f in done:
        ticker = futures_map[f]
        try:
            res = f.result()
            if ticker == "KS11": kp = res
            elif ticker == "KQ11": kd = res
        except Exception as e:
            err_msg = f"{type(e).__name__} {str(e)[:50]}"
            idx_data["error"] = f"{idx_data['error']} | {ticker}: {err_msg}" if idx_data["error"] else f"{ticker}: {err_msg}"
            logging.debug("[Index] Fetch Error %s: %s", ticker, e)

    yahoo_used, yahoo_ok = False, True
    def _fallback_yf(symbol: str):
        try:
            df = yf.download(symbol, period="3mo", progress=False)
            if df is not None and not df.empty:
                # [수정 1] yfinance 버전에 따른 MultiIndex 대응 방어
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                if 'Adj Close' in df.columns:
                    df = df.rename(columns={'Adj Close': 'Close'})
                return df
        except Exception as e:
            logging.debug("[Index] YF Fallback Error %s: %s", symbol, e)
        return None

    if (kp is None or "Close" not in kp.columns or len(kp) < CONFIG.INDEX_REQUIRED_DAYS) and _check_cb("YAHOO"):
        yahoo_used = True
        kp = _fallback_yf("^KS11")
        if kp is None: yahoo_ok = False

    if (kd is None or "Close" not in kd.columns or len(kd) < CONFIG.INDEX_REQUIRED_DAYS) and _check_cb("YAHOO"):
        yahoo_used = True
        kd = _fallback_yf("^KQ11")
        if kd is None: yahoo_ok = False

    if yahoo_used:
        _update_cb("YAHOO", yahoo_ok, "" if yahoo_ok else "Fallback Failed")

    for f in not_done: 
        is_cancelled = f.cancel()
        if not is_cancelled: logging.debug("[Index] Zombie Thread Warning: %s", futures_map[f])

    kp_ok = kp is not None and "Close" in kp.columns and len(kp) >= CONFIG.INDEX_REQUIRED_DAYS
    kd_ok = kd is not None and "Close" in kd.columns and len(kd) >= CONFIG.INDEX_REQUIRED_DAYS

    if kp_ok:
        kpc = kp['Close'].dropna().values
        idx_data["kp_today"], idx_data["kp_prev"] = float(kpc[-1]), float(kpc[-2])
        idx_data["kp_1d"] = round(((kpc[-1] / kpc[-2]) - 1) * 100, 2)
        idx_data["kp_5d"] = round(((kpc[-1] / kpc[-6]) - 1) * 100, 2)
        idx_data["kp_20d"] = round(((kpc[-1] / kpc[-21]) - 1) * 100, 2)
        
    if kd_ok:
        kdc = kd['Close'].dropna().values
        idx_data["kd_today"], idx_data["kd_prev"] = float(kdc[-1]), float(kdc[-2])
        idx_data["kd_1d"] = round(((kdc[-1] / kdc[-2]) - 1) * 100, 2)
        idx_data["kd_5d"] = round(((kdc[-1] / kdc[-6]) - 1) * 100, 2)
        idx_data["kd_20d"] = round(((kdc[-1] / kdc[-21]) - 1) * 100, 2)
        
    idx_data["success"] = kp_ok or kd_ok
    idx_data["partial"] = kp_ok != kd_ok
    idx_data["elapsed"] = round(time.time() - st_idx, 3)
    
    if idx_data["partial"]: logging.warning("[Market] Partial Index (KP=%s, KD=%s)", kp_ok, kd_ok)
    if not idx_data["success"] and not idx_data["error"]: idx_data["error"] = "Data Validation Failed"
    
    if idx_data["success"]:
        with _cache_lock:
            _index_cache = {"timestamp": time.time(), "data": copy.deepcopy(idx_data), "time_context": ctx["is_open"]}
            
    return idx_data

# =========================================================
# 7. Breadth Loaders (Fetchers)
# =========================================================
def _fetch_api(ctx):
    st = time.time()
    res = {"success": False, "source": "NAVER API", "error": "", "data": {}}
    try:
        session = _get_session()
        r_kp = session.get("https://m.stock.naver.com/api/index/KOSPI/price", timeout=(3, 7))
        r_kd = session.get("https://m.stock.naver.com/api/index/KOSDAQ/price", timeout=(3, 7))
        r_kp.raise_for_status(); r_kd.raise_for_status()
        
        kp_j, kd_j = r_kp.json()[0], r_kd.json()[0]
        kp_rf, kd_rf = kp_j.get("riseFall", {}), kd_j.get("riseFall", {})
        
        data = {
            "kp_up": int(kp_rf.get("rise",0)), "kp_down": int(kp_rf.get("fall",0)), "kp_same": int(kp_rf.get("same",0)),
            "kd_up": int(kd_rf.get("rise",0)), "kd_down": int(kd_rf.get("fall",0)), "kd_same": int(kd_rf.get("same",0))
        }
        
        kp_sum = data["kp_up"] + data["kp_down"] + data["kp_same"]
        kd_sum = data["kd_up"] + data["kd_down"] + data["kd_same"]
        
        if _validate_data(data) and kp_sum >= (CONFIG.EXPECTED_KP_TOTAL * ctx["ratio"]) and kd_sum >= (CONFIG.EXPECTED_KD_TOTAL * ctx["ratio"]):
            res["success"] = True; res["data"] = data
        else: res["error"] = "Data Validation or Ratio Failed"
    except Exception as e: 
        res["error"] = f"{type(e).__name__}: {str(e)[:40]}"
    res["elapsed"] = round(time.time() - st, 3)
    return res

def _fetch_dom(ctx):
    st = time.time()
    res = {"success": False, "source": "NAVER DOM", "error": "", "data": {}}
    try:
        session = _get_session()
        def parse(code):
            r = session.get(f"https://finance.naver.com/sise/sise_index.naver?code={code}", timeout=(3, 7))
            r.raise_for_status()
            dl = BeautifulSoup(r.text, 'html.parser').select_one("dl.lst_kos_info")
            u, d, s = 0, 0, 0
            if dl:
                for dt in dl.select("dt"):
                    txt, dd = dt.get_text(), dt.find_next_sibling("dd")
                    if dd:
                        val = int(re.sub(r'[^\d]', '', dd.get_text()) or 0)
                        if "상승" in txt: u = val
                        elif "하락" in txt: d = val
                        elif "보합" in txt: s = val
            return u, d, s
            
        kp_u, kp_d, kp_s = parse("KOSPI")
        kd_u, kd_d, kd_s = parse("KOSDAQ")
        data = {"kp_up": kp_u, "kp_down": kp_d, "kp_same": kp_s, "kd_up": kd_u, "kd_down": kd_d, "kd_same": kd_s}
        
        if _validate_data(data) and sum([kp_u,kp_d,kp_s]) >= (CONFIG.EXPECTED_KP_TOTAL * ctx["ratio"]) and sum([kd_u,kd_d,kd_s]) >= (CONFIG.EXPECTED_KD_TOTAL * ctx["ratio"]):
            res["success"] = True; res["data"] = data
        else: res["error"] = "Data Validation Failed"
    except Exception as e: 
        res["error"] = f"{type(e).__name__}: {str(e)[:40]}"
    res["elapsed"] = round(time.time() - st, 3)
    return res

def _fetch_fdr(ctx):
    st = time.time()
    res = {"success": False, "source": "한국거래소(FDR)", "error": "", "data": {}}
    try:
        # [수정 3] KRX 과도한 동시 접속을 방어하기 위한 Semaphore 적용
        with _fdr_semaphore:
            krx = fdr.StockListing('KRX')
            
        target_col = next((c for c in ["ChangesRatio", "ChgRate", "ChangeRatio", "FluctuationRate", "Rate", "Change"] if c in krx.columns), None)
        if not target_col: raise RuntimeError("Col Search Fail")
        
        krx = krx.rename(columns={target_col: "ChangesRatio"})
        kpi_df, kdq_df = krx[krx['Market'] == 'KOSPI'], krx[krx['Market'] == 'KOSDAQ']
        fkp, fkd = len(kpi_df), len(kdq_df)
        
        data = {
            "kp_up": len(kpi_df[kpi_df['ChangesRatio']>0]), "kp_down": len(kpi_df[kpi_df['ChangesRatio']<0]), "kp_same": len(kpi_df[kpi_df['ChangesRatio']==0]),
            "kd_up": len(kdq_df[kdq_df['ChangesRatio']>0]), "kd_down": len(kdq_df[kdq_df['ChangesRatio']<0]), "kd_same": len(kdq_df[kdq_df['ChangesRatio']==0]),
            "fdr_kp_total": fkp, "fdr_kd_total": fkd
        }
        kp_sum = data["kp_up"] + data["kp_down"] + data["kp_same"]
        kd_sum = data["kd_up"] + data["kd_down"] + data["kd_same"]
        
        if _validate_data(data) and abs(kp_sum - fkp) <= 2 and abs(kd_sum - fkd) <= 2 and kp_sum >= (fkp * ctx["ratio"]) and kd_sum >= (fkd * ctx["ratio"]):
            res["success"] = True; res["data"] = data
        else: res["error"] = "Data Validation or Ratio Failed"
    except Exception as e: 
        res["error"] = f"{type(e).__name__}: {str(e)[:40]}"
    res["elapsed"] = round(time.time() - st, 3)
    return res

# =========================================================
# 8. Main Breadth Orchestrator & Consensus
# =========================================================
def _evaluate_consensus(valid_results: List[Dict], priority_map: Dict[str, float]) -> Tuple[Dict, int]:
    for r in valid_results: r["consensus"] = 0
    source_rms_diff = {r["source"]: 0.0 for r in valid_results}
    
    for r1, r2 in itertools.combinations(valid_results, 2):
        d1, d2 = r1["data"], r2["data"]
        diffs = [
            abs(d1.get("kp_up",0) - d2.get("kp_up",0)) / CONFIG.EXPECTED_KP_TOTAL,
            abs(d1.get("kp_down",0) - d2.get("kp_down",0)) / CONFIG.EXPECTED_KP_TOTAL,
            abs(d1.get("kp_same",0) - d2.get("kp_same",0)) / CONFIG.EXPECTED_KP_TOTAL,
            abs(d1.get("kd_up",0) - d2.get("kd_up",0)) / CONFIG.EXPECTED_KD_TOTAL,
            abs(d1.get("kd_down",0) - d2.get("kd_down",0)) / CONFIG.EXPECTED_KD_TOTAL,
            abs(d1.get("kd_same",0) - d2.get("kd_same",0)) / CONFIG.EXPECTED_KD_TOTAL,
        ]
        rms_diff = math.sqrt(sum(x**2 for x in diffs) / len(diffs))
        
        source_rms_diff[r1["source"]] = max(source_rms_diff[r1["source"]], rms_diff)
        source_rms_diff[r2["source"]] = max(source_rms_diff[r2["source"]], rms_diff)
        
        if rms_diff <= CONFIG.CROSS_CHECK_TOLERANCE:
            r1["consensus"] += 1
            r2["consensus"] += 1

    for r in valid_results:
        src = r["source"]
        src_key = _get_src_key(src)
        rms = source_rms_diff[src]
        
        conf = max(0.1, math.exp(CONFIG.CONFIDENCE_EXP_FACTOR * rms)) 
        r["confidence"] = conf
        
        hist_rel = _source_health_ema.get(src_key, 100.0) / 100.0
        r["final_score"] = (priority_map.get(src, 0) * hist_rel * conf) + (r["consensus"] * 15)
        
    valid_results.sort(key=lambda x: x["final_score"], reverse=True)
    winner = valid_results[0]
    
    agreeing_results = [r for r in valid_results if source_rms_diff[r["source"]] <= CONFIG.CROSS_CHECK_TOLERANCE]
    if len(agreeing_results) > 1:
        avg_data = {}
        for k in ["kp_up", "kp_down", "kp_same", "kd_up", "kd_down", "kd_same"]:
            avg_data[k] = int(sum(r["data"].get(k,0) for r in agreeing_results) / len(agreeing_results))
        winner["data"] = dict(winner["data"], **avg_data)
        logging.debug("[Consensus] Averaged %d sources for winner data.", len(agreeing_results))
        
    return winner, int(source_rms_diff[winner["source"]] * 100)

def load_breadth() -> Dict:
    global _breadth_cache, _health_history, _global_health_ema, _fdr_elapsed_ema
    start_time = time.time()
    ctx = _get_time_context()
    
    with _cache_lock:
        if _breadth_cache["data"] is not None and (start_time - _breadth_cache["timestamp"] < ctx["ttl"]) and (_breadth_cache["time_context"] == ctx["is_open"]):
            cached = copy.deepcopy(_breadth_cache["data"])
            age = int(start_time - _breadth_cache['timestamp'])
            
            orig_src = _breadth_cache.get("original_source", "FDR")
            decay_rate = {"FDR": 1.0, "API": 3.0, "DOM": 3.0}.get(_get_src_key(orig_src), 2.0)
            base_conf = _breadth_cache.get("confidence", 1.0)
            cached_conf = max(0.1, base_conf * math.exp(-decay_rate * (age / ctx["ttl"])))
            
            logging.debug("[Market] Source=CACHE(%s) | Age=%ds | Conf=%.2f", orig_src, age, cached_conf)
            
            return {
                "success": True, "source": f"CACHE({orig_src})", "confidence": cached_conf,
                "elapsed": round(age, 3), "diag": {}, "cross_penalty": 0, **cached
            }

    if ctx["is_open"]: priority_map = {"NAVER API": 100, "한국거래소(FDR)": 98, "NAVER DOM": 92}
    else: priority_map = {"한국거래소(FDR)": 100, "NAVER API": 95, "NAVER DOM": 90}

    task_map = {}
    if _check_cb("API"): task_map[_fetch_api] = "API"
    if _check_cb("DOM"): task_map[_fetch_dom] = "DOM"
    if _check_cb("FDR"): task_map[_fetch_fdr] = "FDR"

    futures_map = {_safe_submit(task, ctx): name for task, name in task_map.items()}
    valid_results = []
    diag_info = {k: SourceDiag(status="BLOCKED") for k in ["API", "DOM", "FDR"]}
    
    if futures_map:
        # [수정 2] 복잡한 FIRST_COMPLETED 논리 제거 및 직관적 ALL_COMPLETED 대기 적용
        timeout_val = min(5.0, max(2.5, (_fdr_elapsed_ema + 1.0)))
        done, not_done = wait(futures_map.keys(), timeout=timeout_val, return_when=ALL_COMPLETED)
        
        for f in done:
            src_key = futures_map[f]
            try:
                res = f.result()
                diag_info[src_key] = SourceDiag(status="PASS" if res["success"] else "FAIL", error=res["error"], elapsed=res["elapsed"])
                if src_key == "FDR" and res["success"]: _fdr_elapsed_ema = (_fdr_elapsed_ema * 0.8) + (res["elapsed"] * 0.2)
                _update_cb(src_key, res["success"], res["error"])
                if res["success"]: valid_results.append(res)
            except Exception as e:
                logging.debug("[Market] Task Error %s: %s", src_key, e, exc_info=True)
                
        for f in not_done:
            src_key = futures_map[f]
            is_cancelled = f.cancel()
            status_str = "Cancelled" if is_cancelled else "Zombie Thread"
            diag_info[src_key].error = f"Grace Exceeded: {status_str}"

    if valid_results:
        winner_res, cross_penalty = _evaluate_consensus(valid_results, priority_map)
        final_data = winner_res["data"]
        final_src = winner_res["source"]
        conf = winner_res["confidence"]
        success = True
    else:
        final_data = {}
        final_src, conf, cross_penalty, success = "NONE", 0.0, 0, False
        logging.error("[Market] ALL SOURCES FAILED")

    elapsed_total = round(time.time() - start_time, 3)
    
    with _cache_lock:
        _health_history.append(final_src if success else "FAIL")
        
        if not success: health_val = 0.0
        elif cross_penalty >= 20: health_val = 30.0
        elif cross_penalty >= 10: health_val = 60.0
        elif cross_penalty >= 5: health_val = 80.0
        else: health_val = 100.0
            
        _global_health_ema = (_global_health_ema * (1 - CONFIG.EMA_ALPHA_GLOBAL)) + (health_val * CONFIG.EMA_ALPHA_GLOBAL)
        
        # [수정 9] CACHE.set_breadth() 관련 NameError 원천봉쇄 및 딕셔너리 직접 할당으로 통일
        if success:
            _breadth_cache = {
                "timestamp": time.time(), 
                "data": copy.deepcopy(final_data), 
                "time_context": ctx["is_open"], 
                "original_source": final_src,
                "confidence": conf
            }
        
        runs = list(_health_history)
        if len(runs) > 0 and (len(runs) % 10 == 0 or not success):
            logging.debug("[Market Health] Global EMA: %.1f | FDR: %.1f | API: %.1f", _global_health_ema, _source_health_ema["FDR"], _source_health_ema["API"])

    return {
        "success": success, "source": final_src, "confidence": conf, "cross_penalty": cross_penalty,
        "elapsed": elapsed_total, "diag": {k: v.__dict__ for k, v in diag_info.items()}, **final_data
    }

# =========================================================
# 9. Quality Evaluation & Orchestration
# =========================================================
def calculate_quality(idx_data: Dict, b_data: Dict) -> Tuple[int, str, str]:
    q_score = 0
    reasons = []
    
    if idx_data.get("success"):
        if idx_data.get("partial"):
            if idx_data.get("kp_today", 0) <= 0: q_score += 2; reasons.append("KOSPI Fail (-8)")
            else: q_score += 7; reasons.append("KOSDAQ Fail (-3)")
        else: q_score += 10
    else: reasons.append("Index Fail")
        
    if b_data.get("success"): q_score += 30
    else: reasons.append("Breadth Fail")
    
    src_str = b_data.get("source", "")
    is_cache = src_str.startswith("CACHE")
    actual_src = src_str.replace("CACHE(", "").replace(")", "") if is_cache else src_str
    
    ctx = _get_time_context()
    fdr_kp, fdr_kd = b_data.get("fdr_kp_total", 0), b_data.get("fdr_kd_total", 0)
    
    if actual_src == "한국거래소(FDR)" and fdr_kp > 0:
        if b_data.get("kp_up",0) + b_data.get("kp_down",0) + b_data.get("kp_same",0) >= (fdr_kp * ctx["ratio"]): q_score += 20
        else: reasons.append("KOSPI Ratio Low")
        if b_data.get("kd_up",0) + b_data.get("kd_down",0) + b_data.get("kd_same",0) >= (fdr_kd * ctx["ratio"]): q_score += 20
        else: reasons.append("KOSDAQ Ratio Low")
    else:
        if b_data.get("kp_up",0) + b_data.get("kp_down",0) + b_data.get("kp_same",0) >= CONFIG.EXPECTED_KP_TOTAL * ctx["ratio"]: q_score += 20
        else: reasons.append("KOSPI Ratio Low")
        if b_data.get("kd_up",0) + b_data.get("kd_down",0) + b_data.get("kd_same",0) >= CONFIG.EXPECTED_KD_TOTAL * ctx["ratio"]: q_score += 20
        else: reasons.append("KOSDAQ Ratio Low")
        
    src_base = 20 if actual_src == "한국거래소(FDR)" else (18 if actual_src == "NAVER API" else 15)
    conf = b_data.get("confidence", 1.0)
    penalty = int((1.0 - conf) * 10)
    q_score += max(0, src_base - penalty)
    
    # [수정 6 & 7] Cache Format 명확화 및 Confidence 연동
    if is_cache: reasons.append(f"Cache ({actual_src}, Age:{int(b_data.get('elapsed', 0))}s, Conf:{conf:.2f})")
            
    conf_pen = int((1.0 - conf) * 20)
    cross_pen = b_data.get("cross_penalty", 0)
    tot_pen = max(conf_pen, cross_pen)
    
    if tot_pen > 0:
        q_score = max(0, q_score - tot_pen)
        reasons.append(f"Cross-Check Pen (-{tot_pen})")
    
    if _global_health_ema < 80.0:
        h_pen = int((80.0 - _global_health_ema) / 2)
        q_score = max(0, q_score - h_pen)
        reasons.append(f"Health Pen (-{h_pen})")
    
    state = "NORMAL" if q_score >= 90 else ("CAUTION" if q_score >= 80 else "INVALID")
    return q_score, state, "; ".join(reasons) if reasons else "All Clear"

def get_market_context() -> Dict:
    # 전역 Executor를 재사용한 완전 병렬 처리
    f_idx = _safe_submit(load_index)
    f_brd = _safe_submit(load_breadth)
    
    done, _ = wait([f_idx, f_brd], timeout=20, return_when=ALL_COMPLETED)
    
    idx = f_idx.result() if f_idx in done else {"success": False, "error": "Timeout", "partial": False}
    b = f_brd.result() if f_brd in done else {"success": False, "error": "Timeout", "diag": {}, "source": "NONE"}
        
    score, state, reason = calculate_quality(idx, b)
    val_pass = (state in ["NORMAL", "CAUTION"])
    
    logging.log(logging.INFO if val_pass else logging.WARNING, "[Market Final] State=%s | Score=%d | Reason=%s", state, score, reason)
    
    return {
        "state": state, "allow_scan": val_pass, "data_quality": score, "validation_pass": val_pass,
        "reason": reason, "breadth": b, "kospi_1d": idx.get("kp_1d", 0), "kosdaq_1d": idx.get("kd_1d", 0), 
        "source": b.get("source"), "partial": idx.get("partial", False)
    }
