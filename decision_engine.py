from models import CandidateFeature
from strategy_engine import assign_strategies
from trade_plan import generate_trade_plan
import logging

def evaluate_candidates(features_list: list[CandidateFeature], market_context: dict, holdings_data: list = None, p_state = None, is_holding_eval: bool = False):
    m_state = market_context.get("state", "UNKNOWN")
    holding_codes = {h.code for h in holdings_data} if holdings_data else set()
    
    # 👑 논리적 상태 동기화: buy_blocked 시 block_reason은 필수
    buy_blocked = False
    block_reason = "추천 대기"
    
    if not is_holding_eval:
        if m_state == "CRASH": buy_blocked, block_reason = True, "CRASH 국면"
        elif p_state and not p_state.allow_new_buy: buy_blocked, block_reason = True, "계좌 위험"
        elif len(holding_codes) >= 5: buy_blocked, block_reason = True, "슬롯 소진"

    final_results = []
    
    for cf in features_list:
        if not is_holding_eval and cf.code in holding_codes: continue
        
        plan = generate_trade_plan(cf)
        atr_pct = (cf.vty.atr_14 / cf.price * 100) if cf.price > 0 else 0
        chg_limit = max(6.0, atr_pct * 2.5)
        
        if not is_holding_eval and (cf.chg >= chg_limit or cf.price >= plan["target1"]): continue

        confidence = min(round((cf.vol.vr_20 * 15 + 25), 1), 100)
        composite_rank = round((confidence * 0.5) + (cf.mom.rs_20d * 0.3) + 10.0, 2)
        
        final_results.append({
            "code": cf.code, "name": cf.name, "price": cf.price, "chg": cf.chg,
            "decision": {"level": "LEVEL 3" if confidence > 50 else "LEVEL 2", "composite_rank": composite_rank, "rs_20d": cf.mom.rs_20d}
        })
        
    final_results.sort(key=lambda x: x["decision"]["composite_rank"], reverse=True)
    alert_cands = [r for r in final_results if r["decision"]["level"] == "LEVEL 3"] if not buy_blocked else []
    
    return {
        "market": market_context, "candidates": final_results, 
        "alert_candidates": alert_cands, 
        "buy_blocked": buy_blocked, "block_reason": block_reason
    }
