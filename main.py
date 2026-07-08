# main.py
import asyncio
import decision_engine

# ✅ 형님 지시사항 ①: 현재 가동 중인 decision_engine.py의 실제 물리 경로 강제 출력
print("===== decision_engine FILE TRACKER =====")
print(f"PATH: {decision_engine.__file__}")
print("========================================")

from market_check import get_market_context
from scanner import fetch_raw_candidates
from feature_factory import build_features
from decision_engine import evaluate_candidates
from telegram_bot import format_scan_messages, send_message

async def main():
    print("🚀 V9.0 SRP Compliant Pipeline 가동...")
    
    # 1. 시장 국면 추출
    market_context = get_market_context()
    
    # 2. 스캐너: Raw 데이터 다운로드
    raw_data = fetch_raw_candidates()
    if not raw_data:
        print("🚨 데이터 다운로드 실패")
        return
        
    # 3. 팩토리: Feature 생성
    features_list = build_features(raw_data, market_context)
    
    # 4. 결정 엔진: 채점 및 전략 수립
    final_results = evaluate_candidates(features_list, market_context)
    
    # 5. UI 포맷팅 및 텔레그램 송출
    messages = format_scan_messages(final_results, holdings_data=None)
    for msg in messages:
        await send_message(msg)
        
    print(f"✅ V9.0 사이클 완료. ({len(features_list)} 종목 분석)")

if __name__ == "__main__":
    asyncio.run(main())
