import os
import sys
import time
import json
import math
import logging
import tempfile
import requests
from dataclasses import dataclass

import market_check
import market_report
import scanner
import decision_engine
import holding_analyzer
import report_formatter
import contracts
import database
import signal_tracker

@dataclass
class AppConfig:
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    TOTAL_EQUITY: float = 10_000_000

CONFIG = AppConfig()

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S', handlers=[logging.StreamHandler(sys.stdout)])
_logger = logging.getLogger(__name__)

TELEGRAM_MAX_LEN = 3900  
BUY_LEVELS = {"LEVEL 3", "LEVEL 2", "LEVEL 1"}
VALID_LEVELS = {"LEVEL 3", "LEVEL 2", "LEVEL 1", "WATCH A", "WATCH B", "WATCH C", "HOLD", "REDUCE", "EXIT", "GATED"}
VALID_MARKET_STATES = {"NORMAL", "CAUTION", "WEAK", "CRASH", "INVALID", "UNKNOWN"}

# [방어 P2] 명시적 Exit Code 규약 상수화
EXIT_SUCCESS = 0
EXIT_CORE_FAILURE = 1
EXIT_DELIVERY_FAILURE = 2
EXIT_DEGRADED_SUCCESS = 3
EXIT_DEGRADED_FAILURE = 4

# ==========================================
# 1. Telegram Subsystem (Smart Retry & Chunk Logging)
# ==========================================
def safe_retry_after(data: dict, default: int = 2) -> int:
    """[방어 P0-3] 429 응답 파싱 및 Job 마진(최대 30초) 상한선 설정으로 타임아웃 방어"""
    MAX_JOB_MARGIN = 30  
    try:
        value = data.get("parameters", {}).get("retry_after", default)
        value = int(value)
        return max(1, min(value, MAX_JOB_MARGIN))
    except Exception:
        return default

def send_telegram_blocks(blocks: list) -> bool:
    try:
        if type(blocks) is not list or not blocks:
            _logger.error("Telegram Delivery Error: blocks must be a non-empty list")
            return False
            
        for i, block in enumerate(blocks):
            if type(block) is not str or not block.strip():
                _logger.error(f"Telegram Delivery Error: Invalid report block at index {i}")
                return False
            if len(block) > TELEGRAM_MAX_LEN:
                _logger.error(f"Telegram Delivery Error: Block {i} exceeds max length ({len(block)} chars)")
                return False
                
        if not CONFIG.TELEGRAM_TOKEN:
            _logger.warning("Telegram token missing.")
            return False
            
        url = f"https://api.telegram.org/bot{CONFIG.TELEGRAM_TOKEN}/sendMessage"
        success_all = True
        
        chunks, current_chunk = [], ""
        for block in blocks:
            if len(current_chunk) + len(block) + 2 <= TELEGRAM_MAX_LEN:
                current_chunk += block + "\n\n"
            else:
                if current_chunk: chunks.append(current_chunk.strip())
                current_chunk = block + "\n\n"
        if current_chunk: chunks.append(current_chunk.strip())
        
        total_chunks = len(chunks)
        for idx, chunk in enumerate(chunks, 1):
            payload = {"chat_id": CONFIG.TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "HTML"}
            chunk_success = False
            
            for attempt in range(3):
                try:
                    res = requests.post(url, json=payload, timeout=10.0)
                    
                    if res.status_code == 429:
                        try:
                            body = res.json()
                            retry_after = safe_retry_after(body, 2)
                        except Exception:
                            retry_after = 2
                            
                        _logger.warning(f"Telegram rate limited (HTTP 429) on Chunk {idx}/{total_chunks}. retry_after={retry_after}s")
                        if attempt < 2:
                            time.sleep(retry_after)
                            continue
                        break
                    
                    if 400 <= res.status_code < 500 and res.status_code != 429:
                        _logger.error(f"Telegram Permanent Client Error on Chunk {idx}/{total_chunks}: {res.status_code} - {res.text}")
                        break 
                        
                    res.raise_for_status()
                    
                    data = res.json()
                    if type(data) is dict:
                        if data.get("ok") is True:
                            chunk_success = True
                            break
                        else:
                            error_code = data.get("error_code")
                            if type(error_code) is int:
                                if 400 <= error_code < 500 and error_code != 429:
                                    _logger.error(f"Telegram API Permanent Error (4xx) on Chunk {idx}/{total_chunks}: {data}")
                                    break
                                elif error_code == 429:
                                    retry_after = safe_retry_after(data, 2)
                                    _logger.warning(f"Telegram API rate limited (429) on Chunk {idx}/{total_chunks}. retry_after={retry_after}s")
                                    if attempt < 2:
                                        time.sleep(retry_after)
                                        continue
                                    break
                                else:
                                    _logger.warning(f"Telegram API transient error ({error_code}) on Chunk {idx}/{total_chunks}, retrying")
                                    if attempt < 2:
                                        time.sleep(2)
                                        continue
                                    break
                            else:
                                _logger.error(f"Telegram API Contract Violation on Chunk {idx}/{total_chunks}: {data}")
                                break
                    else:
                        _logger.error(f"Telegram API returned non-dict JSON on Chunk {idx}/{total_chunks}")
                except Exception as e:
                    _logger.error(f"Telegram network/retry failed on Chunk {idx}/{total_chunks} (attempt {attempt+1}/3): {e}")
                    if attempt < 2: time.sleep(2)
                    
            if not chunk_success:
                _logger.error(f"CRITICAL: Telegram Chunk {idx}/{total_chunks} delivery FAILED.")
                success_all = False
            else:
                _logger.info(f"Telegram Chunk {idx}/{total_chunks} delivered successfully.")
            
        return success_all
    except Exception as e:
        _logger.exception("Telegram delivery subsystem crashed: %s", e)
        return False

