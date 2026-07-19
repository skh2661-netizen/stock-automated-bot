import os
import re
import time
import math
import json
import hashlib
import logging
import datetime
import threading
import atexit
import itertools
import copy  # [수정 2] copy 모듈 import 확인
from dataclasses import dataclass, field
from collections import deque, Counter
from typing import Dict, Any, List, Tuple, Callable, Optional  # [수정 3] Optional 추가
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from concurrent.futures.thread import BrokenThreadPool

import pytz
import numpy as np
import pandas as pd
import requests
import FinanceDataReader as fdr
import yfinance as yf
from bs4 import BeautifulSoup, SoupStrainer
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3.util import Timeout

# =========================================================
# 1. Configuration (All Magic Numbers Extracted)
# =========================================================
@dataclass
class NetworkConfig:
    MAX_WORKERS: int = min(16, (os.cpu_count() or 2) * 2)
    ORCHESTRATOR_WORKERS: int = min(4, (os.cpu_count() or 2))
    TIMEOUT_CONNECT: float = 3.0
    TIMEOUT_READ: float = 7.0
    YF_TIMEOUT: float = 10.0
    MAX_INDEX_WAIT: float = 15.0

@dataclass
class QualityConfig:
    EXPECTED_KP_TOTAL: int = 950
    EXPECTED_KD_TOTAL: int = 1750
    CONFIDENCE_EXP_FACTOR: float = -5.0
    CROSS_CHECK_TOLERANCE: float = 0.05
    INDEX_REQUIRED_DAYS: int = 25
    HIGH_LATENCY_PENALTY: int = 2
    HIGH_LATENCY_THRESHOLD: float = 3.0

@dataclass
class CacheConfig:
    TTL_OPEN_EXTREME: int = 5    
    TTL_OPEN_HIGH: int = 10      
    TTL_OPEN_MID: int = 60       
    TTL_OPEN_END: int = 5        
    TTL_CLOSED: int = 600
    FDR_LISTING_TTL: int = 1800  
    STALE_SECONDS: int = 300
    STALE_ELAPSED_TOLERANCE: float = 0.1
    GRACE_TTL_MULTIPLIER: float = 1.5

@dataclass
class CircuitConfig:
    THRESHOLD_API: int = 3
    THRESHOLD_DOM: int = 5
    THRESHOLD_FDR: int = 2
    THRESHOLD_YAHOO: int = 3
    BASE_PENALTY: int = 1800
    HALF_OPEN_SUCCESS_REQ: int = 3
    PENALTY_429: int = 300
    PENALTY_AUTH: int = 1800
    PENALTY_NET: int = 600
    PENALTY_PARSE: int = 3600
    PENALTY_TIMEOUT: int = 900
    MAX_PENALTY: int = 14400

@dataclass
class EMAConfig:
    ALPHA_GLOBAL: float = 0.10
    ALPHA_SOURCE: float = 0.05
    BAYESIAN_DECAY: float = 0.98

@dataclass
class MarketConfig:
    NET: NetworkConfig = field(default_factory=NetworkConfig)
    QUAL: QualityConfig = field(default_factory=QualityConfig)
    CACHE: CacheConfig = field(default_factory=CacheConfig)
    CB: CircuitConfig = field(default_factory=CircuitConfig)
    EMA: EMAConfig = field(default_factory=EMAConfig)
    STATE_FILE: str = "market_health_state.json"
    STATE_VERSION: str = "1.3.2"
    SAVE_INTERVAL_SEC: int = 600  

CONFIG = MarketConfig()

# Logger Adapter 설정 (Context 주입형)
class ContextAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[{self.extra['ctx']}] {msg}", kwargs

_base_logger = logging.getLogger(__name__)
_logger = ContextAdapter(_base_logger, {'ctx': 'SYS'})

# =========================================================
# 2. Data Structures
# =========================================================
@dataclass
class SourceDiag:
    status: str = "FAIL"
    error: str = ""
    elapsed: float = 0.0
    age: int = 0

@dataclass
class CircuitBreakerState:
    fails: int = 0
    blocked_until: float = 0.0
    last_fail_time: float = 0.0
    state: str = "CLOSED"
    consecutive_successes: int = 0

@dataclass
class CacheEntry:
    timestamp: float = 0.0
    data: Dict[str, Any] = None
    time_context: bool = False
    original_source: str = ""
    confidence: float = 1.0

