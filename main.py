import asyncio
import logging
import os
import subprocess

from market_check import get_market_context
from portfolio_manager import load_holdings, assess_portfolio_health
from scanner import fetch_history, fetch_raw_candidates
from feature_factory import build_features
from decision_engine import evaluate_candidates
from telegram_bot import format_scan_messages, send_message

def commit_holdings_to_git():
    logging.info("Attempting to auto-commit holdings.json to GitHub repository...")
    try:
        subprocess.run(['git', 'config', '--global', 'user.name', 'github-actions[bot]'], check=False)
        subprocess.run(['git', 'config', '--global', 'user.email', 'github-actions[bot]@users.noreply.github.com'], check=False)
        subprocess.run(['git', 'add', 'holdings.json'], check=False)
        
        diff = subprocess.run(['git', 'diff', '--staged', '--quiet'], check=False)
        if diff.returncode == 1: 
            subprocess.run(['git', 'commit', '-m', '[Auto] Update holdings.json state'], check=False)
            subprocess.run(['git', 'push'], check=False)
            logging.info("Successfully pushed holdings.json to repository.")
        else:
            logging.info("No changes in holdings.json to commit. Skipping push.")
    except Exception as e:
        logging.error(f"Failed to auto-commit: {e}")

async def main():
    market_context = get_market_context()
    holdings = load_holdings()
    
    logging.info(f"[Portfolio I/O] Path: holdings.json | Exists: {os.path.exists('holdings.json')} | Count: {len(holdings)}")
    if holdings:
        logging.info(f"Loaded Codes : {[h.code for h in holdings]}")
    
    if holdings:
        holdings_raw = []
        for h in holdings:
            try:
                hist = fetch_history(h.code)
                if hist is not None and not hist.empty:
                    holdings_raw.append({'code': h.code, 'name': h.name, 'data': hist})
            except Exception as e:
                logging.warning(f"Failed to fetch history for holding {h.code}: {e}")
        
        if holdings_raw:
            holdings_features = build_features(holdings_raw, market_context)
            holdings_eval = evaluate_candidates(holdings_features, market_context, holdings_data=None, is_holding_eval=True)
            # 👑 인터페이스 교정: 보유 종목 원본 객체(holdings)와 평가 결과(holdings_eval)를 동시 주입
            p_state = assess_portfolio_health(holdings, holdings_eval['candidates'])
        else:
            p_state = assess_portfolio_health(holdings, [])
    else:
        p_state = assess_portfolio_health([], [])
        
    raw_data = fetch_raw_candidates()
    features_list = build_features(raw_data, market_context)
    
    final_results = evaluate_candidates(
        features_list=features_list, 
        market_context=market_context, 
        holdings_data=holdings, 
        p_state=p_state,
        is_holding_eval=False
    )
    
    messages = format_scan_messages(final_results, holdings_data=holdings, p_state=p_state)
    for msg in messages:
        await send_message(msg)
        
    commit_holdings_to_git()
        
if __name__ == "__main__":
    asyncio.run(main())