# ==========================================
# 2. Data Contract Validators
# ==========================================
def load_sys_state(filepath: str) -> tuple[bool, dict]:
    default_state = {}
    if not os.path.exists(filepath):
        _logger.warning(f"sys_state missing: {filepath}. 신규매수 차단 (Fail-Closed)")
        return False, default_state 
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if type(data) is not dict: return False, default_state
        if "strat_db" in data and type(data["strat_db"]) is not dict: return False, default_state
        return True, data
    except Exception as e:
        _logger.error(f"sys_state load failed: {e}")
        return False, default_state

def load_p_state(filepath: str) -> tuple[bool, dict]:
    default_fail = {"allow_new_buy": False, "reason": "Shield Activated"}
    if not os.path.exists(filepath):
        _logger.warning(f"p_state.json missing. 신규매수 차단 (Fail-Closed)")
        return False, default_fail 
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if type(data) is not dict: raise TypeError
            if "allow_new_buy" not in data: raise ValueError
            if type(data["allow_new_buy"]) is not bool: raise TypeError
            return True, data
    except Exception as e:
        _logger.error(f"p_state corrupted: {e}")
        return False, default_fail

def is_valid_holding_source(data) -> bool:
    if type(data) is not list: return False
    seen_codes = set()
    for h in data:
        if type(h) is not dict: return False
        if "code" not in h or "name" not in h or "entry_price" not in h: return False
        code, name = h["code"], h["name"]
        if type(code) is not str or not code.strip() or type(name) is not str or not name.strip(): return False
        if code in seen_codes: return False
        seen_codes.add(code)
        if type(h["entry_price"]) not in (int, float): return False
        ep = float(h["entry_price"])
        if not math.isfinite(ep) or ep <= 0: return False
    return True

def safe_load_holdings(filepath: str) -> tuple[str, list]:
    if not os.path.exists(filepath): return "MISSING", []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if is_valid_holding_source(data): return "VALID", data
        _logger.error("Holdings Source Contract Violation")
        return "CORRUPTED", []
    except Exception as e:
        _logger.error(f"Holdings load failed: {e}")
        return "CORRUPTED", []

def is_valid_holdings_evaluation(holdings: list) -> bool:
    if type(holdings) is not list: return False
    valid_actions = {"HOLD", "EXIT", "DATA_MISSING", "REDUCE"}
    for h in holdings:
        if type(h) is not dict: return False
        if "code" not in h or "name" not in h or "action" not in h: return False
        code, name, action = h["code"], h["name"], h["action"]
        if type(code) is not str or not code.strip() or type(name) is not str or not name.strip(): return False
        if action not in valid_actions: return False
        
        if action == "DATA_MISSING":
            if "data_status" not in h: return False
            ds = h["data_status"]
            if type(ds) is not str or not ds.strip(): return False
            continue
            
        req_keys = {"entry_price", "current_price", "highest_price", "return_rate"}
        if not req_keys.issubset(h.keys()): return False
        for k in req_keys:
            if type(h[k]) not in (int, float) or not math.isfinite(float(h[k])): return False
            
        ep, cp, hp, rtn = float(h["entry_price"]), float(h["current_price"]), float(h["highest_price"]), float(h["return_rate"])
        if ep <= 0: return False
        if hp < ep * 0.999 or hp < cp * 0.999: return False
        if not math.isclose(rtn, (cp / ep - 1) * 100, abs_tol=0.1): return False
    return True

