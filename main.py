import asyncio
import logging
import os
import time

from market_check import get_market_context
from portfolio_manager import load_holdings, assess_portfolio_health
from scanner import fetch_history, fetch_raw_candidates
from feature_factory import build_features
from decision_engine import evaluate_candidates
from telegram_bot import format_scan_messages, send_message

async def main():
    start_time = time.time()
    pipe_stats = {"krx": 0, "filter": 0, "pool": 0, "history": 0, "feature": 0, "decision": 0, "alert": 0, "time": 0.0}
    
    # 1. Market Service
    market = get_market_context()
    logging.info(f"[Main] Market Quality: {market.get('data_quality')} | Source: {market.get('breadth', {}).get('source')}")
    
    # 2. Portfolio Service
    holdings = load_holdings()
    if holdings:
        holdings_raw = []
        for h in holdings:
            hist = fetch_history(h.code)
            if hist is not None and not hist.empty:
                holdings_raw.append({'code': h.code, 'name': h.name, 'data': hist})
        if holdings_raw:
            holdings_features = build_features(holdings_raw, market)
            holdings_eval = evaluate_candidates(holdings_features, market, holdings_data=None, is_holding_eval=True)
            p_state = assess_portfolio_health(holdings, holdings_eval['candidates'])
        else: p_state = assess_portfolio_health(holdings, [])
    else: p_state = assess_portfolio_health([], [])
        
    # 3. Scanner Service
    raw_data, scan_stats = fetch_raw_candidates()
    pipe_stats["krx"] = scan_stats.get("krx_total", 0)
    pipe_stats["filter"] = scan_stats.get("base_filter", 0)
    pipe_stats["pool"] = scan_stats.get("final_pool", 0)
    
    # 4. Feature Extraction (히스토리 검증된 종목만)
    raw_with_hist = []
    for item in raw_data:
        hist = fetch_history(item['Code'])
        if hist is not None and len(hist) > 20: # 20일선 최소 보장
            raw_with_hist.append({'code': item['Code'], 'name': item['Name'], 'data': hist, 'chg': item['ChangesRatio']})
            
    pipe_stats["history"] = len(raw_with_hist)
    features_list = build_features(raw_with_hist, market) if raw_with_hist else []
    pipe_stats["feature"] = len(features_list)
    
    # 5. Decision Engine
    final_results = evaluate_candidates(features_list, market, holdings, p_state, is_holding_eval=False)
    pipe_stats["decision"] = len(final_results["candidates"])
    pipe_stats["alert"] = len(final_results["alert_candidates"])
    
    # 6. Telegram Dispatch
    pipe_stats["time"] = round(time.time() - start_time, 1)
    messages = format_scan_messages(final_results, holdings, p_state, pipe_stats)
    
    for msg in messages:
        await send_message(msg)
        
    logging.info(f"Pipeline Completed in {pipe_stats['time']}s")
        
if __name__ == "__main__":
    asyncio.run(main())
