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
    pipe_stats = {"krx": "SKIP", "filter": "SKIP", "pool": "SKIP", "hist_ok": "SKIP", "hist_fail": "SKIP", "feat_ok": "SKIP", "feat_fail": "SKIP", "decision": 0, "alert": 0, "time_market": 0, "time_port": 0, "time_scan": 0, "time_hist": 0, "time_feat": 0, "time_dec": 0}
    
    # 1. Market Service
    market = get_market_context()
    t1 = time.time(); pipe_stats["time_market"] = round(t1 - t0, 1)
    
    # 2. Portfolio Service (기존 보유 종목 재평가는 시장 데이터 유효성에 관계없이 진행하여 PHS 유지)
    holdings = load_holdings()
    if holdings:
        holdings_raw = []
        for h in holdings:
            hist = fetch_history(h.code)
            if hist is not None and not hist.empty: holdings_raw.append({'code': h.code, 'name': h.name, 'hist': hist, 'chg': 0.0})
        if holdings_raw:
            holdings_features = build_features(holdings_raw, market)
            holdings_eval = evaluate_candidates(holdings_features, market, holdings_data=None, is_holding_eval=True)
            p_state = assess_portfolio_health(holdings, holdings_eval['candidates'])
        else: p_state = assess_portfolio_health(holdings, [])
    else: p_state = assess_portfolio_health([], [])
    t2 = time.time(); pipe_stats["time_port"] = round(t2 - t1, 1)
        
    # 👑 3~6. 최상위 방화벽 작동: 시장 데이터 검증 실패 시, 신규 스캐너/평가 완전 중단
    if not market.get("allow_scan", False):
        logging.warning(f"Market Validation Failed: {market.get('reason')}. Skipping Scanner and Decision Engine.")
        final_results = {
            "candidates": [], "alert_candidates": [], 
            "buy_blocked": True, "block_reason": f"시장 데이터 검증 실패 ({market.get('reason')})", 
            "dec_stats": {}
        }
        t6 = time.time()
    else:
        # 정상 시 파이프라인 관통
        raw_data, scan_stats = fetch_raw_candidates()
        pipe_stats["krx"] = scan_stats.get("krx_total", 0)
        pipe_stats["filter"] = scan_stats.get("change_pass", 0)
        pipe_stats["pool"] = scan_stats.get("final_pool", 0)
        t3 = time.time(); pipe_stats["time_scan"] = round(t3 - t2, 1)
        
        raw_with_hist = []
        pipe_stats["hist_ok"] = 0
        pipe_stats["hist_fail"] = 0
        for item in raw_data:
            hist = fetch_history(item['Code'])
            if hist is not None and len(hist) > 20: 
                raw_with_hist.append({'code': item['Code'], 'name': item['Name'], 'hist': hist, 'chg': item['ChangesRatio']})
                pipe_stats["hist_ok"] += 1
            else: pipe_stats["hist_fail"] += 1
        t4 = time.time(); pipe_stats["time_hist"] = round(t4 - t3, 1)
        
        features_list = build_features(raw_with_hist, market) if raw_with_hist else []
        clean_features = []
        pipe_stats["feat_ok"] = 0
        pipe_stats["feat_fail"] = 0
        for f in features_list:
            rs_bad, atr_bad = False, False
            try:
                if math.isnan(float(f.mom.rs_20d)): rs_bad = True
            except Exception: rs_bad = True
            try:
                if math.isnan(float(f.vty.atr_14)): atr_bad = True
            except Exception: atr_bad = True
            
            if not (rs_bad or atr_bad): 
                clean_features.append(f)
                pipe_stats["feat_ok"] += 1
            else: pipe_stats["feat_fail"] += 1
        t5 = time.time(); pipe_stats["time_feat"] = round(t5 - t4, 1)
        
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
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