def validate_and_normalize_market_context(ctx: dict) -> dict:
    if type(ctx) is not dict: raise TypeError("market_ctx must be dict")
    req_keys = {"state", "allow_scan", "score", "kospi_1d", "kosdaq_1d", "advance_ratio"}
    if not req_keys.issubset(ctx.keys()): raise ValueError("Market Context missing keys")
    if type(ctx["state"]) is not str or ctx["state"] not in VALID_MARKET_STATES: raise ValueError("Invalid market state")
    if type(ctx["allow_scan"]) is not bool: raise TypeError("allow_scan must be bool")
    
    for field in ["score", "kospi_1d", "kosdaq_1d", "advance_ratio"]:
        if type(ctx[field]) not in (int, float): raise TypeError(f"{field} must be numeric")
        val = float(ctx[field])
        if not math.isfinite(val): raise ValueError(f"{field} is not finite")
        ctx[field] = val
    return ctx

def is_valid_scanner_result(features_list) -> bool:
    if type(features_list) is not list: return False
    for f in features_list:
        try:
            code = getattr(f, "code")
            if type(code) is not str or not code.strip(): return False
            price, chg = float(getattr(f, "price")), float(getattr(f, "chg"))
            if not math.isfinite(price) or price <= 0 or not math.isfinite(chg): return False
            
            struc, vty = getattr(f, "struc"), getattr(f, "vty")
            dist_ma20, return_var_20d = getattr(struc, "dist_ma20"), getattr(vty, "return_var_20d")
            if type(dist_ma20) not in (int, float) or not math.isfinite(float(dist_ma20)): return False
            if type(return_var_20d) not in (int, float) or not math.isfinite(float(return_var_20d)) or float(return_var_20d) < 0: return False
        except Exception: return False
    return True

def safe_nonnegative_int(value) -> int:
    if type(value) is int and value >= 0: return value
    raise TypeError(f"Value is not a non-negative int")

def is_valid_trade_plan(plan: dict) -> bool:
    try:
        if type(plan) is not dict or "sizing" not in plan: return False
        sizing = plan["sizing"]
        if type(sizing) is not dict or "ev" not in sizing: return False

        req_keys = {"entry", "stop_loss", "target1", "target2", "rr1", "rr2"}
        if not req_keys.issubset(plan.keys()): return False
        for k in req_keys:
            if type(plan[k]) not in (int, float): return False
        if type(sizing["ev"]) not in (int, float): return False

        entry, stop = float(plan["entry"]), float(plan["stop_loss"])
        t1, t2 = float(plan["target1"]), float(plan["target2"])
        rr1, rr2 = float(plan["rr1"]), float(plan["rr2"])
        ev = float(sizing["ev"])

        values = [entry, stop, t1, t2, rr1, rr2, ev]
        if not all(math.isfinite(v) for v in values): return False
        if not (entry > 0 and 0 < stop < entry and t1 > entry and t2 >= t1 and rr1 > 0 and rr2 >= rr1): return False
            
        risk = entry - stop
        if risk <= 0: return False 

        if not math.isclose(rr1, (t1 - entry) / risk, rel_tol=0.05, abs_tol=0.02): return False
        if not math.isclose(rr2, (t2 - entry) / risk, rel_tol=0.05, abs_tol=0.02): return False
        return True
    except (Exception): return False

def is_valid_candidate(candidate: dict) -> bool:
    if type(candidate) is not dict: return False
    required = {"code", "name", "price", "chg", "decision", "plan", "strategies"}
    if not required.issubset(candidate.keys()): return False
    
    code, name = candidate["code"], candidate["name"]
    if type(code) is not str or not code.strip() or type(name) is not str or not name.strip(): return False
    
    if type(candidate["price"]) not in (int, float) or type(candidate["chg"]) not in (int, float): return False
    price, chg = float(candidate["price"]), float(candidate["chg"])
    if not math.isfinite(price) or price <= 0 or not math.isfinite(chg): return False
    
    strats = candidate["strategies"]
    if type(strats) is not list or not all(type(s) is str and s.strip() for s in strats): return False

    decision, plan = candidate["decision"], candidate["plan"]
    if type(decision) is not dict or type(plan) is not dict: return False
    
    dec_req = {"level", "final_score", "bayesian_win_rate"}
    if not dec_req.issubset(decision.keys()): return False
    if decision["level"] not in BUY_LEVELS: return False
    
    for k in ["final_score", "bayesian_win_rate"]:
        if type(decision[k]) not in (int, float) or not math.isfinite(float(decision[k])): return False
    if not (0 <= float(decision["bayesian_win_rate"]) <= 1): return False
    
    return is_valid_trade_plan(plan)

