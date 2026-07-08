# main.py
import asyncio
import decision_engine
import portfolio_manager
from market_check import get_market_context
from scanner import fetch_history, fetch_raw_candidates
from feature_factory import build_features
from decision_engine import evaluate_candidates
from telegram_bot import send_message, format_scan_messages
import datetime
import pytz

async def main():
    print("🚀 V9.0 Phase 3 Pipeline 가동 (Portfolio Manager 연동)...")
    
    # 1. 시장 국면 추출
    market_context = get_market_context()
    
    # 2. 보유 종목 로드 및 실시간 동적 재평가
    holdings = portfolio_manager.load_holdings()
    holdings_eval = []
    p_state = portfolio_manager.PortfolioState(75.0, "NORMAL", True, True, True, False, False)
    
    if holdings:
        print(f"\n💼 [보유 종목 재평가 진행: {len(holdings)}종목]")
        kst = pytz.timezone("Asia/Seoul")
        start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=180)).strftime("%Y-%m-%d")
        
        raw_holdings_data = []
        for h in holdings:
            code, hist = fetch_history(h.code, start_date)
            if hist is not None and not hist.empty:
                chg = round(((hist['Close'].iloc[-1] / hist['Close'].iloc[-2]) - 1) * 100, 2)
                raw_holdings_data.append({"code": h.code, "name": h.name, "chg": chg, "hist": hist})
        
        if raw_holdings_data:
            holdings_features = build_features(raw_holdings_data, market_context)
            holdings_eval = evaluate_candidates(holdings_features, market_context)["candidates"]
            
            # ✅ [교정] 형님 지시사항 ③: 실제 연산된 자산 점수로 계좌 건강도(PHS) 동적 도출
            p_state = portfolio_manager.calculate_portfolio_health(holdings_eval, market_context)
            print(f"📊 [계좌 관제 결과] PHS Score: {p_state.phs_score}점 | 운영 상태: {p_state.tier}")
            
            db_update_needed = False
            
            # Time Stop 리스크 감시 및 초기 제로값 복구
            for h_eval in holdings_eval:
                match_h = next((x for x in holdings if x.code == h_eval["code"]), None)
                if match_h:
                    # ✅ [교정] 형님 지시사항 ②: 최초 기동 시 데이터가 0이면 오늘의 실시간 퀀트 점수로 기록 보존
                    if match_h.entry_confidence == 0.0 or match_h.entry_composite == 0.0:
                        match_h.entry_confidence = h_eval["decision"]["confidence"]
                        match_h.entry_composite = h_eval["decision"]["composite_rank"]
                        match_h.entry_level = h_eval["decision"]["level"]
                        db_update_needed = True
                        print(f"⚙️ [{match_h.name}] 초기 진입 스코어 동적 각인 완료 ({match_h.entry_confidence}점)")
                    
                    # ✅ [교정] 형님 지시사항 ③: 하드코딩된 "NORMAL"을 적출하고 동적 도출된 p_state.tier를 완벽 결속
                    is_stop = portfolio_manager.evaluate_time_stop(
                        match_h, h_eval["decision"], market_context["state"], p_state.tier
                    )
                    status = "🚨 TIME STOP (청산 권고)" if is_stop else "🟢 HOLD (순항 중)"
                    print(f"[{match_h.name}] 진입점수: {match_h.entry_confidence} | 현재점수: {h_eval['decision']['confidence']} -> {status}")
            
            if db_update_needed:
                portfolio_manager.save_holdings(holdings)

    # 3. 신규 종목 스캔
    print("\n🔍 [신규 종목 스캐너 가동]")
    raw_data = fetch_raw_candidates()
    if raw_data:
        features_list = build_features(raw_data, market_context)
        final_results = evaluate_candidates(features_list, market_context)
        
        # 텔레그램 리포트에 교차 분석된 보유 종목 데이터 전달
        messages = format_scan_messages(final_results, holdings_data=holdings_eval)
        for msg in messages:
            await send_message(msg)
            
    print(f"✅ V9.0 파이프라인 완결.")

if __name__ == "__main__":
    asyncio.run(main())