# =========================================================
# 3. Centralized Runtime State (관심사 통합)
# =========================================================
class MarketRuntimeState:
    def __init__(self):
        self.lock = threading.RLock()
        
        self.cb = {k: CircuitBreakerState() for k in ["API", "DOM", "FDR", "YAHOO"]}
        self.health_history = deque(maxlen=200)
        self.success_history = {"API": deque(maxlen=20), "DOM": deque(maxlen=20), "FDR": deque(maxlen=20)}
        self.latency_history = {"API": deque(maxlen=20), "DOM": deque(maxlen=20), "FDR": deque(maxlen=20)}
        self.consensus_history = deque(maxlen=5)
        
        self.global_health_ema = 100.0
        self.fdr_elapsed_ema = 3.0
        self.source_health_ema = {"FDR": 100.0, "API": 99.0, "DOM": 98.0, "YAHOO": 100.0}
        self.bayesian_stats = {
            "API": {"alpha": 10.0, "beta": 1.0}, "DOM": {"alpha": 10.0, "beta": 1.0},
            "FDR": {"alpha": 10.0, "beta": 1.0}, "YAHOO": {"alpha": 10.0, "beta": 1.0}
        }
        self.stale_tracker = {
            "API": {"data": None, "timestamp": 0, "elapsed": 0.0},
            "DOM": {"data": None, "timestamp": 0, "elapsed": 0.0},
            "FDR": {"data": None, "timestamp": 0, "elapsed": 0.0}
        }
        
        self.breadth_cache_gen = deque(maxlen=3)
        self.index_cache = CacheEntry()
        self.fdr_listing_cache = {"timestamp": 0, "data": None}
        self.fdr_col_cache = None
        
        self.last_save_time = time.time()

    def load_state(self):
        if not os.path.exists(CONFIG.STATE_FILE): return
        try:
            with open(CONFIG.STATE_FILE, "r", encoding="utf-8") as f:
                wrapper = json.load(f)
                
            payload_str = json.dumps(wrapper.get("payload", {}), sort_keys=True)
            if wrapper.get("hash") != hashlib.sha256(payload_str.encode('utf-8')).hexdigest():
                _logger.warning("State file hash mismatch! Data corrupted. Starting fresh.", extra={'ctx': 'STATE'})
                return

            state = wrapper["payload"]
            if state.get("version") != CONFIG.STATE_VERSION:
                _logger.warning("State version mismatch. Starting fresh.", extra={'ctx': 'STATE'})
                return
                
            with self.lock:
                self.global_health_ema = state.get("global_health_ema", 100.0)
                self.source_health_ema.update(state.get("source_health_ema", {}))
                self.bayesian_stats.update(state.get("bayesian_stats", {}))
                
                now = time.time()
                for k, v_dict in state.get("circuit_breakers", {}).items():
                    if k in self.cb:
                        if v_dict["state"] == "OPEN" and now >= v_dict["blocked_until"]:
                            v_dict["state"] = "HALF_OPEN"
                            v_dict["consecutive_successes"] = 0
                        self.cb[k] = CircuitBreakerState(**v_dict)
            _logger.info("Market health state restored successfully.", extra={'ctx': 'STATE'})
        except Exception as e:
            _logger.warning("Failed to load health state: %s", e, extra={'ctx': 'STATE'})

    def trigger_save(self, force=False):
        now = time.time()
        if not force and (now - self.last_save_time < CONFIG.SAVE_INTERVAL_SEC):
            return
            
        try:
            with self.lock:
                state_dict = {
                    "version": CONFIG.STATE_VERSION, "created": now,
                    "global_health_ema": self.global_health_ema,
                    "source_health_ema": self.source_health_ema,
                    "circuit_breakers": {k: v.__dict__ for k, v in self.cb.items()},
                    "bayesian_stats": self.bayesian_stats
                }
            
            payload_str = json.dumps(state_dict, sort_keys=True)
            wrapper = {"hash": hashlib.sha256(payload_str.encode('utf-8')).hexdigest(), "payload": state_dict}
            
            tmp_file = CONFIG.STATE_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(wrapper, f, indent=4)
                f.flush()
                os.fsync(f.fileno())  
            os.replace(tmp_file, CONFIG.STATE_FILE)
            self.last_save_time = now
        except Exception as e:
            _logger.warning("Failed to save health state: %s", e, extra={'ctx': 'STATE'})

    def get_adaptive_timeout(self, src: str, default: float = 5.0) -> float:
        with self.lock: hist = list(self.latency_history[src])
        if len(hist) < 5: return default
        arr = np.array(hist)
        med = np.median(arr)
        mad = np.median(np.abs(arr - med))
        return min(12.0, max(3.0, med + (3.0 * mad)))

STATE = MarketRuntimeState()
STATE.load_state()

# =========================================================
# 4. RCU Session & Generation Executors
# =========================================================
_thread_local = threading.local()
_old_sessions = deque()
_session_lock = threading.RLock()
_executor_lock = threading.RLock()

STRICT_TIMEOUT = Timeout(connect=CONFIG.NET.TIMEOUT_CONNECT, read=CONFIG.NET.TIMEOUT_READ)

_GLOBAL_ADAPTER = HTTPAdapter(
    pool_connections=CONFIG.NET.MAX_WORKERS, pool_maxsize=CONFIG.NET.MAX_WORKERS, 
    max_retries=Retry(total=3, connect=3, read=2, backoff_factor=1, respect_retry_after_header=True, allowed_methods=["GET"], status_forcelist=[500, 502, 503, 504])
)

_network_executor = None
_orchestrator_executor = None
_net_gen = 0
_orch_gen = 0

def _get_executor(is_orchestrator=False):
    global _network_executor, _orchestrator_executor, _net_gen, _orch_gen
    with _executor_lock:
        target_exe = _orchestrator_executor if is_orchestrator else _network_executor
        target_gen = _orch_gen if is_orchestrator else _net_gen
        
        if target_exe is None or getattr(target_exe, '_shutdown', False):
            new_exe = ThreadPoolExecutor(max_workers=CONFIG.NET.ORCHESTRATOR_WORKERS if is_orchestrator else CONFIG.NET.MAX_WORKERS)
            if is_orchestrator: _orchestrator_executor = new_exe; _orch_gen += 1
            else: _network_executor = new_exe; _net_gen += 1
            return new_exe, (target_gen + 1)
        return target_exe, target_gen

def _safe_submit(fn, is_orchestrator=False, *args, **kwargs):
    last_err = None
    for _ in range(2):
        try:
            exe, _ = _get_executor(is_orchestrator=is_orchestrator)
            return exe.submit(fn, *args, **kwargs)
        except (RuntimeError, BrokenThreadPool) as e:
            last_err = e
            exe._shutdown = True 
    _logger.exception("Failed to submit task to Executor: %s", last_err, extra={'ctx': 'EXEC'})
    raise RuntimeError("Failed to submit task to Executor.")

