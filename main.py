import os
import sys
import time
import json
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

@dataclass
class AppConfig:
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    TOTAL_EQUITY: float = 10_000_000

CONFIG = AppConfig()

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S', handlers=[logging.StreamHandler(sys.stdout)])
_logger = logging.getLogger(__name__)

TELEGRAM_MAX_LEN = 3900  

# [불변 규칙] 승격 허용 등급 단일 상수화
BUY_LEVELS = {"LEVEL 3", "LEVEL 2", "LEVEL 1"}

def _split_message(message: str, max_len: int = TELEGRAM_MAX_LEN):
    chunks = []
    current = ""
    for line in message.split("\n"):
        candidate = (current + "\n" + line) if current else line
        if len(candidate) <= max_len:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(line) > max_len:
                for i in range(0, len(line), max_len):
                    chunks.append(line[i:i + max_len])
                current = ""
            else:
                current = line
    if current:
        chunks.append(current)
    return chunks or [message]

def _send_one_telegram_msg(text: str):
    url = f"https://api.telegram.org/bot{CONFIG.TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CONFIG.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}

    for attempt in range(3):
        try:
            requests.post(url, json=payload, timeout=10.0).raise_for_status()
            return
        except Exception as e:
            _logger.error("Telegram send failed (attempt %d/3): %s", attempt + 1, e)
            time.sleep(2)

def send_telegram_msg(message: str):
    if not CONFIG.TELEGRAM_TOKEN:
        _logger.warning("Telegram token missing, skipping alert.")
        return
    for chunk in _split_message(message):
        _send_one_telegram_msg(chunk)

