from models import CandidateFeature
from strategy_engine import assign_strategies
from trade_plan import generate_trade_plan
import logging

def evaluate_candidates(features_list: list[CandidateFeature], market_context: dict, holdings_data: list = None, p_state = None, is_holding_eval: bool = False):
    m_state = market_context.get("state", "UNKNOWN")
    holding_codes = {h.code for h in holdings_data} if holdings_data else set()
    
    buy_blocked = False
    
    if not is_holding_eval:
        if m_state == "CRASH": buy_blocked = True
        elif p_state and not p_state.allow_new_buy: buy_blocked = True
        elif len(holding_codes) >= 5: buy_blocked = True

    final_results = []
    
    for cf in features_list:
        if not is_holding_eval and cf.code in holding_codes:
            continue

        cf.mom.rs_20d = min(max(cf.mom.rs_20d, -50), 100)
        plan = generate_trade_plan(cf)
        
        atr_pct = (cf.vty.atr_14 / cf.price * 100) if cf.price > 0 else 0
        
        # 👑 심화 Actionable Filter (추격 매수 5중 필터)
        is_chg_over = cf.chg >= max(6.0, atr_pct * 2.5)
        is_target_hit = cf.price >= plan["target1"]
        is_gap_over = (cf.price / cf.struc.prev_pivot_high_price - 1)*100 > 5.0 if cf.struc.prev_pivot_high_price > 0 else False
        is_ma20_far = (cf.price / cf.mom.ma_20 - 1)*100 > 15.0 if cf.mom.ma_20 > 0 else False
        
        if not is_holding_eval and (is_chg_over or is_target_hit or is_gap_over or is_ma20_far):
            continue

        trade_score = min((cf.vol.vr_20 * 15) + (cf.vol.money_flow_ratio * 10), 100)
        pat_bonus = 0
        if cf.struc.last_pivot_low_price > cf.struc.prev_pivot_low_price and cf.struc.last_pivot_low_price > 0: pat_bonus += 10
        if cf.pat.gap_survived: pat_bonus += 10
        
        confidence = min(round((trade_score * 0.6) + (pat_bonus * 0.3) + 20, 1), 100)
        rs_component = min(max(cf.mom.rs_20d, 0), 100)
        
        risk = max(plan["entry"] - plan["stop_loss"], 1)
        reward = max(plan["target1"] - plan["entry"], 1)
        rr_score = min(round(reward / risk, 2) * 20, 100)
        
        composite_rank = round((confidence * 0.5) + (rs_component * 0.3) + (rr_score * 0.2), 2)
        primary, secondary = assign_strategies(cf)
        
        if m_state in ["RISK", "CAUTION", "CRASH"]:
            if cf.mom.rs_20d >= 30 and confidence >= 80: lvl = "LEVEL 4"
            elif cf.mom.rs_20d >= 15 and confidence >= 65: lvl = "LEVEL 3"
            elif confidence >= 45: lvl = "LEVEL 2"
            else: lvl = "LEVEL 1"
        else:
            if cf.mom.rs_20d >= 25 and confidence >= 75: lvl = "LEVEL 4"
            elif cf.mom.rs_20d >= 10 and confidence >= 60: lvl = "LEVEL 3"
            elif confidence >= 40: lvl = "LEVEL 2"
            else: lvl = "LEVEL 1"
            
        final_results.append({
            "code": cf.code, "name": cf.name, "price": cf.price, "chg": cf.chg,
            "decision": {
                "level": lvl, "confidence": confidence, "composite_rank": composite_rank,
                "primary_strategy": primary, "secondary_strategy": secondary, "trade_plan": plan,
                "rr_ratio": round(reward / risk, 2), "atr": cf.vty.atr_14, "rs_20d": cf.mom.rs_20d
            }
        })
        
    final_results.sort(key=lambda x: (x["decision"]["level"], x["decision"]["composite_rank"]), reverse=True)
    alert_candidates = [r for r in final_results if r["decision"]["level"] in ["LEVEL 3", "LEVEL 4"]]
    
    return {
        "market": market_context, "candidates": final_results, 
        "alert_candidates": alert_candidates, "buy_blocked": buy_blocked
    }