def _get_session():
    now = time.time()
    local = _thread_local
    if not hasattr(local, "session_data") or (now - local.session_data["created"] > 3600):
        if hasattr(local, "session_data"):
            with _session_lock: _old_sessions.append((local.session_data["session"], now))
            
        with _session_lock:
            active_sessions = []
            for s, t in _old_sessions:
                if now - t > 60: 
                    try: s.close()
                    except Exception: pass
                else: active_sessions.append((s, t))
            _old_sessions.clear()
            _old_sessions.extend(active_sessions)
                
        s = requests.Session()
        s.headers.update({'User-Agent': 'Mozilla/5.0'})
        s.mount("https://", _GLOBAL_ADAPTER); s.mount("http://", _GLOBAL_ADAPTER)
        local.session_data = {"session": s, "created": now}
    return local.session_data["session"]

@atexit.register
def cleanup():
    STATE.trigger_save(force=True)
    _GLOBAL_ADAPTER.close()
    with _session_lock:
        for s, _ in _old_sessions:
            try: s.close()
            except Exception: pass
    for v in getattr(_thread_local, "__dict__", {}).values():
        if isinstance(v, dict) and "session" in v:
            try: v["session"].close()
            except Exception: pass
    if _network_executor: _network_executor.shutdown(wait=False, cancel_futures=True)
    if _orchestrator_executor: _orchestrator_executor.shutdown(wait=False, cancel_futures=True)

# =========================================================
# 5. Common Wrappers & Utilities
# =========================================================
def _get_time_context() -> Dict[str, Any]:
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.datetime.now(kst)
    if now.weekday() >= 5: return {"is_open": False, "ttl": CONFIG.CACHE.TTL_CLOSED, "ratio": 0.80}
    t = now.time()
    if datetime.time(9, 0) <= t < datetime.time(9, 5): return {"is_open": True, "ttl": CONFIG.CACHE.TTL_OPEN_EXTREME, "ratio": 0.70} 
    elif datetime.time(9, 5) <= t < datetime.time(9, 20): return {"is_open": True, "ttl": CONFIG.CACHE.TTL_OPEN_HIGH, "ratio": 0.75} 
    elif datetime.time(9, 20) <= t < datetime.time(14, 50): return {"is_open": True, "ttl": CONFIG.CACHE.TTL_OPEN_MID, "ratio": 0.75}
    elif datetime.time(14, 50) <= t <= datetime.time(15, 30): return {"is_open": True, "ttl": CONFIG.CACHE.TTL_OPEN_END, "ratio": 0.75} 
    elif datetime.time(15, 30) < t <= datetime.time(15, 40): return {"is_open": False, "ttl": CONFIG.CACHE.TTL_OPEN_MID, "ratio": 0.80}
    else: return {"is_open": False, "ttl": CONFIG.CACHE.TTL_CLOSED, "ratio": 0.80}

def _validate_data(data: Dict[str, Any]) -> bool:
    for k, v in data.items():
        if isinstance(v, (int, float)):
            if math.isnan(v) or math.isinf(v) or v < 0: return False
            if k.startswith("kp_") and v > (CONFIG.QUAL.EXPECTED_KP_TOTAL + 50): return False
            if k.startswith("kd_") and v > (CONFIG.QUAL.EXPECTED_KD_TOTAL + 50): return False
    return True

def _copy_shallow_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    new_data = dict(data)
    if "diag" in new_data:
        new_data["diag"] = {k: dict(v) if isinstance(v, dict) else v for k, v in new_data["diag"].items()}
    return new_data

def _get_src_key(source_str: str) -> str:
    if "API" in source_str: return "API"
    if "DOM" in source_str: return "DOM"
    if "YAHOO" in source_str: return "YAHOO"
    return "FDR"

# =========================================================
# 6. Centralized Circuit Breaker & Health Logic
# =========================================================
def _check_cb(source_key: str) -> bool:
    with STATE.lock:
        cb = STATE.cb[source_key]
        if cb.state == "OPEN":
            if time.time() >= cb.blocked_until:
                cb.state = "HALF_OPEN"
                return True
            return False
            
        bs = STATE.bayesian_stats.get(source_key, {"alpha": 10.0, "beta": 1.0})
        bayesian_rel = bs["alpha"] / (bs["alpha"] + bs["beta"])
        src_ema = STATE.source_health_ema.get(source_key, 100.0)
        
        if bayesian_rel < 0.5 and src_ema < 70.0:
            _logger.warning("%s Predictive OPEN (Bayes:%.2f, EMA:%.1f)", source_key, bayesian_rel, src_ema, extra={'ctx': 'CB'})
            cb.state = "OPEN"
            cb.blocked_until = time.time() + CONFIG.CB.BASE_PENALTY
            STATE.trigger_save(force=True)
            return False
        return True

