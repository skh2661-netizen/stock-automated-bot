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

TELEGRAM_MAX_LEN = 3900  # 텔레그램 실제 제한(4096)보다 여유를 둔 분할 기준

def _split_message(message: str, max_len: int = TELEGRAM_MAX_LEN):
    """긴 리포트를 줄 단위로 잘라 여러 메시지로 나눈다. 한 줄 자체가 max_len을 넘으면 그 줄만 강제 분할."""
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
    _logger.info("=== 4-Stage Quant Pipeline Started ===")

    # 1. Market
    try:
        market_ctx = market_check.get_market_context()
    except Exception as e:
        _logger.exception("Market check crash: %s", e)
        send_telegram_msg("🚨 시장 엔진 붕괴: " + str(e)[:30])
        return

    final_report = []

    stats_dict = market_report.build_market_report(market_ctx)
    msg_mkt = report_formatter.format_market_report(stats_dict)

    final_report.append("=== 📊 [1/3] 시장 리포트 ===")
    final_report.append(msg_mkt)

    # 2. PriceCache: KRX 전체 당일 시세를 한 번만 로드해서 Holding/Scanner가 공유
    price_cache = scanner.build_price_cache()
    if not price_cache:
        _logger.error("Price cache is empty (FDR/KRX 조회 실패 및 백업본 부재). 보유종목은 마지막 시세로, 신규 스캔은 건너뜁니다.")
        send_telegram_msg("⚠️ <b>시세 데이터 조회 및 복구 실패</b>\n오늘은 KRX 시세를 가져오지 못해 신규 스캔을 건너뜁니다. (보유종목은 마지막 시세 기준으로 평가)")

    # 3. Holding: 시장 차단 여부와 무관하게 항상 평가 + JSON 저장 (분기 통합)
    holdings_data = holding_analyzer.load_holdings("holdings.json")
    _logger.info("Loaded holding count: %d", len(holdings_data))

    holding_evals = holding_analyzer.evaluate_holdings(holdings_data, price_cache)

    if holding_evals:
        # [STEP 1 핵심] Atomic Write 적용 (파일 손상 원천 차단)
        temp_name = ""
        try:
            dir_name = os.path.dirname(os.path.abspath("holdings.json")) or '.'
            with tempfile.NamedTemporaryFile('w', delete=False, dir=dir_name, encoding='utf-8') as f:
                json.dump(holding_evals, f, ensure_ascii=False, indent=4)
                temp_name = f.name
            
            os.replace(temp_name, "holdings.json")
            _logger.info("보유종목 상태가 holdings.json에 성공적으로 저장(Atomic Update)되었습니다.")
        except Exception as e:
            _logger.error(f"보유종목 저장 실패: {e}")
            if temp_name and os.path.exists(temp_name):
                os.remove(temp_name)

        msg_holdings = report_formatter.format_holding_report(holding_evals)
        final_report.append("\n=== 💼 [2/3] 보유 종목 ===")
        final_report.append(msg_holdings)

    # 4. 시장 차단(스캔 우회) 상태면 여기서 신규 매수 안내만 보내고 종료
    if not market_ctx.get("allow_scan", False):
        _logger.warning("Scan bypassed. Market State: %s", market_ctx.get("state"))

        final_report.append("\n=== 🎯 [3/3] 신규 추천 ===")
        blocked_msg = f"==========================\n"
        blocked_msg += f"🚫 <b>오늘 신규매수 불가</b>\n"
        blocked_msg += f"사유: {market_ctx.get('state')} 국면\n"
        blocked_msg += f"==========================\n"
        blocked_msg += f"오늘 매수추천: <b>없음</b>\n"
        blocked_msg += f"==========================\n\n"
        blocked_msg += f"👉 <b>현재 행동: 현금 유지 및 관망</b>\n"
        blocked_msg += f"=========================="
        final_report.append(blocked_msg)

        send_telegram_msg("\n".join(final_report))
        return

    # 5. Scanner (PriceCache 전달)
    try:
        features_list = scanner.run_scanner(market_ctx, price_cache)
        _logger.info("Scanner generated %d raw features.", len(features_list))
    except Exception as e:
        _logger.exception("Scanner runtime error: %s", e)
        return

    # 6. Decision
    decision_results = decision_engine.evaluate_candidates(
        features_list=features_list,
        market_context=market_ctx,
        sys_state={},
        holdings_data=holdings_data,
        total_equity=CONFIG.TOTAL_EQUITY
    )

    level_counts = decision_results.get("level_counts", {})
    _logger.info("Decision breakdown: %s", level_counts)

    msg_signals = report_formatter.format_signal_report(decision_results)

    final_report.append("\n=== 🎯 [3/3] 신규 추천 ===")
    final_report.append(msg_signals)

    send_telegram_msg("\n".join(final_report))
    _logger.info("=== Pipeline Completed ===")

if __name__ == "__main__":
    # Windows 멀티프로세싱 재귀 방지 (안전 장치 추가)
    import multiprocessing as mp
    mp.freeze_support()
    run_pipeline()
