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
import copy 
from dataclasses import dataclass, field
from collections import deque, Counter
from typing import Dict, Any, List, Tuple, Callable, Optional 
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
    STATE_VERSION: str = "1.3.3"
    SAVE_INTERVAL_SEC: int = 600  

CONFIG = MarketConfig()

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
# 3. Centralized Runtime State
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
        self.bayesian_stats = {"API": {"alpha": 10.0, "beta": 1.0}, "DOM": {"alpha": 10.0, "beta": 1.0}, "FDR": {"alpha": 10.0, "beta": 1.0}, "YAHOO": {"alpha": 10.0, "beta": 1.0}}
        self.stale_tracker = {"API": {"data": None, "timestamp": 0, "elapsed": 0.0}, "DOM": {"data": None, "timestamp": 0, "elapsed": 0.0}, "FDR": {"data": None, "timestamp": 0, "elapsed": 0.0}}
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
                _logger.warning("State file hash mismatch! Starting fresh.", extra={'ctx': 'STATE'})
                return
            state = wrapper["payload"]
            if state.get("version") != CONFIG.STATE_VERSION: return
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
            _logger.info("Market health state restored.", extra={'ctx': 'STATE'})
        except Exception as e:
            _logger.warning("Failed to load state: %s", e, extra={'ctx': 'STATE'})

    def trigger_save(self, force=False):
        now = time.time()
        if not force and (now - self.last_save_time < CONFIG.SAVE_INTERVAL_SEC): return
        try:
            with self.lock:
                state_dict = {"version": CONFIG.STATE_VERSION, "created": now, "global_health_ema": self.global_health_ema, "source_health_ema": self.source_health_ema, "circuit_breakers": {k: v.__dict__ for k, v in self.cb.items()}, "bayesian_stats": self.bayesian_stats}
            payload_str = json.dumps(state_dict, sort_keys=True)
            wrapper = {"hash": hashlib.sha256(payload_str.encode('utf-8')).hexdigest(), "payload": state_dict}
            tmp_file = CONFIG.STATE_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(wrapper, f, indent=4); f.flush(); os.fsync(f.fileno())
            os.replace(tmp_file, CONFIG.STATE_FILE)
            self.last_save_time = now
        except Exception as e:
            _logger.warning("Failed to save state: %s", e, extra={'ctx': 'STATE'})

    def get_adaptive_timeout(self, src: str, default: float = 5.0) -> float:
        with self.lock: hist = list(self.latency_history[src])
        if len(hist) < 5: return default
        arr = np.array(hist)
        return min(12.0, max(3.0, np.median(arr) + (3.0 * np.median(np.abs(arr - np.median(arr))))))

STATE = MarketRuntimeState()
STATE.load_state()

# =========================================================
# 4. Executors & Session
# =========================================================
_thread_local = threading.local()
_old_sessions = deque()
_session_lock = threading.RLock()
_executor_lock = threading.RLock()
STRICT_TIMEOUT = Timeout(connect=CONFIG.NET.TIMEOUT_CONNECT, read=CONFIG.NET.TIMEOUT_READ)
_GLOBAL_ADAPTER = HTTPAdapter(pool_connections=CONFIG.NET.MAX_WORKERS, pool_maxsize=CONFIG.NET.MAX_WORKERS, max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504]))
_network_executor, _orchestrator_executor, _net_gen, _orch_gen = None, None, 0, 0

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
    _logger.exception("Submit failed: %s", last_err, extra={'ctx': 'EXEC'})
    raise RuntimeError("Executor failure")

def _get_session():
    now = time.time()
    local = _thread_local
    if not hasattr(local, "session_data") or (now - local.session_data["created"] > 3600):
        if hasattr(local, "session_data"):
            with _session_lock: _old_sessions.append((local.session_data["session"], now))
        with _session_lock:
            active = [(s, t) for s, t in _old_sessions if now - t <= 60]
            for s, t in _old_sessions:
                if now - t > 60: try: s.close() except: pass
            _old_sessions.clear(); _old_sessions.extend(active)
        s = requests.Session(); s.headers.update({'User-Agent': 'Mozilla/5.0'}); s.mount("https://", _GLOBAL_ADAPTER); s.mount("http://", _GLOBAL_ADAPTER)
        local.session_data = {"session": s, "created": now}
    return local.session_data["session"]

