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
# 1. Configuration & Setup
# =========================================================
@dataclass
class AppConfig:
    # 환경 변수 또는 하드코딩
    TELEGRAM_TOKEN: str = os.getenv("TG_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: str = os.getenv("TG_CHAT_ID", "YOUR_CHAT_ID")
    DAEMON_MODE: bool = False  # True면 무한 루프, False면 Github Actions 용 1회 실행
    INTERVAL_SEC: int = 3600   # 데몬 모드 시 실행 주기 (1시간)

CONFIG = AppConfig()

# 로깅 기본 세팅 (INFO 이상 출력, 포맷팅 통일)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
)

class ContextAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[{self.extra['ctx']}] {msg}", kwargs

_logger = ContextAdapter(logging.getLogger(__name__), {'ctx': 'MAIN'})

# Telegram 통신용 안전한 세션
_tg_session = requests.Session()
_tg_session.mount("https://", HTTPAdapter(
    max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
))

# =========================================================
# 2. Telegram Alert Service
# =========================================================
def send_telegram_msg(message: str):
    if not CONFIG.TELEGRAM_TOKEN or CONFIG.TELEGRAM_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        _logger.warning("Telegram Token not set. Skipping message: \n%s", message)
        return
        
    url = f"https://api.telegram.org/bot{CONFIG.TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CONFIG.TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    
    try:
        resp = _tg_session.post(url, json=payload, timeout=10.0)
        resp.raise_for_status()
        _logger.info("Telegram message sent successfully.")
    except Exception as e:
        _logger.error("Failed to send Telegram message: %s", e)

# =========================================================
# 3. Main Execution Pipeline
# =========================================================
def run_pipeline():
    _logger.info("=== Starting Trading Pipeline ===")
    
    # Step 1. 시장 상태 진단
    try:
        market_ctx = market_check.get_market_context()
    except Exception as e:
        _logger.exception("CRITICAL: Market Check completely failed: %s", e)
        send_telegram_msg("🚨 <b>CRITICAL ERROR</b>\n시장 상태 모듈(market_check)이 붕괴되었습니다. 즉시 확인 요망.")
        return

    # 시장 상태 브리핑 포맷팅
    mkt_state = market_ctx.get("state", "UNKNOWN")
    mkt_score = market_ctx.get("data_quality", 0)
    msg_mkt = (
        f"📊 <b>Market Health Report</b>\n"
        f"상태: <b>{mkt_state}</b> (Score: {mkt_score})\n"
        f"KOSPI 1D: {market_ctx.get('kospi_1d', 0)}%\n"
        f"KOSDAQ 1D: {market_ctx.get('kosdaq_1d', 0)}%\n"
        f"이유: {market_ctx.get('reason', 'None')}\n"
        f"선정 소스: {market_ctx.get('source', 'None')}"
    )
    send_telegram_msg(msg_mkt)
    
    # Step 2. 스캔 허용 여부 판별 (INVALID면 스캔 중지)
    if not market_ctx.get("allow_scan", False):
        _logger.warning("Market state is %s. Bypassing scanner to protect capital.", mkt_state)
        send_telegram_msg("🛡️ 시장 위험 감지. <b>스캐닝 및 매수 로직을 중단(Bypass)</b>하여 자본을 보호합니다.")
        return
        
    # Step 3. 종목 스캔 진행
    try:
        signals = scanner.run_scanner(market_ctx)
    except Exception as e:
        _logger.exception("CRITICAL: Scanner failed: %s", e)
        send_telegram_msg("🚨 <b>CRITICAL ERROR</b>\n스캐너 모듈에서 예외가 발생했습니다.")
        return
        
    # Step 4. 시그널 통보
    if not signals:
        _logger.info("No actionable signals found.")
        send_telegram_msg("🕵️‍♂️ <b>Scan Result</b>\n현재 시장 상태 및 필터링 기준을 만족하는 종목이 없습니다.")
    else:
        # 상위 5개만 발송
        top_signals = signals[:5]
        sig_texts = [
            f"🔹 <b>{s['name']}</b> ({s['symbol']})\n"
            f"   현재가: {s['price']:,}원\n"
            f"   20MA 이격도: {s['ma20_gap']}%\n"
            f"   거래량 배수: {s['vol_ratio']}배"
            for s in top_signals
        ]
        msg_sig = "🎯 <b>Actionable Signals (Top 5)</b>\n\n" + "\n\n".join(sig_texts)
        send_telegram_msg(msg_sig)

# =========================================================
# 4. Entry Point
# =========================================================
if __name__ == "__main__":
    if CONFIG.DAEMON_MODE:
        _logger.info("Running in DAEMON mode. Interval: %ds", CONFIG.INTERVAL_SEC)
        while True:
            run_pipeline()
            _logger.info("Sleeping for %d seconds...", CONFIG.INTERVAL_SEC)
            time.sleep(CONFIG.INTERVAL_SEC)
    else:
        _logger.info("Running in SINGLE-RUN (GitHub Actions) mode.")
        run_pipeline()
        _logger.info("=== Pipeline Completed ===")
