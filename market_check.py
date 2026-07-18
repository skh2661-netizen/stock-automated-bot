import datetime
import pytz
import FinanceDataReader as fdr
import requests
from bs4 import BeautifulSoup
import time
import re
import logging
import copy
import atexit
import threading
from collections import deque, Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED, ALL_COMPLETED
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 1. 전역 설정 및 락
_cache_lock = threading.Lock()
_cb_lock = threading.Lock()
_breadth_cache = {"timestamp": 0, "data": None, "market_status": False}
_index_cache = {"timestamp": 0, "data": None, "market_status": False} 
BREADTH_THRESHOLD = 700

# Health Monitor & Circuit Breaker (시간 기반 리셋 추가)
_health_history = deque(maxlen=100)
_circuit_breakers = {
    "API": {"fails": 0, "blocked_until": 0, "last_fail_time": 0},
    "DOM": {"fails": 0, "blocked_until": 0, "last_fail_time": 0},
    "FDR": {"fails": 0, "blocked_until": 0, "last_fail_time": 0}
}
CB_THRESHOLD = 5
CB_BASE_PENALTY = 1800  # 30분

# 2. Thread-Local Session 관리
_thread_local = threading.local()

def _get_session():
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.mount("http://", HTTPAdapter(max_retries=retry))
        _thread_local.session = session
    return _thread_local.session

atexit.register(lambda: [s.close() for s in getattr(_thread_local, "__dict__", {}).values() if hasattr(s, "close")])

def _is_market_open():
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.datetime.now(kst)
    if now.weekday() >= 5: return False
    market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close

def _get_dynamic_ttl():
    return 60 if _is_market_open() else 600

def _check_cb(source_key):
    with _cb_lock:
        return time.time() >= _circuit_breakers[source_key]["blocked_until"]