def validate_report_blocks(blocks: list) -> bool:
    if type(blocks) is not list or not blocks: return False
    for i, block in enumerate(blocks):
        if type(block) is not str or not block.strip(): return False
        if len(block) > TELEGRAM_MAX_LEN: return False
    return True

# ==========================================
# 3. 메인 파이프라인 (The Global State Machine)
# ==========================================
def _extract_feature_codes(features_list) -> set[str]:
    """Scanner 결과에서 식별 가능한 종목 코드만 추출한다."""
    codes = set()
    for feature in features_list if isinstance(features_list, list) else []:
        code = getattr(feature, "code", None)
        if isinstance(code, str) and code.strip():
            codes.add(code.strip())
    return codes


def _extract_candidate_codes(candidates) -> set[str]:
    """후속 단계 후보에서 식별 가능한 종목 코드만 추출한다."""
    codes = set()
    for candidate in candidates if isinstance(candidates, list) else []:
        if isinstance(candidate, dict):
            code = candidate.get("code")
            if isinstance(code, str) and code.strip():
                codes.add(code.strip())
    return codes


def _validate_code_set(value, field_name: str) -> set[str]:
    """Cross-file 반환 계약: 명시적인 set[str]만 허용한다."""
    if not isinstance(value, set):
        raise TypeError(f"{field_name} must be set[str]")
    normalized = set()
    for code in value:
        if not isinstance(code, str) or not code.strip():
            raise TypeError(f"{field_name} contains invalid code")
        normalized.add(code.strip())
    return normalized


def _build_coverage_map(
    active_tracked_codes: set[str],
    scanned_codes: set[str],
    engine_evaluated_codes: set[str],
    consumer_evaluated_codes: set[str],
) -> dict[str, str]:
    """DB Active -> Scanner -> Engine -> Consumer의 단계별 lineage를 보존한다."""
    coverage_map = {}
    for code in sorted(active_tracked_codes):
        if code not in scanned_codes:
            coverage_map[code] = "SCANNER_MISSING"
        elif code not in engine_evaluated_codes:
            coverage_map[code] = "ENGINE_MISSING"
        elif code not in consumer_evaluated_codes:
            coverage_map[code] = "CONSUMER_MISSING"
        else:
            coverage_map[code] = "COVERED"
    return coverage_map


