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
    t0 = time.time()
    pipe_stats = {"time_market":0, "time_port":0, "time_scan":0, "time_hist":0, "time_feat":0, "time_dec":0, "krx":0, "filter":0, "history_ok":0, "feature_ok":0, "decision":0, "alert":0}
    
    # 1. Market Service
    market = get_market_context()
    t1 = time.time(); pipe_stats["time_market"] = round(t1 - t0, 1)
    
    # 2. Portfolio Service
    holdings = load_holdings()
    if holdings:
        holdings_raw = []
        for h in holdings:
            hist = fetch_history(h.code)
            if hist is not None and not hist.empty: holdings_raw.append({'code': h.code, 'name': h.name, 'data': hist})
        if holdings_raw:
            holdings_features = build_features(holdings_raw, market)
            holdings_eval = evaluate_candidates(holdings_features, market, holdings_data=None, is_holding_eval=True)
            p_state = assess_portfolio_health(holdings, holdings_eval['candidates'])
        else: p_state = assess_portfolio_health(holdings, [])
    else: p_state = assess_portfolio_health([], [])
    t2 = time.time(); pipe_stats["time_port"] = round(t2 - t1, 1)
        
    # 3. Scanner Service
    raw_data, scan_stats = fetch_raw_candidates()
    pipe_stats["krx"] = scan_stats.get("krx_total", 0)
    pipe_stats["filter"] = scan_stats.get("change_pass", 0)
    t3 = time.time(); pipe_stats["time_scan"] = round(t3 - t2, 1)
    
    # 4. History Fetch
    raw_with_hist = []
    for item in raw_data:
        hist = fetch_history(item['Code'])
        if hist is not None and len(hist) > 20: 
            raw_with_hist.append({'code': item['Code'], 'name': item['Name'], 'data': hist, 'chg': item['ChangesRatio']})
    pipe_stats["history_ok"] = len(raw_with_hist)
    t4 = time.time(); pipe_stats["time_hist"] = round(t4 - t3, 1)
    
    # 5. Feature Extraction (NaN Diagnostics)
    features_list = build_features(raw_with_hist, market) if raw_with_hist else []
    rs_nan = sum(1 for f in features_list if math.isnan(f.mom.rs_20d))
    atr_nan = sum(1 for f in features_list if math.isnan(f.vty.atr_14))
    logging.info(f"[Diagnostics] Feature NaN Count -> RS: {rs_nan}, ATR: {atr_nan}")
    
    # Drop NaNs safely
    clean_features = [f for f in features_list if not (math.isnan(f.mom.rs_20d) or math.isnan(f.vty.atr_14))]
    pipe_stats["feature_ok"] = len(clean_features)
    t5 = time.time(); pipe_stats["time_feat"] = round(t5 - t4, 1)
    
    # 6. Decision Engine
    final_results = evaluate_candidates(clean_features, market, holdings, p_state, is_holding_eval=False)
    pipe_stats["decision"] = len(final_results["candidates"])
    pipe_stats["alert"] = len(final_results["alert_candidates"])
    t6 = time.time(); pipe_stats["time_dec"] = round(t6 - t5, 1)
    
    # 7. Telegram Formatter
    messages = format_scan_messages(final_results, holdings, p_state, pipe_stats)
    for msg in messages:
        await send_message(msg)
    
    logging.info(f"Pipeline TOTAL TIME: {round(time.time() - t0, 1)}s")
        
if __name__ == "__main__":
    asyncio.run(main())