def _update_cb_and_health(source_key: str, success: bool, error_msg: str, elapsed: float):
    now = time.time()
    with STATE.lock:
        # Bayesian Update (Dirichlet Continuous Decay)
        bs = STATE.bayesian_stats[source_key]
        bs["alpha"] = bs["alpha"] * CONFIG.EMA.BAYESIAN_DECAY + (1.0 if success else 0.0)
        bs["beta"] = bs["beta"] * CONFIG.EMA.BAYESIAN_DECAY + (0.0 if success else 1.0)
        
        # Latency & Success History
        if success: STATE.latency_history[source_key].append(elapsed)
        STATE.success_history[source_key].append(1 if success else 0)
        
        # Source EMA
        current_ema = STATE.source_health_ema.get(source_key, 100.0)
        STATE.source_health_ema[source_key] = (current_ema * (1 - CONFIG.EMA.ALPHA_SOURCE)) + ((100.0 if success else 0.0) * CONFIG.EMA.ALPHA_SOURCE)
        
        # CB Update
        cb = STATE.cb[source_key]
        threshold = getattr(CONFIG.CB, f"THRESHOLD_{source_key}", 5)
        
        if success:
            if cb.state == "HALF_OPEN":
                cb.consecutive_successes += 1
                if cb.consecutive_successes >= CONFIG.CB.HALF_OPEN_SUCCESS_REQ and STATE.source_health_ema[source_key] > 85.0:
                    cb.fails = 0; cb.state = "CLOSED"; cb.consecutive_successes = 0
                    STATE.trigger_save(force=True)
            else:
                if (now - cb.last_fail_time > 1800) or STATE.source_health_ema[source_key] > 90.0: cb.fails = 0
                else: cb.fails = max(0, cb.fails - 1)
            cb.blocked_until = 0
        else:
            cb.fails += 1; cb.last_fail_time = now; cb.consecutive_successes = 0
            if cb.state == "HALF_OPEN" or cb.fails >= threshold:
                cb.state = "OPEN"
                power = max(0, (cb.fails // threshold) - 1)
                
                base_pen = CONFIG.CB.BASE_PENALTY
                if "429" in error_msg or "Too Many" in error_msg: base_pen = CONFIG.CB.PENALTY_429       
                elif any(e in error_msg for e in ["403", "404", "Access Denied"]): base_pen = CONFIG.CB.PENALTY_AUTH
                elif any(e in error_msg for e in ["SSL", "ConnectionResetError", "ChunkedEncodingError"]): base_pen = CONFIG.CB.PENALTY_NET
                elif "Parse" in error_msg or "Validation" in error_msg: base_pen = CONFIG.CB.PENALTY_PARSE
                elif "Timeout" in error_msg: base_pen = CONFIG.CB.PENALTY_TIMEOUT                           
                
                penalty = min(base_pen * (2 ** power), CONFIG.CB.MAX_PENALTY)
                cb.blocked_until = now + penalty
                _logger.warning("%s OPEN for %d mins (Err: %s)", source_key, penalty // 60, error_msg[:30], extra={'ctx': 'CB'})
                STATE.trigger_save(force=True)

# =========================================================
# 7. Common Fetch Wrappers (Deduplication)
# =========================================================
def _run_fetch_task(src_key: str, fn: Callable, ctx: Dict) -> Tuple[Dict, SourceDiag]:
    st = time.time()
    try:
        res = fn(ctx)
        elapsed = res.get("elapsed", time.time() - st)
        diag = SourceDiag(status="PASS" if res.get("success") else "FAIL", error=res.get("error", ""), elapsed=elapsed)
    except Exception as e:
        elapsed = time.time() - st
        res = {"success": False, "source": src_key, "error": f"{type(e).__name__}: {str(e)[:40]}", "data": {}}
        diag = SourceDiag(status="FAIL", error=res["error"], elapsed=elapsed)
        
    # [수정 1] 함수명 오류 완벽 교정 (_update_cb_and_health)
    _update_cb_and_health(src_key, res["success"], res.get("error", ""), elapsed)
    return res, diag

def _parallel_fetch(task_map: Dict[str, Callable], ctx: Dict, global_timeout: float) -> Tuple[List[Dict], Dict[str, SourceDiag]]:
    futures_map = {_safe_submit(_run_fetch_task, is_orchestrator=False, src_key=name, fn=task, ctx=ctx): name for name, task in task_map.items()}
    valid_results = []
    diag_info = {k: SourceDiag(status="BLOCKED") for k in task_map.keys()}
    
    if futures_map:
        done, not_done = wait(futures_map.keys(), timeout=global_timeout, return_when=ALL_COMPLETED)
        for f in done:
            src_key = futures_map[f]
            if f.done():
                try:
                    res, diag = f.result(timeout=0.1)
                    diag_info[src_key] = diag
                    if res["success"]: valid_results.append(res)
                except Exception as e:
                    _logger.warning("Fetch Exception for %s: %s", src_key, e, extra={'ctx': 'FETCH'})
        
        for f in not_done:
            src_key = futures_map[f]
            f.cancel()
            diag_info[src_key].error = "Grace Exceeded (Zombie)"
            
    return valid_results, diag_info

# =========================================================
# 8. Fetcher Implementations (API, DOM, FDR, YF)
# =========================================================
_fdr_listing_sem = threading.Semaphore(1)
_fdr_reader_sem = threading.Semaphore(1)
_yf_semaphore = threading.Semaphore(1)

def _fdr_data_reader_safe(ctx: Dict):
    st = time.time()
    symbol = ctx.get("symbol")
    with _fdr_reader_sem:
        df = fdr.DataReader(symbol, ctx.get("start_date"))
        return {"success": True, "source": symbol, "data": df, "elapsed": time.time() - st}

def _check_stale(src: str, new_data: Dict, is_open: bool, elapsed: float) -> Tuple[bool, int]:
    with STATE.lock:
        now = time.time()
        last = STATE.stale_tracker[src]
        
        if last["data"] and is_open:
            is_same = all(new_data.get(k) == last["data"].get(k) for k in ["kp_up", "kp_down", "kd_up", "kd_down"])
            elapsed_same = abs(last["elapsed"] - elapsed) < CONFIG.CACHE.STALE_ELAPSED_TOLERANCE
            
            if is_same:
                age = now - last["timestamp"]
                if age > CONFIG.CACHE.STALE_SECONDS or elapsed_same: 
                    return True, int(age)
                return False, 0
                
        STATE.stale_tracker[src] = {"data": new_data, "timestamp": now, "elapsed": elapsed}
        return False, 0

def _fetch_api_raw(ctx: Dict) -> Dict:
    session = _get_session()
    r_kp = session.get("https://m.stock.naver.com/api/index/KOSPI/price", timeout=STRICT_TIMEOUT)
    r_kd = session.get("https://m.stock.naver.com/api/index/KOSDAQ/price", timeout=STRICT_TIMEOUT)
    r_kp.raise_for_status(); r_kd.raise_for_status()
    
    kp_rf, kd_rf = r_kp.json()[0].get("riseFall", {}), r_kd.json()[0].get("riseFall", {})
    data = {"kp_up": int(kp_rf.get("rise",0)), "kp_down": int(kp_rf.get("fall",0)), "kp_same": int(kp_rf.get("same",0)),
            "kd_up": int(kd_rf.get("rise",0)), "kd_down": int(kd_rf.get("fall",0)), "kd_same": int(kd_rf.get("same",0))}
    
    if not _validate_data(data): return {"success": False, "error": "Validation Failed", "data": {}}
    
    is_stale, stale_age = _check_stale("API", data, ctx["is_open"], 0.0)
    if is_stale: return {"success": False, "error": f"Stale Data ({stale_age}s)", "data": {}}
    
    if sum([data["kp_up"], data["kp_down"], data["kp_same"]]) >= (CONFIG.QUAL.EXPECTED_KP_TOTAL * ctx["ratio"]):
        return {"success": True, "data": data}
    return {"success": False, "error": "Ratio Failed", "data": {}}

def _fetch_dom_raw(ctx: Dict) -> Dict:
    session = _get_session()
    strainer = SoupStrainer('dl', class_='lst_kos_info')
    def parse(code):
        r = session.get(f"https://finance.naver.com/sise/sise_index.naver?code={code}", timeout=STRICT_TIMEOUT)
        r.raise_for_status()
        dl = BeautifulSoup(r.text, 'lxml', parse_only=strainer)
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
    
    if not _validate_data(data): return {"success": False, "error": "Validation Failed", "data": {}}
    is_stale, stale_age = _check_stale("DOM", data, ctx["is_open"], 0.0)
    if is_stale: return {"success": False, "error": f"Stale Data ({stale_age}s)", "data": {}}
    if sum([kp_u,kp_d,kp_s]) >= (CONFIG.QUAL.EXPECTED_KP_TOTAL * ctx["ratio"]): return {"success": True, "data": data}
    return {"success": False, "error": "Ratio Failed", "data": {}}

def _fetch_fdr_raw(ctx: Dict) -> Dict:
    now = time.time()
    with _fdr_listing_sem:
        with STATE.lock:
            if STATE.fdr_listing_cache["data"] is not None and (now - STATE.fdr_listing_cache["timestamp"] < CONFIG.CACHE.FDR_LISTING_TTL):
                krx = STATE.fdr_listing_cache["data"] 
            else:
                krx = fdr.StockListing('KRX')
                STATE.fdr_listing_cache = {"timestamp": now, "data": krx}
                
    with STATE.lock:
        if STATE.fdr_col_cache is None or STATE.fdr_col_cache not in krx.columns:
            STATE.fdr_col_cache = next((c for c in ["ChangesRatio", "ChgRate", "ChangeRatio", "FluctuationRate", "Rate", "Change"] if c in krx.columns), None)
            if not STATE.fdr_col_cache: raise RuntimeError("Col Search Fail")
        col_cache = STATE.fdr_col_cache

    krx_renamed = krx.rename(columns={col_cache: "ChangesRatio"})
    kpi_df, kdq_df = krx_renamed[krx_renamed['Market'] == 'KOSPI'], krx_renamed[krx_renamed['Market'] == 'KOSDAQ']
    fkp, fkd = len(kpi_df), len(kdq_df)
    
    data = {"kp_up": len(kpi_df[kpi_df['ChangesRatio']>0]), "kp_down": len(kpi_df[kpi_df['ChangesRatio']<0]), "kp_same": len(kpi_df[kpi_df['ChangesRatio']==0]),
            "kd_up": len(kdq_df[kdq_df['ChangesRatio']>0]), "kd_down": len(kdq_df[kdq_df['ChangesRatio']<0]), "kd_same": len(kdq_df[kdq_df['ChangesRatio']==0]),
            "fdr_kp_total": fkp, "fdr_kd_total": fkd}
            
    kp_sum, kd_sum = data["kp_up"] + data["kp_down"] + data["kp_same"], data["kd_up"] + data["kd_down"] + data["kd_same"]
    if _validate_data(data) and abs(kp_sum - fkp) <= 2 and abs(kd_sum - fkd) <= 2 and kp_sum >= (fkp * ctx["ratio"]):
        return {"success": True, "data": data}
    return {"success": False, "error": "Ratio/Match Failed", "data": {}}

# =========================================================
# 9. Load Index (Refactored)
# =========================================================
def load_index() -> Dict:
    st_idx = time.time()
    ctx = _get_time_context()
    
    with STATE.lock:
        if STATE.index_cache.data is not None and (st_idx - STATE.index_cache.timestamp < ctx["ttl"]) and (STATE.index_cache.time_context == ctx["is_open"]):
            return _copy_shallow_dict(STATE.index_cache.data)

    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    idx_data = {
        "success": False, "partial": False, "error": None,
        "kp_today": 0.0, "kp_prev": 0.0, "kp_1d": 0.0, "kp_5d": 0.0, "kp_20d": 0.0,
        "kd_today": 0.0, "kd_prev": 0.0, "kd_1d": 0.0, "kd_5d": 0.0, "kd_20d": 0.0,
        "elapsed": 0.0
    }
    
    task_map = {
        "KS11": lambda c: _fdr_data_reader_safe({"symbol": "KS11", "start_date": start_date}),
        "KQ11": lambda c: _fdr_data_reader_safe({"symbol": "KQ11", "start_date": start_date})
    }
    
    valid_results, diag_info = _parallel_fetch(task_map, ctx, global_timeout=CONFIG.NET.MAX_INDEX_WAIT)
    
    kp, kd = None, None
    for r in valid_results:
        if r["source"] == "KS11": kp = r["data"]
        elif r["source"] == "KQ11": kd = r["data"]
    
    for k, v in diag_info.items():
        if v.status == "FAIL":
            idx_data["error"] = f"{idx_data['error']} | {k}: {v.error}" if idx_data["error"] else f"{k}: {v.error}"

    yahoo_used, yahoo_ok = False, True
    def _fallback_yf(symbol: str):
        with _yf_semaphore:
            for _ in range(2):
                try:
                    df = yf.download(symbol, period="3mo", progress=False, timeout=CONFIG.NET.YF_TIMEOUT)
                    if df is not None and not df.empty:
                        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                        if 'Adj Close' in df.columns: df = df.rename(columns={'Adj Close': 'Close'})
                        return df
                except Exception: time.sleep(0.5)
            return None

    if (kp is None or "Close" not in kp.columns or len(kp) < CONFIG.QUAL.INDEX_REQUIRED_DAYS) and _check_cb("YAHOO"):
        yahoo_used = True; kp = _fallback_yf("^KS11")
        if kp is None: yahoo_ok = False
    if (kd is None or "Close" not in kd.columns or len(kd) < CONFIG.QUAL.INDEX_REQUIRED_DAYS) and _check_cb("YAHOO"):
        yahoo_used = True; kd = _fallback_yf("^KQ11")
        if kd is None: yahoo_ok = False

    if yahoo_used: _update_cb_and_health("YAHOO", yahoo_ok, "" if yahoo_ok else "Fallback Failed", 0.0)

    kp_ok = kp is not None and "Close" in kp.columns and len(kp) >= CONFIG.QUAL.INDEX_REQUIRED_DAYS
    kd_ok = kd is not None and "Close" in kd.columns and len(kd) >= CONFIG.QUAL.INDEX_REQUIRED_DAYS

    if kp_ok:
        kpc = kp['Close'].dropna().values
        idx_data.update({"kp_today": float(kpc[-1]), "kp_prev": float(kpc[-2]), "kp_1d": round((kpc[-1]/kpc[-2]-1)*100, 2), "kp_5d": round((kpc[-1]/kpc[-6]-1)*100, 2), "kp_20d": round((kpc[-1]/kpc[-21]-1)*100, 2)})
    if kd_ok:
        kdc = kd['Close'].dropna().values
        idx_data.update({"kd_today": float(kdc[-1]), "kd_prev": float(kdc[-2]), "kd_1d": round((kdc[-1]/kdc[-2]-1)*100, 2), "kd_5d": round((kdc[-1]/kdc[-6]-1)*100, 2), "kd_20d": round((kdc[-1]/kdc[-21]-1)*100, 2)})
        
    idx_data["success"] = kp_ok or kd_ok
    idx_data["partial"] = kp_ok != kd_ok
    idx_data["elapsed"] = round(time.time() - st_idx, 3)
    if not idx_data["success"] and not idx_data["error"]: idx_data["error"] = "Validation Failed"
    
    if idx_data["success"]:
        with STATE.lock: STATE.index_cache = CacheEntry(timestamp=time.time(), data=_copy_shallow_dict(idx_data), time_context=ctx["is_open"])
    return idx_data

# =========================================================
# 10. Load Breadth & Consensus (Refactored 6 Steps)
# =========================================================
def _get_cached_breadth(ctx: Dict) -> Optional[Dict]:
    with STATE.lock:
        if len(STATE.breadth_cache_gen) > 0:
            c = STATE.breadth_cache_gen[0]
            age = int(time.time() - c["timestamp"])
            if c["data"] is not None and (c["time_context"] == ctx["is_open"]):
                if age < ctx["ttl"]:
                    cached = dict(c["data"])
                    orig_src = c.get("original_source", "FDR")
                    return {"success": True, "source": f"CACHE({orig_src})", "confidence": c.get("confidence", 1.0), "elapsed": round(age, 3), "diag": {}, "cross_penalty": 0, **cached}
                elif age < ctx["ttl"] * CONFIG.CACHE.GRACE_TTL_MULTIPLIER:
                    cached = dict(c["data"])
                    orig_src = c.get("original_source", "FDR")
                    decay_rate = {"FDR": 1.0, "API": 3.0, "DOM": 3.0}.get(_get_src_key(orig_src), 2.0)
                    cached_conf = max(0.1, c.get("confidence", 1.0) * math.exp(-decay_rate * (age / ctx["ttl"])))
                    if _logger.isEnabledFor(logging.DEBUG): _logger.debug("Grace Hit (%s) | Age=%ds | Conf=%.2f", orig_src, age, cached_conf, extra={'ctx': 'CACHE'})
                    return {"success": True, "source": f"CACHE({orig_src})", "confidence": cached_conf, "elapsed": round(age, 3), "diag": {}, "cross_penalty": 0, **cached}
    return None

def _plan_and_fetch_breadth(ctx: Dict) -> Tuple[List[Dict], Dict[str, SourceDiag]]:
    task_map = {}
    if _check_cb("API"): task_map["API"] = _fetch_api_raw
    if _check_cb("DOM"): task_map["DOM"] = _fetch_dom_raw
    if _check_cb("FDR"): task_map["FDR"] = _fetch_fdr_raw
    
    max_timeout = max([STATE.get_adaptive_timeout(src) for src in task_map.keys()] + [3.0])
    return _parallel_fetch(task_map, ctx, max_timeout)

def _build_consensus(valid_results: List[Dict], ctx: Dict) -> Tuple[Dict, int]:
    priority_map = {"NAVER API": 100, "한국거래소(FDR)": 98, "NAVER DOM": 92} if ctx["is_open"] else {"한국거래소(FDR)": 100, "NAVER API": 95, "NAVER DOM": 90}
    
    for r in valid_results: r["consensus"] = 0
    source_rms_diff = {r["source"]: 0.0 for r in valid_results}
    
    for r1, r2 in itertools.combinations(valid_results, 2):
        d1, d2 = r1["data"], r2["data"]
        diffs = [
            abs(d1.get("kp_up",0) - d2.get("kp_up",0)) / CONFIG.QUAL.EXPECTED_KP_TOTAL,
            abs(d1.get("kp_down",0) - d2.get("kp_down",0)) / CONFIG.QUAL.EXPECTED_KP_TOTAL,
            abs(d1.get("kd_up",0) - d2.get("kd_up",0)) / CONFIG.QUAL.EXPECTED_KD_TOTAL,
            abs(d1.get("kd_down",0) - d2.get("kd_down",0)) / CONFIG.QUAL.EXPECTED_KD_TOTAL,
        ]
        rms_diff = math.sqrt(sum(x**2 for x in diffs) / len(diffs))
        source_rms_diff[r1["source"]] = max(source_rms_diff[r1["source"]], rms_diff)
        source_rms_diff[r2["source"]] = max(source_rms_diff[r2["source"]], rms_diff)
        if rms_diff <= CONFIG.QUAL.CROSS_CHECK_TOLERANCE:
            r1["consensus"] += 1; r2["consensus"] += 1

    with STATE.lock: history_counter = Counter(list(STATE.consensus_history))
    
    for r in valid_results:
        src_key = _get_src_key(r["source"])
        rms = source_rms_diff[r["source"]]
        r["confidence"] = max(0.1, math.exp(CONFIG.QUAL.CONFIDENCE_EXP_FACTOR * rms)) 
        with STATE.lock:
            bs = STATE.bayesian_stats.get(src_key, {"alpha": 10.0, "beta": 1.0})
            bayesian_rel = bs["alpha"] / (bs["alpha"] + bs["beta"])
        history_bonus = (history_counter.get(src_key, 0) / 5.0) * 5.0 
        r["final_score"] = (priority_map.get(r["source"], 0) * bayesian_rel * r["confidence"]) + (r["consensus"] * 15) + history_bonus
        
    winner_cand = max(valid_results, key=lambda x: x["final_score"])
    winner = copy.deepcopy(winner_cand)  # [수정 2] 원본 보존을 위한 Deepcopy
    with STATE.lock: STATE.consensus_history.append(_get_src_key(winner["source"]))
    
    agreeing_results = [r for r in valid_results if source_rms_diff[r["source"]] <= CONFIG.QUAL.CROSS_CHECK_TOLERANCE]
    if len(agreeing_results) > 1:
        avg_data = {}
        for k in ["kp_up", "kp_down", "kp_same", "kd_up", "kd_down", "kd_same"]:
            avg_data[k] = int(np.median([r["data"].get(k, 0) for r in agreeing_results]))
        winner["data"] = dict(winner["data"], **avg_data)
        
    return winner, int(source_rms_diff[winner["source"]] * 100)

def _update_health(success: bool, final_src: str, cross_penalty: int):
    with STATE.lock:
        STATE.health_history.append(final_src if success else "FAIL")
        health_val = max(0.0, 100.0 - cross_penalty) if success else 0.0
        STATE.global_health_ema = (STATE.global_health_ema * (1 - CONFIG.EMA.ALPHA_GLOBAL)) + (health_val * CONFIG.EMA.ALPHA_GLOBAL)
        
        runs = list(STATE.health_history)
        if len(runs) > 0 and (len(runs) % 10 == 0 or not success):
            _logger.info("Global EMA: %.1f | FDR EMA: %.1f", STATE.global_health_ema, STATE.source_health_ema.get("FDR", 100.0), extra={'ctx': 'HLTH'})

def _save_cache_breadth(final_data: Dict, final_src: str, conf: float, ctx: Dict):
    with STATE.lock:
        STATE.breadth_cache_gen.appendleft({"timestamp": time.time(), "data": dict(final_data), "time_context": ctx["is_open"], "original_source": final_src, "confidence": conf})

def load_breadth() -> Dict:
    start_time = time.time()
    ctx = _get_time_context()
    
    cached = _get_cached_breadth(ctx)
    if cached: return cached

    valid_results, diag_info = _plan_and_fetch_breadth(ctx)

    if valid_results:
        winner_res, cross_penalty = _build_consensus(valid_results, ctx)
        final_data, final_src, conf, success = winner_res["data"], winner_res["source"], winner_res["confidence"], True
    else:
        final_data, final_src, conf, cross_penalty, success = {}, "NONE", 0.0, 0, False
        _logger.warning("ALL SOURCES FAILED", extra={'ctx': 'BRD'})

    _update_health(success, final_src, cross_penalty)
    if success: _save_cache_breadth(final_data, final_src, conf, ctx)
    STATE.trigger_save()

    return {"success": success, "source": final_src, "confidence": conf, "cross_penalty": cross_penalty, "elapsed": round(time.time() - start_time, 3), "diag": {k: v.__dict__ for k, v in diag_info.items()}, **final_data}

# =========================================================
# 11. Quality Evaluator (Modularized)
# =========================================================
def _score_index(idx_data: Dict) -> Tuple[int, List[str]]:
    if not idx_data.get("success"): return -30, ["CRITICAL: Index Fail (-30)"]
    if idx_data.get("partial"):
        if idx_data.get("kp_today", 0) <= 0: return 2, ["KOSPI Fail (-8)"]
        else: return 7, ["KOSDAQ Fail (-3)"]
    return 10, []

def _score_breadth(b_data: Dict, actual_src: str, ctx: Dict) -> Tuple[int, List[str]]:
    if not b_data.get("success"): return 0, ["Breadth Fail"]
    score, reasons = 30, []
    
    tgt_kp = b_data.get("fdr_kp_total") if (actual_src == "한국거래소(FDR)" and b_data.get("fdr_kp_total", 0) > 0) else CONFIG.QUAL.EXPECTED_KP_TOTAL
    tgt_kd = b_data.get("fdr_kd_total") if (actual_src == "한국거래소(FDR)" and b_data.get("fdr_kd_total", 0) > 0) else CONFIG.QUAL.EXPECTED_KD_TOTAL
    
    kp_val = b_data.get("kp_up",0) + b_data.get("kp_down",0) + b_data.get("kp_same",0)
    kd_val = b_data.get("kd_up",0) + b_data.get("kd_down",0) + b_data.get("kd_same",0)
    
    if kp_val >= (tgt_kp * ctx["ratio"]): score += 20
    else: reasons.append("KOSPI Ratio Low")
    if kd_val >= (tgt_kd * ctx["ratio"]): score += 20
    else: reasons.append("KOSDAQ Ratio Low")
    return score, reasons

def _score_health(b_data: Dict, actual_src: str) -> Tuple[int, List[str]]:
    src_key = _get_src_key(actual_src)
    with STATE.lock:
        bs = STATE.bayesian_stats.get(src_key, {"alpha": 10.0, "beta": 1.0})
        bayesian_rel = bs["alpha"] / (bs["alpha"] + bs["beta"])
        g_ema = STATE.global_health_ema
        
    src_base = int(20 * bayesian_rel)
    conf = b_data.get("confidence", 1.0)
    tot_pen = int(((1.0 - conf) * 20 * 0.4) + (b_data.get("cross_penalty", 0) * 0.6))
    
    score = max(0, src_base - tot_pen)
    reasons = [f"Validation Pen (-{tot_pen})"] if tot_pen > 0 else []
    
    if g_ema < 80.0:
        h_pen = int((80.0 - g_ema) / 2)
        score = max(0, score - h_pen)
        reasons.append(f"Health Pen (-{h_pen})")
    return score, reasons

def _score_latency(b_data: Dict) -> Tuple[int, List[str]]:
    if b_data.get('elapsed', 0) > CONFIG.QUAL.HIGH_LATENCY_THRESHOLD: 
        return -CONFIG.QUAL.HIGH_LATENCY_PENALTY, [f"High Latency (-{CONFIG.QUAL.HIGH_LATENCY_PENALTY})"]
    return 0, []

def calculate_quality(idx_data: Dict, b_data: Dict) -> Tuple[int, str, str]:
    q_score, reasons = 0, []
    
    s_idx, r_idx = _score_index(idx_data); q_score += s_idx; reasons.extend(r_idx)
    
    src_str = b_data.get("source", "")
    is_cache = src_str.startswith("CACHE")
    actual_src = src_str.replace("CACHE(", "").replace(")", "") if is_cache else src_str
    
    s_brd, r_brd = _score_breadth(b_data, actual_src, _get_time_context()); q_score += s_brd; reasons.extend(r_brd)
    # [수정 4] 오타 완벽 교정 (r_brd -> r_hlth)
    s_hlth, r_hlth = _score_health(b_data, actual_src); q_score += s_hlth; reasons.extend(r_hlth) 
    s_lat, r_lat = _score_latency(b_data); q_score += s_lat; reasons.extend(r_lat)
    
    if is_cache: reasons.append(f"Cache ({actual_src}, Age:{int(b_data.get('elapsed', 0))}s)")
    
    state = "NORMAL" if q_score >= 90 else ("CAUTION" if q_score >= 80 else "INVALID")
    return q_score, state, "; ".join(set(reasons)) if reasons else "All Clear"

# =========================================================
# 12. Public API Orchestrator
# =========================================================
def health_snapshot() -> Dict[str, Any]:
    with STATE.lock:
        success_rates = {k: np.mean(list(v)) if v else 0.0 for k, v in STATE.success_history.items()}
        return {
            "global_ema": round(STATE.global_health_ema, 2),
            "success_rate": {k: round(v*100, 1) for k, v in success_rates.items()},
            "bayesian": {k: round(_get_bayesian_reliability(k)*100, 1) for k in STATE.bayesian_stats.keys()},
            "circuit_breakers": {k: v.state for k, v in STATE.cb.items()}
        }

def auto_self_test():
    _logger.info("Running Network Ping Test...", extra={'ctx': 'INIT'})
    try:
        requests.head("https://m.stock.naver.com", timeout=3.0)
        requests.head("https://finance.yahoo.com", timeout=3.0)
    except Exception as e:
        _logger.warning("Initial Ping Test Failed: %s", e, extra={'ctx': 'INIT'})
    _logger.info("Ping Test Complete. %s", health_snapshot(), extra={'ctx': 'INIT'})

def get_market_context() -> Dict:
    f_idx = _safe_submit(load_index, is_orchestrator=True)
    f_brd = _safe_submit(load_breadth, is_orchestrator=True)
    
    done, _ = wait([f_idx, f_brd], timeout=20, return_when=ALL_COMPLETED)
    
    if f_idx in done and f_idx.done():
        try: idx = f_idx.result(timeout=0.1)
        except Exception: idx = {"success": False, "error": "Execution Failed", "partial": False}
    else: idx = {"success": False, "error": "Timeout", "partial": False}
        
    if f_brd in done and f_brd.done():
        try: b = f_brd.result(timeout=0.1)
        except Exception: b = {"success": False, "error": "Execution Failed", "diag": {}, "source": "NONE"}
    else: b = {"success": False, "error": "Timeout", "diag": {}, "source": "NONE"}
        
    score, state, reason = calculate_quality(idx, b)
    val_pass = (state in ["NORMAL", "CAUTION"])
    
    _logger.log(logging.INFO if val_pass else logging.WARNING, "State=%s | Score=%d | Reason=%s", state, score, reason, extra={'ctx': 'FINAL'})
    
    return {
        "state": state, "allow_scan": val_pass, "data_quality": score, "validation_pass": val_pass,
        "reason": reason, "breadth": b, "kospi_1d": idx.get("kp_1d", 0), "kosdaq_1d": idx.get("kd_1d", 0), 
        "source": b.get("source"), "partial": idx.get("partial", False)
    }

# Bootstrap
auto_self_test()