@atexit.register
def cleanup():
    STATE.trigger_save(force=True)
    _GLOBAL_ADAPTER.close()
    with _session_lock:
        for s, _ in _old_sessions: try: s.close() except: pass
    for v in getattr(_thread_local, "__dict__", {}).values():
        if isinstance(v, dict) and "session" in v: try: v["session"].close() except: pass
    if _network_executor: _network_executor.shutdown(wait=False, cancel_futures=True)
    if _orchestrator_executor: _orchestrator_executor.shutdown(wait=False, cancel_futures=True)

# =========================================================
# 5. Core Helpers
# =========================================================
def _get_time_context() -> Dict[str, Any]:
    kst = pytz.timezone("Asia/Seoul"); now = datetime.datetime.now(kst)
    if now.weekday() >= 5: return {"is_open": False, "ttl": CONFIG.CACHE.TTL_CLOSED, "ratio": 0.80}
    t = now.time()
    if datetime.time(9, 0) <= t < datetime.time(9, 5): return {"is_open": True, "ttl": CONFIG.CACHE.TTL_OPEN_EXTREME, "ratio": 0.70} 
    elif datetime.time(9, 5) <= t < datetime.time(9, 20): return {"is_open": True, "ttl": CONFIG.CACHE.TTL_OPEN_HIGH, "ratio": 0.75} 
    elif datetime.time(9, 20) <= t < datetime.time(14, 50): return {"is_open": True, "ttl": CONFIG.CACHE.TTL_OPEN_MID, "ratio": 0.75}
    elif datetime.time(14, 50) <= t <= datetime.time(15, 30): return {"is_open": True, "ttl": CONFIG.CACHE.TTL_OPEN_END, "ratio": 0.75} 
    return {"is_open": False, "ttl": CONFIG.CACHE.TTL_CLOSED, "ratio": 0.80}

def _validate_data(data: Dict[str, Any]) -> bool:
    for k, v in data.items():
        if isinstance(v, (int, float)):
            if math.isnan(v) or math.isinf(v) or v < 0: return False
            if k.startswith("kp_") and v > (CONFIG.QUAL.EXPECTED_KP_TOTAL + 50): return False
            if k.startswith("kd_") and v > (CONFIG.QUAL.EXPECTED_KD_TOTAL + 50): return False
    return True

def _copy_shallow_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    new_data = dict(data)
    if "diag" in new_data: new_data["diag"] = {k: dict(v) if isinstance(v, dict) else v for k, v in new_data["diag"].items()}
    return new_data

def _get_src_key(source_str: str) -> str:
    if "API" in source_str: return "API"
    if "DOM" in source_str: return "DOM"
    if "YAHOO" in source_str: return "YAHOO"
    return "FDR"

def _get_bayesian_reliability(src: str) -> float:
    with STATE.lock:
        bs = STATE.bayesian_stats.get(src, {"alpha": 10.0, "beta": 1.0})
        return bs["alpha"] / (bs["alpha"] + bs["beta"])

# =========================================================
# 6. CB & Health
# =========================================================
def _check_cb(source_key: str) -> bool:
    with STATE.lock:
        cb = STATE.cb[source_key]
        if cb.state == "OPEN":
            if time.time() >= cb.blocked_until: cb.state = "HALF_OPEN"; return True
            return False
        bs = STATE.bayesian_stats.get(source_key, {"alpha": 10.0, "beta": 1.0})
        if (bs["alpha"] / (bs["alpha"] + bs["beta"])) < 0.5 and STATE.source_health_ema.get(source_key, 100.0) < 70.0:
            cb.state = "OPEN"; cb.blocked_until = time.time() + CONFIG.CB.BASE_PENALTY
            STATE.trigger_save(force=True); return False
        return True