def run_pipeline():
    _logger.info("=== 5-Stage Observability Pipeline Started ===")

    # -------------------------------------------------------------
    # [1/5] Market Check (V14 Frozen)
    # -------------------------------------------------------------
    try:
        market_ctx = market_check.get_market_context()
    except Exception as e:
        _logger.exception("Market check crash: %s", e)
        send_telegram_msg("🚨 시장 엔진 붕괴: " + str(e)[:30])
        return

    gate_open = market_ctx.get("allow_scan", False)
    final_report = []

    stats_dict = market_report.build_market_report(market_ctx)
    msg_mkt = report_formatter.format_market_report(stats_dict)
    final_report.append(msg_mkt)

    # -------------------------------------------------------------
    # [2/5] PriceCache & Holding Analyzer
    # -------------------------------------------------------------
    price_cache = scanner.build_price_cache()
    if not price_cache:
        _logger.error("Price cache empty. 데이터 장애로 신규 스캔이 차단됩니다.")
        scanner_can_run = False
    else:
        scanner_can_run = True

    holdings_data = holding_analyzer.load_holdings("holdings.json")
    _logger.info("Loaded holding count: %d", len(holdings_data))

    holding_evals = holding_analyzer.evaluate_holdings(holdings_data, price_cache)

    if holding_evals:
        temp_name = ""
        try:
            dir_name = os.path.dirname(os.path.abspath("holdings.json")) or '.'
            with tempfile.NamedTemporaryFile('w', delete=False, dir=dir_name, encoding='utf-8') as f:
                json.dump(holding_evals, f, ensure_ascii=False, indent=4)
                temp_name = f.name
            os.replace(temp_name, "holdings.json")
        except Exception as e:
            _logger.error("보유종목 저장 실패: %s", e)
            if temp_name and os.path.exists(temp_name):
                os.remove(temp_name)

        msg_holdings = report_formatter.format_holding_report(holding_evals)
        final_report.append(msg_holdings)

    # -------------------------------------------------------------
    # [3/5] Scanner Engine (무조건 실행)
    # -------------------------------------------------------------
    features_list = []
    scanner_telemetry = {"is_ran": False}

    if scanner_can_run:
        try:
            _logger.info("Running Scanner Engine (Gate: %s)", "OPEN" if gate_open else "BLOCKED")
            features_list = scanner.run_scanner(market_ctx, price_cache)
            
            scanner_rejects = market_ctx.get("scanner_rejects", {})
            total_univ = len(price_cache)
            prefilter_drop = scanner_rejects.get("PREFILTER_DROP", 0)
            
            scanner_telemetry = {
                "is_ran": True,
                "total_universe": total_univ,
                "prefilter_pass": total_univ - prefilter_drop,
                "fetch_fail": scanner_rejects.get("FETCH_FAIL", 0),
                "feature_pass": scanner_rejects.get("PASS", 0),
                "rejects": scanner_rejects
            }
        except Exception as e:
            _logger.exception("Scanner runtime error: %s", e)

    msg_health = report_formatter.format_scanner_health(scanner_telemetry)
    final_report.append(msg_health)

    # -------------------------------------------------------------
    # [4/5] Decision Engine (엄격한 타입 검증 및 예외 방어)
    # -------------------------------------------------------------
    decision_results = {}
    scanner_ran = scanner_telemetry.get("is_ran", False)
    engine_ran = False
    engine_error = False
    features_count = len(features_list)

    if scanner_ran:
        if features_count > 0:
            try:
                result = decision_engine.evaluate_candidates(
                    features_list=features_list,
                    market_context=market_ctx,
                    sys_state={},
                    holdings_data=holdings_data,
                    total_equity=CONFIG.TOTAL_EQUITY
                )
                
                # 1. 반환 타입 1차 검증
                if not isinstance(result, dict):
                    raise TypeError(f"Decision Engine returned {type(result).__name__}, expected dict")
                
                # 2. 필수 Key 존재 검증
                required_keys = {"candidates", "buy_blocked", "block_reason", "level_counts"}
                missing_keys = required_keys - result.keys()
                if missing_keys:
                    raise ValueError(f"Decision Engine result missing keys: {sorted(missing_keys)}")
                
                # 3. 내부 필드 타입 2차 검증
                if not isinstance(result.get("candidates"), list):
                    raise TypeError("Decision Engine 'candidates' must be list")
                if not isinstance(result.get("level_counts"), dict):
                    raise TypeError("Decision Engine 'level_counts' must be dict")
                if not isinstance(result.get("buy_blocked"), bool):
                    raise TypeError("Decision Engine 'buy_blocked' must be bool")
                
                decision_results = result
                engine_ran = True
            except Exception as e:
                _logger.exception("Decision Engine runtime error: %s", e)
                engine_error = True
        else:
            _logger.info("Skipping Decision Engine: Scanner Feature 0건")
    else:
        _logger.warning("Decision Engine Not Run: Scanner Failure")

    # -------------------------------------------------------------
    # [5/5] Promotion (명시적 방어 승격)
    # -------------------------------------------------------------
    shadow_candidates = decision_results.get("candidates", []) if engine_ran and not engine_error else []
    level_counts = decision_results.get("level_counts", {}) if engine_ran and not engine_error else {}
    
    # [방어] 엔진이 온전히 돌았을 때만 엔진의 판단 존중, 그 외는 무조건 차단(Fail-Closed)
    engine_buy_blocked = decision_results.get("buy_blocked", False) if engine_ran and not engine_error else True

    # [핵심] 4단 콤보 명시적 승격 규칙
    if engine_ran and not engine_error and gate_open and not engine_buy_blocked:
        actual_signals = [
            c for c in shadow_candidates
            if c.get("decision", {}).get("level") in BUY_LEVELS
        ]
    else:
        actual_signals = []

    # 전체 상태 캡슐화
    signal_stats = {
        "gate_open": gate_open,
        "scanner_ran": scanner_ran,
        "engine_ran": engine_ran,
        "engine_error": engine_error,
        "features_count": features_count,
        "engine_buy_blocked": engine_buy_blocked,
        "block_reason": decision_results.get("block_reason", "") if engine_ran and not engine_error else "",
        "level_counts": level_counts,
        "shadow_candidates": shadow_candidates,
        "actual_signals": actual_signals
    }

    msg_decision = report_formatter.format_decision_report(signal_stats)
    final_report.append(msg_decision)

    msg_promotion = report_formatter.format_promotion_report(signal_stats)
    final_report.append(msg_promotion)

    # 텔레그램 발송
    send_telegram_msg("\n".join(final_report))
    _logger.info("=== Observability Pipeline Completed ===")

if __name__ == "__main__":
    import multiprocessing as mp
    mp.freeze_support()
    run_pipeline()
