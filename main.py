import os
import sys
import time
import logging
from dataclasses import dataclass
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import market_check
import scanner

# =========================================================
# 1. Config & Debugging (토큰 로딩 문제 확인)
# =========================================================
@dataclass
class AppConfig:
    # 환경 변수 로그 확인용 (디버깅 후 마스킹 예정)
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    DAEMON_MODE: bool = False
    INTERVAL_SEC: int = 3600

CONFIG = AppConfig()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# 토큰 디버깅: 로딩 직후 상태 로그 확인
if not CONFIG.TELEGRAM_TOKEN:
    logging.error("CRITICAL: TELEGRAM_TOKEN 환경변수를 찾을 수 없습니다!")
else:
    logging.info("Telegram Token loaded (Length: %d)", len(CONFIG.TELEGRAM_TOKEN))

_logger = logging.getLogger(__name__)

# =========================================================
# 2. Telegram Alert Service (상세 에러 핸들링)
# =========================================================
def send_telegram_msg(message: str):
    if not CONFIG.TELEGRAM_TOKEN:
        _logger.warning("Telegram token missing, skipping alert.")
        return
        
    url = f"https://api.telegram.org/bot{CONFIG.TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CONFIG.TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    
    try:
        resp = requests.post(url, json=payload, timeout=10.0)
        resp.raise_for_status()
        _logger.info("Telegram notification sent.")
    except Exception as e:
        _logger.error("Failed to send Telegram message: %s", e)

# =========================================================
# 3. Main Pipeline (ALL SOURCES FAILED 디버깅 강화)
# =========================================================
def run_pipeline():
    _logger.info("=== Pipeline Started ===")
    
    try:
        market_ctx = market_check.get_market_context()
    except Exception as e:
        _logger.exception("Market check crash: %s", e)
        send_telegram_msg("🚨 시장 엔진 붕괴: " + str(e)[:30])
        return

    # 상세 실패 원인 로깅 (ALL SOURCES FAILED 디버깅)
    if not market_ctx.get("breadth", {}).get("success", False):
        diag = market_ctx.get("breadth", {}).get("diag", {})
        err_msg = "\n".join([f"- {k}: {v.get('error', 'Unknown')}" for k, v in diag.items() if v.get('error')])
        _logger.error("Breadth sources failed details:\n%s", err_msg)
        send_telegram_msg(f"⚠️ 시장 데이터 수집 실패:\n{err_msg}")

    mkt_state = market_ctx.get("state", "INVALID")
    msg_mkt = (f"📊 <b>Market Health: {mkt_state}</b>\n"
               f"Reason: {market_ctx.get('reason', 'N/A')}\n"
               f"Source: {market_ctx.get('source', 'None')}")
    send_telegram_msg(msg_mkt)
    
    if not market_ctx.get("allow_scan", False):
        _logger.warning("Scan bypassed due to market state: %s", mkt_state)
        return
        
    try:
        signals = scanner.run_scanner(market_ctx)
        if signals:
            top = signals[:5]
            msg_sig = "🎯 <b>Actionable Signals</b>\n" + "\n".join([f"- {s['name']} ({s['chg']}%)" for s in top])
            send_telegram_msg(msg_sig)
        else:
            send_telegram_msg("🕵️‍♂️ No actionable signals found.")
    except Exception as e:
        _logger.exception("Scanner runtime error: %s", e)

if __name__ == "__main__":
    run_pipeline()
