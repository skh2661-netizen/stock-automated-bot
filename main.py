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
    runtime_stats = {"pool": 0, "final": 0, "time": 0.0}
    
    # [1] Market Service
    market = get_market_context()
    
    # [2] Portfolio Service
    holdings = load_holdings()
    
    if holdings:
        holdings_raw = []
        for h in holdings:
            hist = fetch_history(h.code)
            if hist is not None and not hist.empty:
                holdings_raw.append({'code': h.code, 'name': h.name, 'data': hist})
            else:
                logging.warning(f"Holding: {h.code} | History Fetch Failed")
                
        if holdings_raw:
            holdings_features = build_features(holdings_raw, market)
            holdings_eval = evaluate_candidates(holdings_features, market, holdings_data=None, is_holding_eval=True)
            p_state = assess_portfolio_health(holdings, holdings_eval['candidates'])
        else:
            p_state = assess_portfolio_health(holdings, [])
    else:
        p_state = assess_portfolio_health([], [])
        
    # [3] Scanner Service
    raw_data = fetch_raw_candidates()
    runtime_stats["pool"] = len(raw_data)
    features_list = build_features(raw_data, market)
    
    # [4] Decision Engine
    final_results = evaluate_candidates(
        features_list=features_list, 
        market_context=market, 
        holdings_data=holdings, 
        p_state=p_state,
        is_holding_eval=False
    )
    runtime_stats["final"] = len(final_results["alert_candidates"])
    
    # [5] Telegram Formatter
    runtime_stats["time"] = round(time.time() - start_time, 1)
    messages = format_scan_messages(final_results, holdings_data=holdings, p_state=p_state, runtime_stats=runtime_stats)
    
    for msg in messages:
        await send_message(msg)
        
    logging.info(f"Pipeline Completed in {runtime_stats['time']}s")
        
if __name__ == "__main__":
    asyncio.run(main())