def run_pipeline():
    _logger.info("=== V9 Final Assembly Pipeline Started ===")

    market_success = cache_success = False
    holdings_eval_success = holdings_persistence_success = False
    scanner_success = engine_success = render_success = False
    tracker_success = False
    sys_state_success = p_state_success = False

    engine_status = "NOT_RUN"
    engine_skip_reason = ""
    decision_results = {}
    market_ctx = {}
    gate_open = False

    # =============================================================
    # [T0] Active Lineage Snapshot
    # =============================================================
    # 이 스냅샷은 이번 실행에서 기존 활성 신호의 생존권을 판단하는
    # 단일 기준점이다. 읽기 실패를 빈 집합으로 위장하지 않는다.
    try:
        active_db_signals = database.get_active_signals()
        if not isinstance(active_db_signals, dict):
            raise TypeError("database.get_active_signals() must return dict")

        active_tracked_codes = set()
        for signal_id, row in active_db_signals.items():
            if not isinstance(row, dict):
                raise TypeError(f"active_db_signals[{signal_id}] must be dict")
            code = row.get("code")
            if not isinstance(code, str) or not code.strip():
                raise TypeError(f"active_db_signals[{signal_id}] has invalid code")
            active_tracked_codes.add(code.strip())
    except Exception as e:
        _logger.critical("CORE FAILURE: Active lineage snapshot unavailable: %s", e, exc_info=True)
        sys.exit(EXIT_CORE_FAILURE)

    # =============================================================
    # [A] Market
    # =============================================================
    try:
        raw_ctx = market_check.get_market_context()
        market_ctx = validate_and_normalize_market_context(raw_ctx)
        gate_open = market_ctx["allow_scan"]
        market_success = True
    except Exception as e:
        _logger.exception("Market Contract Violation: %s", e)

    # =============================================================
    # [B] Price Cache
    # =============================================================
    price_cache = {}
    if market_success:
        try:
            price_cache = scanner.build_price_cache()
            if type(price_cache) is not dict:
                raise TypeError("price_cache must be dict")
            if not price_cache:
                raise ValueError("Price cache empty")
            cache_success = True
        except Exception as e:
            _logger.exception("Price Cache Contract Violation: %s", e)

    # =============================================================
    # [C] Holdings
    # =============================================================
    hold_status, holdings_data = safe_load_holdings("holdings.json")
    holding_evals = []

    if hold_status == "VALID" and cache_success:
        try:
            raw_evals = holding_analyzer.evaluate_holdings(holdings_data, price_cache)
            if is_valid_holdings_evaluation(raw_evals):
                holding_evals = raw_evals
                holdings_eval_success = True
            else:
                _logger.error("Holdings Eval Contract Violation")
        except Exception as e:
            _logger.exception("Holdings evaluation failed: %s", e)
    elif hold_status == "MISSING":
        _logger.error("Holdings file missing: account state UNKNOWN. 신규매수 차단.")
    elif hold_status == "CORRUPTED":
        _logger.error("Holdings file corrupted. 신규매수 차단.")

    if holdings_eval_success:
        temp_name = ""
        dir_name = os.path.dirname(os.path.abspath("holdings_eval.json")) or "."
        try:
            with tempfile.NamedTemporaryFile(
                "w", delete=False, dir=dir_name, encoding="utf-8"
            ) as f:
                json.dump(holding_evals, f, ensure_ascii=False, indent=4)
                f.flush()
                os.fsync(f.fileno())
                temp_name = f.name

            os.replace(temp_name, "holdings_eval.json")

            dir_fd = os.open(dir_name, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)

            holdings_persistence_success = True
        except Exception as e:
            _logger.exception("holdings_eval.json persistence failed: %s", e)
            if temp_name and os.path.exists(temp_name):
                try:
                    os.remove(temp_name)
                except OSError:
                    pass

    # =============================================================
    # [D] Scanner + 1차 Coverage
    # =============================================================
    features_list = []
    scanned_codes = set()
    scanner_telemetry = {"is_ran": False}

    if cache_success:
        try:
            # Cross-file 계약: Scanner는 active_tracked_codes를 반드시 받아
            # 활성 신호가 일반 랭킹에서 탈락하지 않도록 평가를 강제한다.
            raw_features = scanner.run_scanner(
                market_ctx,
                price_cache,
                active_tracked_codes=active_tracked_codes,
            )

            scanner_valid, scanner_reason = contracts.validate_scanner_result(raw_features)
            if not scanner_valid:
                raise TypeError(f"Scanner Result Contract Violation: {scanner_reason}")

            features_list = raw_features
            scanned_codes = _extract_feature_codes(features_list)

            # 기존 Scanner telemetry invariant는 그대로 유지한다.
            raw_rejects = market_ctx.get("scanner_rejects", {})
            if type(raw_rejects) is not dict:
                raise TypeError("scanner_rejects must be dict")

            required_telemetry = {"PREFILTER_DROP", "FETCH_FAIL", "PASS"}
            if not required_telemetry.issubset(raw_rejects.keys()):
                raise ValueError("Missing scanner telemetry keys")

            total_u = len(price_cache)
            pre_drop = safe_nonnegative_int(raw_rejects["PREFILTER_DROP"])
            fetch_fail = safe_nonnegative_int(raw_rejects["FETCH_FAIL"])
            feature_pass = safe_nonnegative_int(raw_rejects["PASS"])

            if pre_drop > total_u:
                raise ValueError("Invariant Violation: pre_drop")
            pre_pass = total_u - pre_drop
            if fetch_fail > pre_pass:
                raise ValueError("Invariant Violation: fetch_fail")
            if feature_pass > pre_pass - fetch_fail:
                raise ValueError("Invariant Violation: feature_pass")
            if len(features_list) != feature_pass:
                raise ValueError("Invariant Violation: feature_pass length mismatch")

            scanner_telemetry = {
                "is_ran": True,
                "total_universe": total_u,
                "prefilter_pass": pre_pass,
                "fetch_fail": fetch_fail,
                "feature_pass": feature_pass,
                "active_tracked": len(active_tracked_codes),
                "active_scanned": len(active_tracked_codes & scanned_codes),
            }
            scanner_success = True

            scanner_missing = active_tracked_codes - scanned_codes
            if scanner_missing:
                _logger.warning(
                    "SCAN COVERAGE INCOMPLETE: active codes missing from scanner: %s",
                    sorted(scanner_missing),
                )
        except Exception as e:
            _logger.exception("Scanner Contract Violation: %s", e)

    # =============================================================
    # [E] State + Decision Engine + 2차 Coverage
    # =============================================================
    sys_state_success, sys_state = load_sys_state("sys_state.json")
    p_state_success, p_state = load_p_state("p_state.json")

    engine_evaluated_codes = set()

    if not market_success:
        engine_status, engine_skip_reason = "NOT_RUN", "MARKET_CONTEXT_UNAVAILABLE"
    elif not cache_success:
        engine_status, engine_skip_reason = "SKIPPED", "PRICE_CACHE_UNAVAILABLE"
    elif hold_status in {"MISSING", "CORRUPTED"} or not holdings_eval_success or not holdings_persistence_success:
        engine_status, engine_skip_reason = "SKIPPED", "HOLDINGS_STATE_UNAVAILABLE"
    elif not sys_state_success:
        engine_status, engine_skip_reason = "SKIPPED", "SYS_STATE_UNAVAILABLE"
    elif not scanner_success:
        engine_status, engine_skip_reason = "NOT_RUN", "SCANNER_FAILURE"
    elif not p_state_success:
        engine_status, engine_skip_reason = "SKIPPED", "P_STATE_UNAVAILABLE"
    elif len(features_list) == 0:
        engine_status, engine_skip_reason = "SKIPPED", "NO_FEATURE_CANDIDATES"
    else:
        try:
            result = decision_engine.evaluate_candidates(
                features_list=features_list,
                market_context=market_ctx,
                holdings_data=holding_evals,
                p_state=p_state,
                total_equity=CONFIG.TOTAL_EQUITY,
                active_tracked_codes=active_tracked_codes,
            )

            if type(result) is not dict:
                raise TypeError("Decision Engine must return dict")

            required_keys = {
                "candidates",
                "buy_blocked",
                "block_reason",
                "level_counts",
                "engine_evaluated_codes",
            }
            if not required_keys.issubset(result.keys()):
                missing = required_keys - set(result.keys())
                raise ValueError(f"Decision Engine missing keys: {sorted(missing)}")

            if type(result["candidates"]) is not list:
                raise TypeError("Decision Engine candidates must be list")
            if type(result["buy_blocked"]) is not bool:
                raise TypeError("Decision Engine buy_blocked must be bool")
            if type(result["block_reason"]) is not str:
                raise TypeError("Decision Engine block_reason must be str")
            if type(result["level_counts"]) is not dict:
                raise TypeError("Decision Engine level_counts must be dict")

            for level, count in result["level_counts"].items():
                if level not in VALID_LEVELS:
                    raise ValueError(f"Invalid level key: {level}")
                if type(count) is not int or count < 0:
                    raise ValueError(f"Invalid level count: {level}={count}")

            engine_evaluated_codes = _validate_code_set(
                result["engine_evaluated_codes"],
                "engine_evaluated_codes",
            )

            # 반환된 명시적 lineage set은 features에서 단순히 재계산한 값이
            # 아니라 Engine 내부에서 실제 평가된 universe의 증적이어야 한다.
            if not scanned_codes.issuperset(engine_evaluated_codes):
                impossible = engine_evaluated_codes - scanned_codes
                raise ValueError(
                    f"Engine lineage violation: evaluated codes not scanned: {sorted(impossible)}"
                )

            decision_results = result
            engine_status = "SUCCESS"
            engine_success = True

            engine_missing = active_tracked_codes - engine_evaluated_codes
            if engine_missing:
                _logger.warning(
                    "ENGINE COVERAGE INCOMPLETE: active codes missing from engine evaluation: %s",
                    sorted(engine_missing),
                )
        except Exception as e:
            _logger.exception("Decision Engine Contract Violation: %s", e)
            engine_status, engine_skip_reason = "ERROR", "RUNTIME_EXCEPTION"

    # =============================================================
    # [F] Consumer Authority — contracts.py ONLY
    # =============================================================
    shadow_candidates = decision_results.get("candidates", []) if engine_success else []
    level_counts = decision_results.get("level_counts", {}) if engine_success else {}
    engine_buy_blocked = decision_results.get("buy_blocked", True) if engine_success else True

    validated_candidates = []
    consumer_evaluated_codes = set()
    actual_signals = []
    buy_contract_failures = 0
    non_buy_contract_failures = 0

    core_operational = (
        market_success
        and cache_success
        and holdings_eval_success
        and holdings_persistence_success
        and sys_state_success
        and p_state_success
        and scanner_success
        and engine_success
    )

    if core_operational:
        for candidate in shadow_candidates:
            if not isinstance(candidate, dict):
                _logger.error("Consumer input type violation: candidate is not dict")
                continue

            code = candidate.get("code")
            if not isinstance(code, str) or not code.strip():
                _logger.error("Consumer input type violation: candidate code missing")
                continue
            code = code.strip()

            # Producer의 is_valid는 읽지 않는다. Consumer가 유일한 심판이다.
            is_valid, reason = contracts.validate_candidate_contract(
                candidate,
                CONFIG.TOTAL_EQUITY,
                market_ctx["state"],
            )

            candidate["contract_status"] = "PASS" if is_valid else "FAIL"
            candidate["contract_reason"] = "CONTRACT_VALIDATED" if is_valid else reason
            validated_candidates.append(candidate)
            consumer_evaluated_codes.add(code)

            decision = candidate.get("decision", {})
            level = decision.get("level", "UNKNOWN") if isinstance(decision, dict) else "UNKNOWN"

            if is_valid:
                if level in BUY_LEVELS:
                    actual_signals.append(candidate)
            elif level in BUY_LEVELS:
                buy_contract_failures += 1
            else:
                non_buy_contract_failures += 1

    promotion_safe = True
    promotion_state = "NOT_EVALUATED"
    if core_operational:
        promotion_state = "EVALUATED"
        promotion_safe = buy_contract_failures == 0
        if not promotion_safe:
            _logger.critical(
                "Promotion Blocked: %d BUY candidate contract violations detected.",
                buy_contract_failures,
            )
            actual_signals = []

    # =============================================================
    # [G] Step-by-step Lineage Coverage + Tracker
    # =============================================================
    coverage_map = _build_coverage_map(
        active_tracked_codes,
        scanned_codes,
        engine_evaluated_codes,
        consumer_evaluated_codes,
    )

    pipeline_coverage_complete = all(
        status == "COVERED" for status in coverage_map.values()
    )

    coverage_counts = {
        "SCANNER_MISSING": sum(v == "SCANNER_MISSING" for v in coverage_map.values()),
        "ENGINE_MISSING": sum(v == "ENGINE_MISSING" for v in coverage_map.values()),
        "CONSUMER_MISSING": sum(v == "CONSUMER_MISSING" for v in coverage_map.values()),
        "COVERED": sum(v == "COVERED" for v in coverage_map.values()),
    }

    tracker_results = {
        "NEW": [],
        "CONFIRMED": [],
        "INVALIDATED": [],
        "DEFERRED": [],
    }

    if core_operational:
        try:
            # Tracker에는 Consumer가 검증을 끝낸 validated_candidates만 전달한다.
            # coverage_map은 bool이 아니라 정확한 lineage 원인을 전달한다.
            tracker_results = signal_tracker.process_pipeline_signals(
                validated_candidates=validated_candidates,
                active_db_signals=active_db_signals,
                active_tracked_codes=active_tracked_codes,
                coverage_map=coverage_map,
            )

            if type(tracker_results) is not dict:
                raise TypeError("Signal Tracker must return dict")

            required_tracker_keys = {"NEW", "CONFIRMED", "INVALIDATED", "DEFERRED"}
            if set(tracker_results.keys()) != required_tracker_keys:
                raise ValueError(
                    "Signal Tracker return contract violation: "
                    f"expected={sorted(required_tracker_keys)}, "
                    f"actual={sorted(tracker_results.keys())}"
                )

            for key in required_tracker_keys:
                if type(tracker_results[key]) is not list:
                    raise TypeError(f"tracker_results[{key}] must be list")

            # Tracker가 예외 없이 반환했다는 것은 DB 내부에서 모든
            # transition commit이 SUCCESS로 끝났다는 cross-file 계약을 전제로 한다.
            tracker_success = True
        except Exception as e:
            _logger.critical(
                "CRITICAL CORE FAILURE: Signal Tracker / DB persistence failed: %s",
                e,
                exc_info=True,
            )
            tracker_success = False

    # =============================================================
    # [H] Report Builder
    # =============================================================
    report_blocks = []
    try:
        signal_stats = {
            "gate_open": gate_open,
            "engine_status": engine_status,
            "engine_skip_reason": engine_skip_reason,
            "scanner_ran": scanner_success,
            "engine_ran": engine_success,
            "engine_error": engine_status == "ERROR",
            "features_count": len(features_list),
            "portfolio_state_valid": holdings_eval_success and holdings_persistence_success,
            "core_operational": core_operational,
            "promotion_state": promotion_state,
            "promotion_safe": promotion_safe,
            "engine_buy_blocked": engine_buy_blocked,
            "block_reason": decision_results.get("block_reason", "") if engine_success else "",
            "level_counts": level_counts,
            "shadow_candidates": shadow_candidates,
            "actual_signals": actual_signals,
            "active_tracked_codes": sorted(active_tracked_codes),
            "scanned_codes": sorted(scanned_codes),
            "engine_evaluated_codes": sorted(engine_evaluated_codes),
            "consumer_evaluated_codes": sorted(consumer_evaluated_codes),
            "coverage_map": coverage_map,
            "coverage_counts": coverage_counts,
            "pipeline_coverage_complete": pipeline_coverage_complete,
            "validated_candidates": validated_candidates,
            "buy_contract_failures": buy_contract_failures,
            "non_buy_contract_failures": non_buy_contract_failures,
            "tracker_success": tracker_success,
            "tracker_results": tracker_results,
        }

        m_ctx_safe = market_ctx if market_success else {
            "state": "UNKNOWN",
            "score": 0.0,
            "kospi_1d": 0.0,
            "kosdaq_1d": 0.0,
            "advance_ratio": 0.0,
            "allow_scan": False,
        }

        report_blocks.append(report_formatter.format_market_report(m_ctx_safe))
        report_blocks.append(report_formatter.format_holding_report(holding_evals))
        report_blocks.append(report_formatter.format_scanner_health(scanner_telemetry))
        report_blocks.append(report_formatter.format_decision_report(signal_stats))
        report_blocks.append(report_formatter.format_promotion_report(signal_stats))

        if not validate_report_blocks(report_blocks):
            raise ValueError("Report Blocks Contract Violation")
        render_success = True
    except Exception as e:
        _logger.critical("CRITICAL: Report Formatter Crash: %s", e, exc_info=True)
        fallback_blocks = [
            "🚨 <b>시스템 심각한 내부 오류</b>\n\n"
            "- 리포트 렌더링 중 예외 발생\n"
            "- 코어 상태를 Fail-Closed로 처리합니다."
        ]
        report_blocks = fallback_blocks if validate_report_blocks(fallback_blocks) else ["CORE_FAILURE"]
        render_success = False

    # =============================================================
    # [I] Delivery Isolation + Final Exit Semantics
    # =============================================================
    api_accepted = False
    try:
        api_accepted = send_telegram_blocks(report_blocks)
    except Exception as e:
        _logger.critical("CRITICAL: Telegram delivery subsystem crashed: %s", e, exc_info=True)
        api_accepted = False

    # 영속성 계층 실패는 절대 DEGRADED로 낮추지 않는다.
    # Pipeline coverage incomplete는 Tracker가 해당 lineage를 DEFERRED로 보존해야
    # 하며, active signal을 INVALIDATED로 죽이지 않는 것이 핵심이다.
    if not core_operational or not tracker_success or not render_success:
        core_state = "FAILURE"
    elif not promotion_safe:
        # Consumer가 Producer의 BUY 결과를 차단한 안전한 기능 저하.
        core_state = "DEGRADED"
    else:
        core_state = "SUCCESS"

    _logger.info(
        "Final State: CORE_%s | DELIVERY_%s | PIPELINE_COVERAGE_%s",
        core_state,
        "SUCCESS" if api_accepted else "FAILURE",
        "COMPLETE" if pipeline_coverage_complete else "DEFERRED",
    )

    if core_state == "SUCCESS" and api_accepted:
        sys.exit(EXIT_SUCCESS)
    elif core_state == "FAILURE":
        sys.exit(EXIT_CORE_FAILURE)
    elif core_state == "SUCCESS" and not api_accepted:
        sys.exit(EXIT_DELIVERY_FAILURE)
    elif core_state == "DEGRADED" and api_accepted:
        sys.exit(EXIT_DEGRADED_SUCCESS)
    else:
        sys.exit(EXIT_DEGRADED_FAILURE)

if __name__ == "__main__":
    import multiprocessing as mp
    mp.freeze_support()
    run_pipeline()
