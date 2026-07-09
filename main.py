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
    print("🚀 V9.1 Phase 3 Pipeline 가동 (Rolling Time Stop 연동)...")
    
    market_context = get_market_context()
    holdings = portfolio_manager.load_holdings()
    holdings_eval = []
    tele_holdings = [] 
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
            
            p_state = portfolio_manager.calculate_portfolio_health(holdings_eval, market_context)
            print(f"📊 [계좌 관제 결과] PHS Score: {p_state.phs_score}점 | 운영 상태: {p_state.tier}")
            
            db_update_needed = False
            
            for h_eval in holdings_eval:
                match_h = next((x for x in holdings if x.code == h_eval["code"]), None)
                if match_h:
                    curr_conf = h_eval["decision"]["confidence"]
                    
                    # 1. 청산 판별 (오늘 데이터를 갱신하기 전의 '과거 평균'을 기준으로 대조)
                    is_stop = portfolio_manager.evaluate_time_stop(
                        match_h, h_eval["decision"], market_context["state"], p_state.tier
                    )
                    status = "청산 권고" if is_stop else "순항 중"
                    
                    past_avg = sum(match_h.conf_history)/len(match_h.conf_history) if match_h.conf_history else curr_conf
                    print(f"[{match_h.name}] 과거평균: {round(past_avg, 1)} | 오늘점수: {curr_conf} -> {status}")
                    
                    # 2. V9.1 동적 롤링: 오늘 점수 추가 후 5일 초과분 컷오프
                    match_h.conf_history.append(curr_conf)
                    if len(match_h.conf_history) > 5:
                        match_h.conf_history.pop(0)
                    db_update_needed = True
                    
                    pnl = round(((h_eval['price'] / match_h.entry_price) - 1) * 100, 2)
                    tele_holdings.append({
                        "name": match_h.name,
                        "judgment": status,
                        "pnl": pnl,
                        "stop_p": h_eval["decision"]["trade_plan"]["stop_loss"],
                        "conf": curr_conf
                    })
            
            if db_update_needed:
                portfolio_manager.save_holdings(holdings)

    print("\n🔍 [신규 종목 스캐너 가동]")
    raw_data = fetch_raw_candidates()
    if raw_data:
        features_list = build_features(raw_data, market_context)
        final_results = evaluate_candidates(features_list, market_context)
        
        messages = format_scan_messages(final_results, holdings_data=tele_holdings)
        for msg in messages:
            await send_message(msg)
            
    print(f"✅ V9.1 파이프라인 완결.")

if __name__ == "__main__":
    asyncio.run(main())
