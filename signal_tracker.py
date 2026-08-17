# signal_tracker.py
import logging
import time
from datetime import datetime
import pytz
import database

_logger = logging.getLogger(__name__)

VALID_CONTRACT_STATUSES = {"PASS", "FAIL", "NOT_EVALUATED"}

def get_kst_now() -> str:
    return datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")

def _validate_candidate_uniqueness(candidates: list):
    """입력 후보군 내 동일 종목 중복을 허용하지 않고 즉시 하드 스톱"""
    seen = set()
    for cand in candidates:
        code = cand["code"]
        if code in seen:
            raise RuntimeError(f"DUPLICATE_CANDIDATE_CODE: {code} appears multiple times in evaluated candidates")
        seen.add(code)

def _create_new_signal_with_retry(cand: dict) -> str:
    code = cand["code"]
    date_str = get_kst_now()[:10]
    strats = cand["plan"]["strategies_at_plan"]
    
    for attempt in range(3):
        revision = database.get_next_signal_revision(code, date_str)
        sig_id = database.generate_signal_id(code, date_str, strats, revision)
        
        master_data = {"signal_id": sig_id, "code": code, "signal_date": date_str, "strategies": strats, "revision": revision}
        registry_data = {
            "signal_id": sig_id, "code": code, "name": cand["name"],
            "signal_state": "WATCH", "first_seen_at": get_kst_now(), "last_seen_at": get_kst_now(),
            "last_price": cand["price"], "entry_price": cand["plan"]["entry"],
            "stop_loss": cand["plan"]["stop_loss"], "target1": cand["plan"]["target1"],
            "target2": cand["plan"]["target2"], "ev": cand["plan"]["sizing"]["ev"],
            "expected_reward_rr": cand["plan"]["expected_reward_rr"],
            "current_level": cand["decision"]["level"], "confirmation_count": 1,
            "invalidation_reason": "PASS"
        }
        log_data = {
            "signal_id": sig_id, "code": code, "level": cand["decision"]["level"],
            "ev": cand["plan"]["sizing"]["ev"], "signal_state": "WATCH",
            "price": cand["price"], "action_note": "NEW_SIGNAL_DETECTED"
        }
        
        status = database.save_signal_transition(master_data, registry_data, log_data)
        
        if status == "SUCCESS":
            _logger.info(f"New Signal Created: {sig_id} (Rev {revision})")
            cand["signal_id"] = sig_id
            return sig_id
        elif status == "REVISION_COLLISION":
            _logger.warning(f"Revision collision for {code} R{revision}. Retrying attempt {attempt+1}/3...")
            time.sleep(0.1)
            continue
        elif status == "DB_BUSY":
            delay = 0.2 * (2 ** attempt)
            _logger.warning(f"Database is locked/busy for {code}. Retrying in {delay}s...")
            time.sleep(delay)
            continue
        elif status == "ACTIVE_LINEAGE_COLLISION":
            _logger.error(f"CRITICAL: Attempted to create new signal for {code} but an active signal already exists in DB.")
            break
        else:
            _logger.error(f"CRITICAL: Signal creation failed for {code} due to {status}")
            break
            
    _logger.error(f"CRITICAL: Failed to create new signal for {code} after 3 attempts.")
    return None

