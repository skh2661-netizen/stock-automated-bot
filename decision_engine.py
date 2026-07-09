from models import CandidateFeature
from strategy_engine import assign_strategies
from trade_plan import generate_trade_plan

def evaluate_candidates(features_list: list[CandidateFeature], market_context: dict):
    final_results = []
    m_state = market_context["state"]
    breadth = market_context["breadth"]
    
    for cf in features_list:
        cf.mom.rs_20d = min(max(cf.mom.rs_20d, -50), 100)
        
        trade_score = min((cf.vol.vr_20 * 15) + (cf.vol.money_flow_ratio * 10), 100)
        
        pat_bonus = 0
        if cf.struc.last_pivot_low_price > cf.struc.prev_pivot_low_price and cf.struc.last_pivot_low_price > 0: pat_bonus += 10
        if cf.pat.gap_survived: pat_bonus += 10
        if cf.pat.is_bull_engulfing or cf.pat.is_hammer: pat_bonus += 5
        
        if breadth.get("trend") == "Unknown":
            breadth_bonus = 0
        else:
            breadth_bonus = 10 if breadth.get("trend") == "Improving" else (-10 if breadth.get("trend") == "Weakening" else 0)
        
        confidence = round((trade_score * 0.6) + (pat_bonus * 0.3) + (breadth_bonus * 0.1) + 20, 1) 
        rs_component = min(max(cf.mom.rs_20d, 0), 100)
        composite_rank = round(confidence + (rs_component * 0.15), 2)
        
        primary, secondary = assign_strategies(cf)
        plan = generate_trade_plan(cf)
        
        if m_state == "CRASH":
            if cf.mom.rs_20d >= 10 and confidence >= 65: lvl = "LEVEL 4"
            elif cf.mom.rs_20d >= 0 and confidence >= 55: lvl = "LEVEL 3" 
            elif confidence >= 45: lvl = "LEVEL 2" 
            else: lvl = "LEVEL 0"
        else:
            if cf.mom.rs_20d >= 5 and confidence >= 70: lvl = "LEVEL 4"
            elif confidence >= 55: lvl = "LEVEL 3"
            elif confidence >= 40: lvl = "LEVEL 2"
            else: lvl = "LEVEL 1"
            
        final_results.append({
            "code": cf.code, "name": cf.name, "price": cf.price, "chg": cf.chg,
            "decision": {
                "level": lvl, "confidence": confidence, "composite_rank": composite_rank,
                "trade_score": round(trade_score, 1), "pat_bonus": pat_bonus, "breadth_bonus": breadth_bonus,
                "rs_20d": round(cf.mom.rs_20d, 2), # 텔레그램 브리핑용 직결
                "primary_strategy": primary, "secondary_strategy": secondary, "trade_plan": plan
            },
            "raw_features": cf
        })
        
    level_map = {"LEVEL 4": 4, "LEVEL 3": 3, "LEVEL 2": 2, "LEVEL 1": 1, "LEVEL 0": 0}
    final_results.sort(key=lambda x: (level_map.get(x["decision"]["level"], 0), x["decision"]["composite_rank"]), reverse=True)
    
    alert_candidates = []
    for res in final_results:
        lvl = res["decision"]["level"]
        conf = res["decision"]["confidence"]
        
        if m_state == "CRASH":
            if lvl in ["LEVEL 3", "LEVEL 4"]: alert_candidates.append(res)
        else:
            if lvl in ["LEVEL 3", "LEVEL 4"]: alert_candidates.append(res)
            elif lvl == "LEVEL 2" and conf >= 45: alert_candidates.append(res)
            
    return {"market": market_context, "candidates": final_results, "alert_candidates": alert_candidates}
