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
    _logger.info("=== 5-Stage Quant Trading Engine Started ===")
    
    # 1. Market (거시 환경 분석)
    try:
        market_ctx = market_check.get_market_context()
    except Exception as e:
        _logger.exception("Market check crash: %s", e)
        send_telegram_msg("🚨 시장 엔진 붕괴: " + str(e)[:30])
        return

    # 기존 market_report 사용 유지
    stats_dict = market_report.build_market_report(market_ctx) if hasattr(market_report, 'build_market_report') else market_ctx
    msg_mkt = report_formatter.format_market_report(stats_dict)
    send_telegram_msg(msg_mkt)

    # 2. Portfolio & Holding (가장 시급했던 와이씨 누락 패치 및 독립화 적용)
    holdings_data = holding_analyzer.load_holdings("holdings.json")
    if holdings_data:
        # 스캐너 실행 전에, 독립적으로 FDR 조회하여 수익률 및 손절가 이탈 판별
        holding_evals = holding_analyzer.evaluate_holdings(holdings_data)
        msg_holdings = report_formatter.format_holding_report(holding_evals)
        send_telegram_msg(msg_holdings)

    # 시장 상태 악화 시 신규 스캔 중지
    if not market_ctx.get("allow_scan", False):
        _logger.warning("Scan bypassed. Market State: %s", market_ctx.get("state"))
        return

    # 3. Scanner (거래대금/수급 피처 추가)
    try:
        features_list = scanner.run_scanner(market_ctx)
        _logger.info("Scanner generated %d features.", len(features_list))
    except Exception as e:
        _logger.exception("Scanner runtime error: %s", e)
        return

    # 4. Decision Engine (Rule-based 매매 결정 및 리스크 수집)
    decision_results = decision_engine.evaluate_candidates(
        features_list, market_ctx, holdings_data, total_equity=CONFIG.TOTAL_EQUITY
    )
    
    # 5. Telegram Report (UX/UI 양식 고도화)
    msg_signals = report_formatter.format_signal_report(decision_results)
    send_telegram_msg(msg_signals)
    _logger.info("=== Pipeline Completed ===")

if __name__ == "__main__":
    run_pipeline()