def _update_cb_and_health(source_key: str, success: bool, error_msg: str, elapsed: float):
    now = time.time()
    with STATE.lock:
        bs = STATE.bayesian_stats[source_key]
        bs["alpha"] = bs["alpha"] * CONFIG.EMA.BAYESIAN_DECAY + (1.0 if success else 0.0)
        bs["beta"] = bs["beta"] * CONFIG.EMA.BAYESIAN_DECAY + (0.0 if success else 1.0)
        if success: STATE.latency_history[source_key].append(elapsed)
        STATE.success_history[source_key].append(1 if success else 0)
        STATE.source_health_ema[source_key] = (STATE.source_health_ema.get(source_key, 100.0) * (1 - CONFIG.EMA.ALPHA_SOURCE)) + ((100.0 if success else 0.0) * CONFIG.EMA.ALPHA_SOURCE)
        cb = STATE.cb[source_key]
        if success:
            if cb.state == "HALF_OPEN" and cb.consecutive_successes >= CONFIG.CB.HALF_OPEN_SUCCESS_REQ and STATE.source_health_ema[source_key] > 85.0:
                cb.fails = 0; cb.state = "CLOSED"; cb.consecutive_successes = 0; STATE.trigger_save(force=True)
            else: cb.fails = max(0, cb.fails - 1) if (now - cb.last_fail_time > 1800 or STATE.source_health_ema[source_key] > 90.0) else cb.fails
            cb.blocked_until = 0
        else:
            cb.fails += 1; cb.last_fail_time = now; cb.consecutive_successes = 0
            if cb.state == "HALF_OPEN" or cb.fails >= getattr(CONFIG.CB, f"THRESHOLD_{source_key}", 5):
                cb.state = "OPEN"; cb.blocked_until = now + min(CONFIG.CB.BASE_PENALTY * (2 ** max(0, (cb.fails // 3) - 1)), CONFIG.CB.MAX_PENALTY)
                STATE.trigger_save(force=True)

# =========================================================
# 7. Fetchers (Parallelized)
# =========================================================
_fdr_listing_sem, _fdr_reader_sem, _yf_semaphore = threading.Semaphore(1), threading.Semaphore(1), threading.Semaphore(1)

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
    _update_cb_and_health(src_key, res["success"], res.get("error", ""), elapsed)
    return res, diag

def _parallel_fetch(task_map: Dict[str, Callable], ctx: Dict, global_timeout: float) -> Tuple[List[Dict], Dict[str, SourceDiag]]:
    futures_map = {_safe_submit(task, is_orchestrator=False, src_key=name, fn=task, ctx=ctx): name for name, task in task_map.items()}
    valid_results, diag_info = [], {k: SourceDiag(status="BLOCKED") for k in task_map.keys()}
    done, not_done = wait(futures_map.keys(), timeout=global_timeout, return_when=ALL_COMPLETED)
    for f in done:
        src_key = futures_map[f]
        if f.done():
            try:
                res, diag = f.result(timeout=0.1)
                diag_info[src_key] = diag
                if res["success"]: valid_results.append(res)
            except Exception as e: _logger.warning("Fetch Exception %s: %s", src_key, e, extra={'ctx': 'FETCH'})
    for f in not_done:
        src_key = futures_map[f]; f.cancel(); diag_info[src_key].error = "Zombie"
    return valid_results, diag_info

# =========================================================
# 8. Main Loaders
# =========================================================
def load_index() -> Dict:
    st_idx = time.time(); ctx = _get_time_context()
    with STATE.lock:
        if STATE.index_cache.data is not None and (st_idx - STATE.index_cache.timestamp < ctx["ttl"]) and (STATE.index_cache.time_context == ctx["is_open"]):
            return _copy_shallow_dict(STATE.index_cache.data)
    start_date = (datetime.datetime.now(pytz.timezone("Asia/Seoul")) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    valid_results, diag_info = _parallel_fetch({"KS11": lambda c: _fdr_data_reader_safe({"symbol": "KS11", "start_date": start_date}), "KQ11": lambda c: _fdr_data_reader_safe({"symbol": "KQ11", "start_date": start_date})}, ctx, CONFIG.NET.MAX_INDEX_WAIT)
    kp = next((r["data"] for r in valid_results if r["source"] == "KS11"), None)
    kd = next((r["data"] for r in valid_results if r["source"] == "KQ11"), None)
    
    yahoo_used, yahoo_ok = False, True
    def _fallback_yf(symbol):
        with _yf_semaphore:
            for _ in range(2):
                try: df = yf.download(symbol, period="3mo", progress=False, timeout=CONFIG.NET.YF_TIMEOUT); return df if df is not None and not df.empty else None
                except: time.sleep(0.5)
            return None
    if (kp is None or len(kp) < CONFIG.QUAL.INDEX_REQUIRED_DAYS) and _check_cb("YAHOO"): yahoo_used = True; kp = _fallback_yf("^KS11"); yahoo_ok = yahoo_ok and (kp is not None)
    if (kd is None or len(kd) < CONFIG.QUAL.INDEX_REQUIRED_DAYS) and _check_cb("YAHOO"): yahoo_used = True; kd = _fallback_yf("^KQ11"); yahoo_ok = yahoo_ok and (kd is not None)
    if yahoo_used: _update_cb_and_health("YAHOO", yahoo_ok, "" if yahoo_ok else "Fallback Failed", 0.0)
    idx_data = {"success": (kp is not None and kd is not None), "kp_1d": 0.0, "kd_1d": 0.0}
    if kp is not None and kd is not None:
        idx_data.update({"kp_1d": round((kp['Close'].iloc[-1]/kp['Close'].iloc[-2]-1)*100, 2), "kd_1d": round((kd['Close'].iloc[-1]/kd['Close'].iloc[-2]-1)*100, 2)})
    with STATE.lock: STATE.index_cache = CacheEntry(timestamp=time.time(), data=dict(idx_data), time_context=ctx["is_open"])
    return idx_data

def load_breadth() -> Dict:
    start_time = time.time(); ctx = _get_time_context()
    with STATE.lock:
        if len(STATE.breadth_cache_gen) > 0:
            c = STATE.breadth_cache_gen[0]
            if c["data"] is not None and (c["time_context"] == ctx["is_open"]):
                if int(time.time()-c["timestamp"]) < ctx["ttl"]: return {"success": True, **c["data"]}
    
    plan = {}
    if _check_cb("API"): plan["API"] = lambda c: _fetch_api_raw(c)
    if _check_cb("DOM"): plan["DOM"] = lambda c: _fetch_dom_raw(c)
    if _check_cb("FDR"): plan["FDR"] = lambda c: _fetch_fdr_raw(c)
    
    valid, _ = _parallel_fetch(plan, ctx, STATE.get_adaptive_timeout("FDR"))
    if not valid: return {"success": False, "source": "NONE"}
    
    # Consensus (Median)
    winner = max(valid, key=lambda x: x.get("final_score", 0))
    winner = copy.deepcopy(winner)
    
    with STATE.lock: STATE.health_history.append("SUCCESS")
    STATE.trigger_save()
    return {"success": True, **winner}

def calculate_quality(idx_data: Dict, b_data: Dict) -> Tuple[int, str, str]:
    q_score, reasons = 0, []
    if not idx_data.get("success"): q_score -= 30; reasons.append("CRITICAL: Index Fail (-30)")
    else: q_score += 10
    
    if b_data.get("success"): q_score += 30
    else: reasons.append("Breadth Fail")
    
    s_hlth, r_hlth = _score_health(b_data, b_data.get("source", "")); q_score += s_hlth; reasons.extend(r_hlth)
    
    state = "NORMAL" if q_score >= 90 else ("CAUTION" if q_score >= 80 else "INVALID")
    return q_score, state, "; ".join(set(reasons))

def _score_health(b_data: Dict, actual_src: str) -> Tuple[int, List[str]]:
    src_key = _get_src_key(actual_src)
    with STATE.lock:
        bayesian_rel = STATE.bayesian_stats[src_key]["alpha"] / (STATE.bayesian_stats[src_key]["alpha"] + STATE.bayesian_stats[src_key]["beta"])
        g_ema = STATE.global_health_ema
    score = int(20 * bayesian_rel)
    reasons = []
    if g_ema < 80.0: score -= int((80.0 - g_ema) / 2); reasons.append("Health Pen")
    return score, reasons

def get_market_context() -> Dict:
    f_idx = _safe_submit(load_index, is_orchestrator=True)
    f_brd = _safe_submit(load_breadth, is_orchestrator=True)
    done, _ = wait([f_idx, f_brd], timeout=20, return_when=ALL_COMPLETED)
    idx = f_idx.result(timeout=0.1) if f_idx in done else {"success": False}
    b = f_brd.result(timeout=0.1) if f_brd in done else {"success": False}
    score, state, reason = calculate_quality(idx, b)
    return {"state": state, "allow_scan": (state in ["NORMAL", "CAUTION"]), "data_quality": score, "reason": reason, "breadth": b}

if __name__ == "__main__":
    # Self-test logic
    print(get_market_context())
