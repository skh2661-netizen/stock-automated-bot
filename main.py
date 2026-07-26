import os
import sys
import time
import json
import logging
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

def send_telegram_msg(message: str):
    if not CONFIG.TELEGRAM_TOKEN:
        _logger.warning("Telegram token missing, skipping alert.")
        return
    url = f"https://api.telegram.org/bot{CONFIG.TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CONFIG.TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    
    for attempt in range(3):
        try:
            requests.post(url, json=payload, timeout=10.0).raise_for_status()
            return
        except Exception as e:
            _logger.error("Telegram send failed (attempt %d/3): %s", attempt + 1, e)
            time.sleep(2)

def run_pipeline():
    _logger.info("=== 4-Stage Quant Pipeline Started ===")
    
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

    holdings_data = holding_analyzer.load_holdings("holdings.json")
    _logger.info("Loaded holding count: %d", len(holdings_data))

    # 시장 차단(스캔 우회) 상태일 때도 보유 종목 평가는 반영하고 JSON에 저장
    if not market_ctx.get("allow_scan", False):
        _logger.warning("Scan bypassed. Market State: %s", market_ctx.get("state"))
        
        if holdings_data:
            holding_evals = holding_analyzer.evaluate_holdings(holdings_data, {})
            try:
                with open("holdings.json", "w", encoding="utf-8") as f:
                    json.dump(holding_evals, f, ensure_ascii=False, indent=4)
                _logger.info("보유종목 상태가 holdings.json에 성공적으로 저장(Update)되었습니다.")
            except Exception as e:
                _logger.error(f"보유종목 저장 실패: {e}")
                
            msg_holdings = report_formatter.format_holding_report(holding_evals)
            final_report.append("\n=== 💼 [2/3] 보유 종목 ===")
            final_report.append(msg_holdings)
            
        final_report.append("\n=== 🎯 [3/3] 신규 추천 ===")
        
        # UI 개선에 맞춰 텔레그램 포맷 수정
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

    try:
        features_list = scanner.run_scanner(market_ctx)
        _logger.info("Scanner generated %d raw features.", len(features_list))
    except Exception as e:
        _logger.exception("Scanner runtime error: %s", e)
        return

    if holdings_data:
        features_map = {cf.code: cf for cf in features_list}
        holding_evals = holding_analyzer.evaluate_holdings(holdings_data, features_map)
        
        # 보유 종목 평가 후 JSON 덮어쓰기 (영속성 유지)
        try:
            with open("holdings.json", "w", encoding="utf-8") as f:
                json.dump(holding_evals, f, ensure_ascii=False, indent=4)
            _logger.info("보유종목 상태가 holdings.json에 성공적으로 저장(Update)되었습니다.")
        except Exception as e:
            _logger.error(f"보유종목 저장 실패: {e}")
            
        msg_holdings = report_formatter.format_holding_report(holding_evals)
        final_report.append("\n=== 💼 [2/3] 보유 종목 ===")
        final_report.append(msg_holdings)

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
    run_pipeline()
