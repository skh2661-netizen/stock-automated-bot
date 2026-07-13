import asyncio
import logging
import os
import subprocess

# 👑 누락되었던 필수 의존성 모듈 명시적 임포트
from market_check import get_market_context
from portfolio_manager import load_holdings, assess_portfolio_health
from scanner import fetch_history, fetch_raw_candidates
from feature_factory import build_features
from decision_engine import evaluate_candidates
from telegram_bot import format_scan_messages, send_message

def commit_holdings_to_git():
    """GitHub Actions 환경의 영속성 보장을 위한 안전한 커밋 모듈"""
    logging.info("Attempting to auto-commit holdings.json to GitHub repository...")
    try:
        subprocess.run(['git', 'config', '--global', 'user.name', 'github-actions[bot]'], check=False)
        subprocess.run(['git', 'config', '--global', 'user.email', 'github-actions[bot]@users.noreply.github.com'], check=False)
        subprocess.run(['git', 'add', 'holdings.json'], check=False)
        
        # 변경 사항 유무 검사 (Exit Code 1 붕괴 방지)
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
        # 객체 속성(h.code)으로 정확히 접근
        logging.info(f"Loaded Codes : {[h.code for h in holdings]}")
    
    # 보유 종목 실시간 재평가 (과거가 아닌 현재 차트 기준 PHS 연산)
    if holdings:
        holdings_raw = []
        for h in holdings:
            try:
                hist = fetch_history(h.code) # 단일 종목 순회 방식
                if hist is not None and not hist.empty:
                    holdings_raw.append({'code': h.code, 'name': h.name, 'data': hist})
            except Exception as e:
                logging.warning(f"Failed to fetch history for holding {h.code}: {e}")
        
        if holdings_raw:
            holdings_features = build_features(holdings_raw, market_context)
            holdings_eval = evaluate_candidates(holdings_features, market_context, holdings_data=None, is_holding_eval=True)
            p_state = assess_portfolio_health(holdings_eval['candidates'])
        else:
            p_state = assess_portfolio_health([])
    else:
        p_state = assess_portfolio_health([])
        
    # 신규 스캐너 가동
    raw_data = fetch_raw_candidates()
    features_list = build_features(raw_data, market_context)
    
    # 의사결정 엔진 가동
    final_results = evaluate_candidates(
        features_list=features_list, 
        market_context=market_context, 
        holdings_data=holdings, 
        p_state=p_state,
        is_holding_eval=False
    )
    
    # 텔레그램 송출
    messages = format_scan_messages(final_results, holdings_data=holdings, p_state=p_state)
    for msg in messages:
        await send_message(msg)
        
    # 실행 종료 전 영속성 보장 (GitHub VM 초기화 방어)
    commit_holdings_to_git()
        
if __name__ == "__main__":
    asyncio.run(main())