def _transition_existing_signal(cand: dict, sig_id: str, new_state: str, old_registry_row: dict, reason: str) -> bool:
    """DB 트랜잭션의 최종 성공 여부를 명시적으로 반환"""
    code = old_registry_row["code"]
    is_invalidated = (new_state == "INVALIDATED")
    is_evaluated = cand is not None
    
    conf_count = old_registry_row["confirmation_count"]
    if new_state == "CONFIRMED" and old_registry_row["signal_state"] == "WATCH":
        conf_count += 1
        
    registry_data = {
        "signal_id": sig_id, "code": code, "name": old_registry_row["name"],
        "signal_state": new_state, "first_seen_at": old_registry_row["first_seen_at"],
        "last_seen_at": get_kst_now() if is_evaluated else old_registry_row["last_seen_at"], 
        "last_price": cand["price"] if is_evaluated else old_registry_row["last_price"],
        
        "entry_price": cand["plan"]["entry"] if is_evaluated and not is_invalidated else old_registry_row["entry_price"],
        "stop_loss": cand["plan"]["stop_loss"] if is_evaluated and not is_invalidated else old_registry_row["stop_loss"],
        "target1": cand["plan"]["target1"] if is_evaluated and not is_invalidated else old_registry_row["target1"],
        "target2": cand["plan"]["target2"] if is_evaluated and not is_invalidated else old_registry_row["target2"],
        "ev": cand["plan"]["sizing"]["ev"] if is_evaluated and not is_invalidated else old_registry_row["ev"],
        "expected_reward_rr": cand["plan"]["expected_reward_rr"] if is_evaluated and not is_invalidated else old_registry_row["expected_reward_rr"],
        # [P1] 무효화(INVALIDATED)되거나 관측 실패(DEFERRED) 시에도, 신호의 마지막 Level을 파괴하지 않고 보존
        "current_level": cand["decision"]["level"] if is_evaluated and not is_invalidated else old_registry_row["current_level"],
        
        "confirmation_count": conf_count,
        "invalidation_reason": reason if is_invalidated else old_registry_row.get("invalidation_reason", "PASS")
    }
    
    log_data = {
        "signal_id": sig_id, "code": code, 
        "level": cand["decision"]["level"] if is_evaluated and not is_invalidated else old_registry_row["current_level"], 
        "ev": cand["plan"]["sizing"]["ev"] if is_evaluated and not is_invalidated else old_registry_row["ev"],
        "signal_state": new_state, 
        "price": cand["price"] if is_evaluated else old_registry_row["last_price"], 
        "action_note": reason
    }
    
    for attempt in range(3):
        status = database.save_signal_transition(None, registry_data, log_data)
        if status == "SUCCESS":
            if is_evaluated:
                cand["signal_id"] = sig_id
                cand["signal_state"] = new_state
                cand["invalidation_reason"] = reason
            return True
        elif status == "DB_BUSY":
            delay = 0.2 * (2 ** attempt)
            _logger.warning(f"DB busy during transition of {sig_id}. Retrying in {delay}s...")
            time.sleep(delay)
            continue
        else:
            _logger.error(f"CRITICAL: Transition failed for {sig_id} due to {status}")
            return False
            
    _logger.error(f"CRITICAL: Failed to transition signal {sig_id} after 3 attempts.")
    return False