def _update_cb(source_key, success):
    with _cb_lock:
        now = time.time()
        if success:
            # 30분(1800초) 이상 무사고 시 완전 초기화, 아니면 점진 차감
            if now - _circuit_breakers[source_key]["last_fail_time"] > 1800:
                _circuit_breakers[source_key]["fails"] = 0
            else:
                _circuit_breakers[source_key]["fails"] = max(0, _circuit_breakers[source_key]["fails"] - 1)
            _circuit_breakers[source_key]["blocked_until"] = 0
        else:
            _circuit_breakers[source_key]["fails"] += 1
            _circuit_breakers[source_key]["last_fail_time"] = now
            fails = _circuit_breakers[source_key]["fails"]
            if fails >= CB_THRESHOLD:
                power = max(0, (fails // CB_THRESHOLD) - 1)
                penalty = min(CB_BASE_PENALTY * (2 ** power), 14400)
                _circuit_breakers[source_key]["blocked_until"] = now + penalty
                logging.error(f"[Circuit Breaker] {source_key} BLOCKED for {penalty//60} mins (Fails: {fails})")

def load_index():
    global _index_cache
    st_idx = time.time()
    cache_ttl = _get_dynamic_ttl()
    current_market_status = _is_market_open()
    
    with _cache_lock:
        if _index_cache["data"] is not None and (st_idx - _index_cache["timestamp"] < cache_ttl) and (_index_cache["market_status"] == current_market_status):
            cached = copy.deepcopy(_index_cache["data"])
            logging.debug(f"[Market] Index Source=CACHE | Age={int(st_idx - _index_cache['timestamp'])}s")
            return cached

    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    idx_data = {
        "success": False, "partial": False, "error": None,
        "kp_today": 0.0, "kp_prev": 0.0, "kp_1d": 0.0, "kp_5d": 0.0, "kp_20d": 0.0,
        "kd_today": 0.0, "kd_prev": 0.0, "kd_1d": 0.0, "kd_5d": 0.0, "kd_20d": 0.0,
        "elapsed": 0.0
    }
    
    kp, kd = None, None
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_kp = executor.submit(fdr.DataReader, "KS11", start_date)
        f_kd = executor.submit(fdr.DataReader, "KQ11", start_date)
        
        done, not_done = wait([f_kp, f_kd], timeout=15, return_when=ALL_COMPLETED)
        
        if f_kp in done:
            try: kp = f_kp.result()
            except Exception as e: 
                idx_data["error"] = f"KOSPI: {type(e).__name__} {str(e)[:50]}"
        else: idx_data["error"] = "KOSPI: Timeout"
            
        if f_kd in done:
            try: kd = f_kd.result()
            except Exception as e:
                err_msg = f"KOSDAQ: {type(e).__name__} {str(e)[:50]}"
                idx_data["error"] = idx_data["error"] + " | " + err_msg if idx_data["error"] else err_msg
        else:
            err_msg = "KOSDAQ: Timeout"
            idx_data["error"] = idx_data["error"] + " | " + err_msg if idx_data["error"] else err_msg
            
        for f in not_done: f.cancel()

    # KeyError 방지: "Close" 컬럼 검증 추가
    kp_ok = kp is not None and "Close" in kp.columns and len(kp) >= 21
    kd_ok = kd is not None and "Close" in kd.columns and len(kd) >= 21

    if kp_ok:
        idx_data["kp_today"], idx_data["kp_prev"] = float(kp['Close'].iloc[-1]), float(kp['Close'].iloc[-2])
        idx_data["kp_1d"] = round(((idx_data["kp_today"] / idx_data["kp_prev"]) - 1) * 100, 2)
        idx_data["kp_5d"] = round(((idx_data["kp_today"] / kp['Close'].iloc[-6]) - 1) * 100, 2)
        idx_data["kp_20d"] = round(((idx_data["kp_today"] / kp['Close'].iloc[-21]) - 1) * 100, 2)
        
    if kd_ok:
        idx_data["kd_today"], idx_data["kd_prev"] = float(kd['Close'].iloc[-1]), float(kd['Close'].iloc[-2])
        idx_data["kd_1d"] = round(((idx_data["kd_today"] / idx_data["kd_prev"]) - 1) * 100, 2)
        idx_data["kd_5d"] = round(((idx_data["kd_today"] / kd['Close'].iloc[-6]) - 1) * 100, 2)
        idx_data["kd_20d"] = round(((idx_data["kd_today"] / kd['Close'].iloc[-21]) - 1) * 100, 2)
        
    idx_data["success"] = kp_ok or kd_ok
    idx_data["partial"] = kp_ok != kd_ok
    idx_data["elapsed"] = round(time.time() - st_idx, 3)
    
    if idx_data["partial"]: logging.warning(f"[Market] Partial Index Loaded (KOSPI={kp_ok}, KOSDAQ={kd_ok})")
    if not idx_data["success"] and not idx_data["error"]: idx_data["error"] = "데이터 행 부족 또는 컬럼 이상"
    
    if idx_data["success"]:
        with _cache_lock:
            _index_cache = {"timestamp": time.time(), "data": copy.deepcopy(idx_data), "market_status": current_market_status}
            
    return idx_data

def _fetch_api():
    st = time.time()
    res = {"success": False, "source": "NAVER API", "error": "", "data": {}, "elapsed": 0.0}
    try:
        session = _get_session()
        r_kp = session.get("https://m.stock.naver.com/api/index/KOSPI/price", timeout=(3, 7))
        r_kd = session.get("https://m.stock.naver.com/api/index/KOSDAQ/price", timeout=(3, 7))
        
        r_kp.raise_for_status(); r_kd.raise_for_status()
        
        kp_j, kd_j = r_kp.json(), r_kd.json()
        d_kp, d_kd = (kp_j[0] if isinstance(kp_j, list) else kp_j), (kd_j[0] if isinstance(kd_j, list) else kd_j)
        
        kp_rf, kd_rf = d_kp.get("riseFall", {}), d_kd.get("riseFall", {})
        kp_up, kp_down, kp_same = int(kp_rf.get("rise",0)), int(kp_rf.get("fall",0)), int(kp_rf.get("same",0))
        kd_up, kd_down, kd_same = int(kd_rf.get("rise",0)), int(kd_rf.get("fall",0)), int(kd_rf.get("same",0))
        
        if (kp_up + kp_down + kp_same) >= BREADTH_THRESHOLD and (kd_up + kd_down + kd_same) >= BREADTH_THRESHOLD:
            res["success"] = True
            res["data"] = {"kp_up": kp_up, "kp_down": kp_down, "kp_same": kp_same, "kd_up": kd_up, "kd_down": kd_down, "kd_same": kd_same}
        else: res["error"] = "Insufficient Data"
    except Exception as e: res["error"] = f"Err: {str(e)[:70]}"
    res["elapsed"] = round(time.time() - st, 3)
    return res

def _parse_dom_market(code):
    session = _get_session()
    r = session.get(f"https://finance.naver.com/sise/sise_index.naver?code={code}", timeout=(3, 7))
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    dl = soup.select_one("dl.lst_kos_info")
    up, down, same = 0, 0, 0
    if dl:
        for dt in dl.select("dt"):
            txt, dd = dt.get_text().strip(), dt.find_next_sibling("dd")
            if not dd: continue
            val_match = re.search(r'[\d,]+', dd.get_text())
            val = int(val_match.group().replace(",", "")) if val_match else 0
            if "상승" in txt: up = val
            elif "하락" in txt: down = val
            elif "보합" in txt: same = val
    return up, down, same

def _fetch_dom():
    st = time.time()
    res = {"success": False, "source": "NAVER DOM", "error": "", "data": {}, "elapsed": 0.0}
    try:
        kp_up, kp_down, kp_same = _parse_dom_market("KOSPI")
        kd_up, kd_down, kd_same = _parse_dom_market("KOSDAQ")
        
        if (kp_up + kp_down + kp_same) >= BREADTH_THRESHOLD and (kd_up + kd_down + kd_same) >= BREADTH_THRESHOLD:
            res["success"] = True
            res["data"] = {"kp_up": kp_up, "kp_down": kp_down, "kp_same": kp_same, "kd_up": kd_up, "kd_down": kd_down, "kd_same": kd_same}
        else: res["error"] = "Insufficient Data"
    except Exception as e: res["error"] = f"Err: {str(e)[:70]}"
    res["elapsed"] = round(time.time() - st, 3)
    return res

def _fetch_fdr():
    st = time.time()
    res = {"success": False, "source": "한국거래소(FDR)", "error": "", "data": {}, "elapsed": 0.0}
    try:
        krx = fdr.StockListing('KRX')
        target_col = None
        for col in ["ChangesRatio", "ChgRate", "ChangeRatio", "FluctuationRate", "Rate", "Change"]:
            if col in krx.columns:
                target_col = col; break
        if not target_col: raise RuntimeError("변동률 컬럼 탐색 실패")
        
        krx = krx.rename(columns={target_col: "ChangesRatio"})
        
        kpi_df, kdq_df, kon_df = krx[krx['Market'] == 'KOSPI'], krx[krx['Market'] == 'KOSDAQ'], krx[krx['Market'] == 'KONEX']
        fdr_kp_total, fdr_kd_total = len(kpi_df), len(kdq_df)
        
        kp_up, kp_down, kp_same = len(kpi_df[kpi_df['ChangesRatio']>0]), len(kpi_df[kpi_df['ChangesRatio']<0]), len(kpi_df[kpi_df['ChangesRatio']==0])
        kd_up, kd_down, kd_same = len(kdq_df[kdq_df['ChangesRatio']>0]), len(kdq_df[kdq_df['ChangesRatio']<0]), len(kdq_df[kdq_df['ChangesRatio']==0])
        kp_sum, kd_sum = kp_up + kp_down + kp_same, kd_up + kd_down + kd_same
        
        if abs(kp_sum - fdr_kp_total) <= 2 and abs(kd_sum - fdr_kd_total) <= 2 and kp_sum >= (fdr_kp_total * 0.75) and kd_sum >= (fdr_kd_total * 0.75):
            res["success"] = True
            res["data"] = {
                "fdr_total": len(krx), "fdr_kp_total": fdr_kp_total, "fdr_kd_total": fdr_kd_total, "fdr_konex_total": len(kon_df),
                "fdr_others": len(krx) - (fdr_kp_total + fdr_kd_total + len(kon_df)),
                "kp_up": kp_up, "kp_down": kp_down, "kp_same": kp_same, "kd_up": kd_up, "kd_down": kd_down, "kd_same": kd_same
            }
        else: res["error"] = f"Mismatch (KP:{kp_sum}/{fdr_kp_total}, KD:{kd_sum}/{fdr_kd_total})"
    except Exception as e: res["error"] = str(e)[:80]
    res["elapsed"] = round(time.time() - st, 3)
    return res

def _get_src_key(source_str):
    if "API" in source_str: return "API"
    if "DOM" in source_str: return "DOM"
    return "FDR"

def load_breadth():
    global _breadth_cache, _health_history
    start_time = time.time()
    cache_ttl = _get_dynamic_ttl()
    current_market_status = _is_market_open()
    
    b_data = {
        "success": False, "source": "NONE", "kp_up": 0, "kp_down": 0, "kp_same": 0, "kd_up": 0, "kd_down": 0, "kd_same": 0,
        "fdr_total": 0, "fdr_kp_total": 0, "fdr_kd_total": 0, "fdr_konex_total": 0, "fdr_others": 0,
        "diag": {
            "API": {"status": "FAIL", "error": "", "elapsed": 0}, "DOM": {"status": "FAIL", "error": "", "elapsed": 0},
            "FDR": {"status": "FAIL", "error": "", "elapsed": 0}, "YAHOO": {"status": "OFF", "error": "", "elapsed": 0},
            "CACHE": {"status": "NO", "age": 0, "error": ""}
        },
        "elapsed": 0.0
    }
    
    with _cache_lock:
        if _breadth_cache["data"] is not None and (start_time - _breadth_cache["timestamp"] < cache_ttl) and (_breadth_cache["market_status"] == current_market_status):
            cached = copy.deepcopy(_breadth_cache["data"])
            cached["success"] = True
            for k in ["API", "DOM", "FDR", "YAHOO"]:
                cached["diag"][k] = {"status": "SKIP", "error": "", "elapsed": 0}
            age = int(start_time - _breadth_cache['timestamp'])
            cached["diag"]["CACHE"].update({"status": "USED", "age": age, "error": ""})
            cached["elapsed"] = round(time.time() - start_time, 3)
            logging.debug(f"[Market] Source=CACHE | Age={age}s")
            return cached

    priority_map = {"한국거래소(FDR)": 100, "NAVER API": 95, "NAVER DOM": 90}
    valid_results = []
    
    task_map = {}
    if _check_cb("API"): task_map[_fetch_api] = "API"
    else: b_data["diag"]["API"]["status"] = "BLOCKED"
    
    if _check_cb("DOM"): task_map[_fetch_dom] = "DOM"
    else: b_data["diag"]["DOM"]["status"] = "BLOCKED"
        
    if _check_cb("FDR"): task_map[_fetch_fdr] = "FDR"
    else: b_data["diag"]["FDR"]["status"] = "BLOCKED"

    executor = ThreadPoolExecutor(max_workers=3)
    try:
        futures = {executor.submit(task): name for task, name in task_map.items()}
        
        if futures:
            done, not_done = wait(futures, return_when=FIRST_COMPLETED)
            
            highest_found = False
            for f in done:
                try:
                    res = f.result()
                except Exception as e:
                    src_key = futures[f]
                    b_data["diag"][src_key]["error"] = f"Thread Exception: {str(e)[:50]}"
                    continue
                
                src_key = _get_src_key(res["source"])
                b_data["diag"][src_key]["elapsed"] = res.get("elapsed", 0)
                _update_cb(src_key, res["success"])
                
                if res["success"]:
                    valid_results.append(res)
                    if res["source"] == "한국거래소(FDR)": highest_found = True
                else:
                    b_data["diag"][src_key]["error"] = res["error"]
            
            # FDR의 무거운 I/O를 배려하여 최대 5.0초로 Grace 대폭 상향
            if not highest_found and not_done:
                elapsed_so_far = time.time() - start_time
                remaining_grace = max(0.5, 5.0 - elapsed_so_far)
                
                done2, not_done2 = wait(not_done, timeout=remaining_grace, return_when=ALL_COMPLETED)
                for f in done2:
                    try:
                        res = f.result()
                        src_key = _get_src_key(res["source"])
                        b_data["diag"][src_key]["elapsed"] = res.get("elapsed", 0)
                        _update_cb(src_key, res["success"])
                        if res["success"]: valid_results.append(res)
                        else: b_data["diag"][src_key]["error"] = res["error"]
                    except Exception as e:
                        src_key = futures[f]
                        b_data["diag"][src_key]["error"] = f"Thread Exception: {str(e)[:50]}"
                        continue
                
                for f in not_done2: 
                    is_cancelled = f.cancel()
                    src_key = futures[f]
                    if b_data["diag"][src_key]["status"] == "FAIL" and not b_data["diag"][src_key]["error"]:
                        b_data["diag"][src_key]["error"] = f"Grace Exceeded ({'Cancelled' if is_cancelled else 'Running'})"
            else:
                for f in not_done:
                    is_cancelled = f.cancel()
                    src_key = futures[f]
                    if b_data["diag"][src_key]["status"] == "FAIL" and not b_data["diag"][src_key]["error"]:
                        b_data["diag"][src_key]["error"] = f"Fast Exit ({'Cancelled' if is_cancelled else 'Running'})"
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    if valid_results:
        valid_results.sort(key=lambda x: priority_map.get(x["source"], 0), reverse=True)
        winner_res = valid_results[0]
        
        b_data.update(winner_res["data"])
        b_data["success"], b_data["source"] = True, winner_res["source"]
        
        winner_key = _get_src_key(winner_res["source"])
        for k in ["API", "DOM", "FDR"]:
            if k == winner_key: b_data["diag"][k]["status"] = "PASS"
            elif b_data["diag"][k]["status"] == "FAIL" and b_data["diag"][k]["error"] == "":
                b_data["diag"][k]["status"] = "SKIP"
    else:
        try:
            yf_st = time.time()
            resp = _get_session().get("https://query1.finance.yahoo.com/v8/finance/chart/^KS11", timeout=(3, 3))
            resp.raise_for_status()
            b_data["diag"]["YAHOO"]["status"] = "PASS"
            b_data["diag"]["YAHOO"]["elapsed"] = round(time.time() - yf_st, 3)
            logging.debug("[Market] YAHOO Connectivity check PASS")
        except Exception as e:
            b_data["diag"]["YAHOO"]["error"] = f"Conn Err: {str(e)[:50]}"
            
        logging.error("[Market] ALL SOURCES FAILED OR BLOCKED")

    b_data["kp_actual_sum"] = b_data.get("kp_up",0) + b_data.get("kp_down",0) + b_data.get("kp_same",0)
    b_data["kd_actual_sum"] = b_data.get("kd_up",0) + b_data.get("kd_down",0) + b_data.get("kd_same",0)
    b_data["elapsed"] = round(time.time() - start_time, 3)
    
    with _cache_lock:
        _health_history.append(b_data["source"] if b_data["success"] else "FAIL")
        
        if b_data["success"]:
            cache_data = copy.deepcopy(b_data)
            cache_data["diag"]["CACHE"]["age"] = 0
            _breadth_cache = {"timestamp": time.time(), "data": cache_data, "market_status": current_market_status}
        
        runs = list(_health_history)
        if len(runs) > 0 and (len(runs) % 10 == 0 or not b_data["success"]):
            stats_10 = {k: round(v/min(10, len(runs))*100, 1) for k, v in Counter(runs[-10:]).items()}
            stats_30 = {k: round(v/min(30, len(runs))*100, 1) for k, v in Counter(runs[-30:]).items()}
            stats_100 = {k: round(v/len(runs)*100, 1) for k, v in Counter(runs).items()}
            logging.info(f"[Market Health] 10MA: {stats_10} | 30MA: {stats_30} | 100MA: {stats_100}")

    diag_log = " | ".join([f"{k}:{v['status']}({v.get('elapsed',0)}s)" for k, v in b_data['diag'].items() if k != "CACHE"])
    logging.debug(f"[Market] Diagnostics -> {diag_log}")
    
    if b_data["success"]:
        logging.info(f"[Market] Selected Source={b_data['source']} | Elapsed={b_data['elapsed']}s")
    
    return b_data

def calculate_quality(idx_data, b_data):
    q = {"idx": 0, "brd": 0, "kp": 0, "kd": 0, "src": 0, "score": 0, "reasons": []}
    
    if idx_data["success"]:
        if idx_data.get("partial"):
            q["idx"] = 5; q["reasons"].append("Index Partial Success")
        else: q["idx"] = 10
    else: q["reasons"].append("Index Fail")
        
    if b_data["success"]: q["brd"] = 30
    else: q["reasons"].append("Breadth Data Fail")
    
    if b_data["source"] == "한국거래소(FDR)":
        if abs(b_data["kp_actual_sum"] - b_data.get("fdr_kp_total", 0)) <= 2 and b_data["kp_actual_sum"] >= (b_data.get("fdr_kp_total", 0) * 0.75): q["kp"] = 20
        else: q["reasons"].append("KOSPI Mismatch")
        if abs(b_data["kd_actual_sum"] - b_data.get("fdr_kd_total", 0)) <= 2 and b_data["kd_actual_sum"] >= (b_data.get("fdr_kd_total", 0) * 0.75): q["kd"] = 20
        else: q["reasons"].append("KOSDAQ Mismatch")
    else:
        if b_data["kp_actual_sum"] >= BREADTH_THRESHOLD: q["kp"] = 20
        else: q["reasons"].append("KOSPI Empty/Low")
        if b_data["kd_actual_sum"] >= BREADTH_THRESHOLD: q["kd"] = 20
        else: q["reasons"].append("KOSDAQ Empty/Low")
        
    if b_data["source"] == "NAVER API": q["src"] = 20
    elif b_data["source"] == "한국거래소(FDR)": q["src"] = 20
    elif b_data["source"] == "NAVER DOM": q["src"] = 15
    elif b_data["source"] == "CACHE":
        age = b_data["diag"].get("CACHE", {}).get("age", 0)
        if age <= 60: q["src"] = 10
        elif age <= 180: q["src"] = 8
        elif age <= 300: q["src"] = 6
        else: q["src"] = 4
        if not q["reasons"]: q["reasons"].append(f"Using Cache ({age}s)")
            
    q["score"] = sum([q["idx"], q["brd"], q["kp"], q["kd"], q["src"]])
    
    if q["score"] >= 90: state = "NORMAL"
    elif q["score"] >= 80: state = "CAUTION"
    else: state = "INVALID"
    
    return q["score"], state, "; ".join(q["reasons"]) if q["reasons"] else "All Clear"

def get_market_context():
    st = time.time()
    idx = load_index()
    b = load_breadth()
    score, state, reason = calculate_quality(idx, b)
    val_pass = (state in ["NORMAL", "CAUTION"])
    
    log_level = logging.INFO if val_pass else logging.WARNING
    total_elapsed = round(time.time() - st, 3)
    logging.log(log_level, f"[Market Final] State={state} | Score={score} | TotalElapsed={total_elapsed}s | Reason={reason}")
    
    return {
        "state": state, "allow_scan": val_pass, "data_quality": score, "validation_pass": val_pass,
        "reason": reason, "breadth": b, "kospi_1d": idx["kp_1d"], "kosdaq_1d": idx["kd_1d"], "source": b["source"], "partial": idx.get("partial", False)
    }
