import asyncio
import logging
import os
import time
import math

from market_check import get_market_context
from portfolio_manager import load_holdings, assess_portfolio_health
from scanner import fetch_history, fetch_raw_candidates
from feature_factory import build_features
from decision_engine import evaluate_candidates
from telegram_bot import format_scan_messages, send_message

async def main():
    pipe_stats = {"krx":0, "filter":0, "pool":0, "hist_ok":0, "hist_fail":0, "feat_ok":0, "feat_fail":0, "decision":0, "alert":0}
    
    # 1. Market Service
    market = get_market_context()
    
    # 2. Portfolio Service
    holdings = load_holdings()
    if holdings:
        holdings_raw = []
        for h in holdings:
            hist = fetch_history(h.code)
            if hist is not None and not hist.empty: 
                holdings_raw.append({'code': h.code, 'name': h.name, 'hist': hist, 'chg': 0.0})
        if holdings_raw:
            holdings_features = build_features(holdings_raw, market)
            holdings_eval = evaluate_candidates(holdings_features, market, holdings_data=None, is_holding_eval=True)
            p_state = assess_portfolio_health(holdings, holdings_eval['candidates'])
        else: p_state = assess_portfolio_health(holdings, [])
    else: p_state = assess_portfolio_health([], [])
        
    # 3. Scanner Service
    raw_data, scan_stats = fetch_raw_candidates()
    pipe_stats["krx"] = scan_stats.get("krx_total", 0)
    pipe_stats["filter"] = scan_stats.get("filter_pass", 0)
    pipe_stats["pool"] = scan_stats.get("pool_pass", 0)
    
    # 4. History Fetch
    raw_with_hist = []
    for item in raw_data:
        hist = fetch_history(item['Code'])
        if hist is not None and not hist.empty and len(hist) > 20: 
            raw_with_hist.append({'code': item['Code'], 'name': item['Name'], 'hist': hist, 'chg': item['ChangesRatio']})
            pipe_stats["hist_ok"] += 1
        else:
            pipe_stats["hist_fail"] += 1
            
    # 5. Feature Extraction
    features_list = build_features(raw_with_hist, market) if raw_with_hist else []
    clean_features = []
    for f in features_list:
        if not (math.isnan(getattr(f.mom, 'rs_20d', float('nan'))) or math.isnan(getattr(f.vty, 'atr_14', float('nan')))):
            clean_features.append(f)
            pipe_stats["feat_ok"] += 1
        else:
            pipe_stats["feat_fail"] += 1
            
    # 6. Decision Engine
    final_results = evaluate_candidates(clean_features, market, holdings, p_state, is_holding_eval=False)
    pipe_stats["decision"] = len(final_results["candidates"])
    pipe_stats["alert"] = len(final_results["alert_candidates"])
    
    # 7. Telegram Dispatch
    messages = format_scan_messages(final_results, holdings, p_state, pipe_stats)
    for msg in messages:
        await send_message(msg)
        
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
