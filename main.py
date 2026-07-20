import os
import sys
import logging
from dataclasses import dataclass
import requests

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
    # 추후 증권사 API 연동을 통해 실시간 계좌 잔고를 불러오도록 업데이트 예정
    TOTAL_EQUITY: float = 10_000_000  

CONFIG = AppConfig()

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S', handlers=[logging.StreamHandler(sys.stdout)])
_logger = logging.getLogger(__name__)

def send_telegram_msg(message: str):
    if not CONFIG.TELEGRAM_TOKEN:
        _logger.warning("Telegram token missing, skipping alert.")
        return
    url = f"https://api.telegram.org/bot{CONFIG.TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CONFIG.TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10.0).raise_for_status()
    except Exception as e:
        _logger.error("Failed to send Telegram message: %s", e)

def run_pipeline():
    _logger.info("=== 4-Stage Quant Pipeline Started ===")
    
    try:
        market_ctx = market_check.get_market_context()
    except Exception as e:
        _logger.exception("Market check crash: %s", e)
        send_telegram_msg("🚨 시장 엔진 붕괴: " + str(e)[:30])
        return

    stats_dict = market_report.build_market_report(market_ctx)
    msg_mkt = report_formatter.format_market_report(stats_dict)
    send_telegram_msg(msg_mkt)

    if not market_ctx.get("allow_scan", False):
        _logger.warning("Scan bypassed. Market State: %s", market_ctx.get("state"))
        return

    try:
        features_list = scanner.run_scanner(market_ctx)
        _logger.info("Scanner generated %d features.", len(features_list))
    except Exception as e:
        _logger.exception("Scanner runtime error: %s", e)
        return

    holdings_data = holding_analyzer.load_holdings("holdings.json")

    if holdings_data:
        features_map = {cf.code: cf for cf in features_list}
        holding_evals = holding_analyzer.evaluate_holdings(holdings_data, features_map)
        msg_holdings = report_formatter.format_holding_report(holding_evals)
        send_telegram_msg(msg_holdings)

    decision_results = decision_engine.evaluate_candidates(features_list, market_ctx, holdings_data, total_equity=CONFIG.TOTAL_EQUITY)
    
    msg_signals = report_formatter.format_signal_report(decision_results)
    send_telegram_msg(msg_signals)
    _logger.info("=== Pipeline Completed ===")

if __name__ == "__main__":
    run_pipeline()