def process_pipeline_signals(all_evaluated_candidates: list, active_db_signals: dict, active_tracked_codes: set, scan_complete: bool) -> dict:
    tracked_results = {"NEW": [], "CONFIRMED": [], "INVALIDATED": [], "DEFERRED": []}
    
    _validate_candidate_uniqueness(all_evaluated_candidates)
    
    active_code_to_id = {}
    for sig_id, row in active_db_signals.items():
        if row["signal_state"] not in {"WATCH", "CONFIRMED"}:
            raise RuntimeError(f"INVALID_ACTIVE_INPUT_STATE: {sig_id} has invalid state '{row['signal_state']}'")
        code = row["code"]
        if code in active_code_to_id:
            raise RuntimeError(f"CORRUPTED_ACTIVE_LINEAGE: Multiple active signals found for {code}")
        active_code_to_id[code] = sig_id
        
    active_db_codes = set(active_code_to_id.keys())
    unknown_tracked = set(active_tracked_codes) - active_db_codes
    if unknown_tracked:
        raise RuntimeError(f"INVALID_ACTIVE_TRACKED_CODES: Contains unknown codes {sorted(list(unknown_tracked))}")
        
    seen_codes = set()
    
    for cand in all_evaluated_candidates:
        code = cand["code"]
        seen_codes.add(code)
        
        contract_status = cand.get("contract_status", "NOT_EVALUATED")
        contract_reason = cand.get("contract_reason", "NO_STATUS")
        
        if contract_status not in VALID_CONTRACT_STATUSES:
            raise RuntimeError(f"UNKNOWN_CONTRACT_STATUS: {code} returned invalid status '{contract_status}'")
        
        if code in active_code_to_id:
            sig_id = active_code_to_id[code]
            row = active_db_signals[sig_id]
            
            if contract_status == "PASS":
                if _transition_existing_signal(cand, sig_id, "CONFIRMED", row, "CONDITIONS_MET"):
                    tracked_results["CONFIRMED"].append(cand)
                else:
                    raise RuntimeError(f"TRACKER_COMMIT_FAILURE: Failed to commit CONFIRMED transition for {sig_id}")
                    
            elif contract_status == "FAIL":
                if _transition_existing_signal(cand, sig_id, "INVALIDATED", row, contract_reason):
                    tracked_results["INVALIDATED"].append(cand)
                else:
                    raise RuntimeError(f"TRACKER_COMMIT_FAILURE: Failed to commit INVALIDATED transition for {sig_id}")
                    
            elif contract_status == "NOT_EVALUATED":
                _logger.warning(f"Signal {sig_id} not evaluated ({contract_reason}). Deferred.")
                if _transition_existing_signal(None, sig_id, row["signal_state"], row, "EVALUATION_DEFERRED"):
                    cand["signal_state"] = row["signal_state"]
                    tracked_results["DEFERRED"].append(cand)
                else:
                    raise RuntimeError(f"TRACKER_COMMIT_FAILURE: Failed to commit DEFERRED transition for {sig_id}")
                
        elif contract_status == "PASS" and cand["decision"].get("level") in ["LEVEL 3", "LEVEL 2", "LEVEL 1"]:
            sig_id = _create_new_signal_with_retry(cand)
            # [P0] 신규 신호 DB 생성 실패 시 조용한 증발을 막고 시스템 셧다운 (Fail-Closed)
            if not sig_id:
                raise RuntimeError(f"TRACKER_COMMIT_FAILURE: Failed to create NEW signal for {code}")
            
            cand["signal_state"] = "WATCH"
            tracked_results["NEW"].append(cand)

    missing_codes = active_db_codes - seen_codes
    for code in missing_codes:
        sig_id = active_code_to_id[code]
        row = active_db_signals[sig_id]
        
        if code in active_tracked_codes:
            err_msg = f"PIPELINE_INTEGRITY_FAILURE: Signal {sig_id} ({code}) requested for eval but produced no result."
            _logger.error(err_msg)
            if not _transition_existing_signal(None, sig_id, row["signal_state"], row, "PIPELINE_ERROR_DEFERRED"):
                raise RuntimeError(f"TRACKER_COMMIT_FAILURE: Failed to commit PIPELINE_ERROR_DEFERRED for {sig_id}")
        elif not scan_complete:
            _logger.warning(f"Active signal {sig_id} missing, but scan incomplete. Holding state.")
            if not _transition_existing_signal(None, sig_id, row["signal_state"], row, "SCAN_COVERAGE_DEFERRED"):
                raise RuntimeError(f"TRACKER_COMMIT_FAILURE: Failed to commit SCAN_COVERAGE_DEFERRED for {sig_id}")
        else:
            _logger.warning(f"Active signal {sig_id} missing from complete scan. Invalidating.")
            if not _transition_existing_signal(None, sig_id, "INVALIDATED", row, "DROPPED_FROM_SCANNER"):
                raise RuntimeError(f"TRACKER_COMMIT_FAILURE: Failed to commit DROPPED_FROM_SCANNER for {sig_id}")

    return tracked_results
