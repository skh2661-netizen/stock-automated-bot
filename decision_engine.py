from models import CandidateFeature
from strategy_engine import assign_strategies
from trade_plan import generate_trade_plan
import logging

def evaluate_candidates(features_list: list[CandidateFeature], market_context: dict, holdings_data: list = None, p_state = None, is_holding_eval: bool = False):
    m_state = market_context.get("state", "UNKNOWN")
    holding_codes = {h.code for h in holdings_data} if holdings_data else set()
    
    buy_blocked = False
    block_reason = ""
    
    # 디버깅용 컷오프 트래커
    dec_stats = {"total_in": len(features_list), "holding_drop": 0, "atr_drop": 0, "ma20_drop": 0, "levels": {"LEVEL 4": 0, "LEVEL 3": 0, "LEVEL 2": 0, "LEVEL 1": 0}}
    
    if not is_holding_eval:
        if m_state == "CRASH": buy_blocked, block_reason = True, "CRASH 국면"
        elif p_state and not p_state.allow_new_buy: buy_blocked, block_reason = True, "계좌 위험"
        elif len(holding_codes) >= 5: buy_blocked, block_reason = True, "슬롯 소진"

    final_results = []
    
    for cf in features_list:
        if not is_holding_eval and cf.code in holding_codes:
            dec_stats["holding_drop"] += 1
            continue

        cf.mom.rs_20d = min(max(cf.mom.rs_20d, -50), 100)
        plan = generate_trade_plan(cf)
        
        atr_pct = (cf.vty.atr_14 / cf.price * 100) if cf.price > 0 else 0
        chg_limit = max(6.0, atr_pct * 2.5)
        
        if not is_holding_eval and (cf.chg >= chg_limit or cf.price >= plan["target1"]):
            dec_stats["atr_drop"] += 1
            continue
            
        is_ma20_far = (cf.price / cf.mom.ma_20 - 1)*100 > 15.0 if cf.mom.ma_20 > 0 else False
        if not is_holding_eval and is_ma20_far:
            dec_stats["ma20_drop"] += 1
            continue

        trade_score = min((cf.vol.vr_20 * 15) + (cf.vol.money_flow_ratio * 10), 100)
        confidence = min(round((trade_score * 0.6) + 25, 1), 100)
        rs_component = min(max(cf.mom.rs_20d, 0), 100)
        
        risk = max(plan["entry"] - plan["stop_loss"], 1)
        reward = max(plan["target1"] - plan["entry"], 1)
        rr_score = min(round(reward / risk, 2) * 20, 100)
        
        composite_rank = round((confidence * 0.5) + (rs_component * 0.3) + (rr_score * 0.2), 2)
        primary, secondary = assign_strategies(cf)
        
        if cf.mom.rs_20d >= 20 and confidence >= 65: lvl = "LEVEL 4"
        elif cf.mom.rs_20d >= 5 and confidence >= 50: lvl = "LEVEL 3"
        elif confidence >= 40: lvl = "LEVEL 2"
        else: lvl = "LEVEL 1"
        
        dec_stats["levels"][lvl] += 1
            
        final_results.append({
            "code": cf.code, "name": cf.name, "price": cf.price, "chg": cf.chg,
            "decision": {
                "level": lvl, "confidence": confidence, "composite_rank": composite_rank,
                "primary_strategy": primary, "secondary_strategy": secondary, "trade_plan": plan,
                "rs_20d": cf.mom.rs_20d, "atr": cf.vty.atr_14
            }
        })
        
    final_results.sort(key=lambda x: x["decision"]["composite_rank"], reverse=True)
    alert_candidates = [r for r in final_results if r["decision"]["level"] in ["LEVEL 3", "LEVEL 4"]]
    
    return {
        "market": market_context, "candidates": final_results, 
        "alert_candidates": alert_candidates, 
        "buy_blocked": buy_blocked, "block_reason": block_reason, "dec_stats": dec_stats
    }
