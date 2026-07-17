import asyncio
import logging
import time
import math

from market_check import get_market_context
from portfolio_manager import load_holdings, assess_portfolio_health
from scanner import fetch_history, fetch_raw_candidates
from feature_factory import build_features
from decision_engine import evaluate_candidates
from telegram_bot import format_scan_messages, send_message

async def main():
    t0 = time.time()
    pipe_stats = {"krx":0, "filter":0, "pool":0, "hist_ok":0, "hist_fail":0, "feat_ok":0, "feat_fail":0, "decision":0, "alert":0, "time":0.0}
    
    market = get_market_context()
    holdings = load_holdings()
    
    # [Portfolio 재평가]
    p_state = assess_portfolio_health(holdings, []) # 초기화
    
    # 👑 [Early Exit Gate] 데이터 검증 통과 여부 확인
    if not market.get("allow_scan", False):
        logging.warning("Pipeline Shutdown: Market Validation Failed")
        final_results = {"candidates": [], "alert_candidates": [], "buy_blocked": True, "block_reason": f"시장 데이터 검증 실패 ({market.get('reason')})"}
    else:
        # [Scanner]
        raw_data, scan_stats = fetch_raw_candidates()
        pipe_stats.update({"krx": scan_stats["krx_total"], "filter": scan_stats["filter_pass"], "pool": scan_stats["final_pool"]})
        
        if not raw_data:
            final_results = {"candidates": [], "alert_candidates": [], "buy_blocked": True, "block_reason": "스캐너 통과 종목 없음"}
        else:
            # [History]
            raw_with_hist = []
            for item in raw_data:
                hist = fetch_history(item['Code'])
                if hist is not None and len(hist) > 20: 
                    raw_with_hist.append({'code': item['Code'], 'name': item['Name'], 'hist': hist, 'chg': item['ChangesRatio']})
                    pipe_stats["hist_ok"] += 1
                else: pipe_stats["hist_fail"] += 1
            
            # [Feature]
            features_list = build_features(raw_with_hist, market)
            clean_features = [f for f in features_list if not (math.isnan(f.mom.rs_20d) or math.isnan(f.vty.atr_14))]
            pipe_stats["feat_ok"] = len(clean_features)
            
            # [Decision]
            final_results = evaluate_candidates(clean_features, market, holdings, p_state, is_holding_eval=False)
            pipe_stats["decision"] = len(final_results["candidates"])
            pipe_stats["alert"] = len(final_results["alert_candidates"])

    pipe_stats["time"] = round(time.time() - t0, 1)
    messages = format_scan_messages(final_results, holdings, p_state, pipe_stats)
    for msg in messages: await send_message(msg)
        
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
