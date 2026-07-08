from models import CandidateFeature
from strategy_engine import assign_strategies
from trade_plan import generate_trade_plan

def evaluate_candidates(features_list: list[CandidateFeature], market_context: dict):
    final_results = []
    m_state = market_context["state"]
    breadth = market_context["breadth"]
    
    # ✅ 형님 지시사항: Decision Engine 유입 직후 전달받은 시장 상태 출력
    print("=" * 60)
    print("MARKET STATE (Engine) :", m_state)
    print("BREADTH (Engine)      :", breadth)
    print("=" * 60)
    
    for cf in features_list:
        trade_score = min((cf.mom.rs_20d * 1.5) + (cf.vol.vr_20 * 10) + (cf.vol.money_flow_ratio * 5), 100)
        
        pat_bonus = 0
        if cf.struc.last_pivot_low_price > cf.struc.prev_pivot_low_price and cf.struc.last_pivot_low_price > 0: pat_bonus += 10
        if cf.pat.gap_survived: pat_bonus += 10
        if cf.pat.is_bull_engulfing or cf.pat.is_hammer: pat_bonus += 5
        
        breadth_bonus = 10 if breadth.get("trend") == "Improving" else (-10 if breadth.get("trend") == "Weakening" else 0)
        
        confidence = round((trade_score * 0.4) + (pat_bonus * 0.2) + (breadth_bonus * 0.1) + 30, 1) 
        
        primary, secondary = assign_strategies(cf)
        plan = generate_trade_plan(cf)
        
        if m_state == "CRASH":
            if cf.mom.rs_20d >= 35 and confidence >= 75: lvl = "LEVEL 3"
            elif cf.mom.rs_20d >= 20 and confidence >= 60: lvl = "LEVEL 2"
            else: lvl = "LEVEL 0"
        else:
            if confidence >= 80: lvl = "LEVEL 4"
            elif confidence >= 65: lvl = "LEVEL 3"
            elif confidence >= 50: lvl = "LEVEL 2"
            else: lvl = "LEVEL 1"
            
        final_results.append({
            "code": cf.code, "name": cf.name, "price": cf.price, "chg": cf.chg,
            "decision": {
                "level": lvl, "confidence": confidence, "trade_score": round(trade_score, 1),
                "primary_strategy": primary, "secondary_strategy": secondary, "trade_plan": plan
            },
            "raw_features": cf
        })
        
    final_results.sort(key=lambda x: x["decision"]["confidence"], reverse=True)
    
    alert_candidates = []
    for res in final_results:
        lvl = res["decision"]["level"]
        conf = res["decision"]["confidence"]
        rs = res["raw_features"].mom.rs_20d
        
        if m_state == "CRASH":
            if lvl in ["LEVEL 3", "LEVEL 4"]: alert_candidates.append(res)
        else:
            if lvl in ["LEVEL 3", "LEVEL 4"]: alert_candidates.append(res)
            elif lvl == "LEVEL 2" and conf >= 55 and rs >= 15: alert_candidates.append(res)
            
    print("=" * 60)
    print(f"분석종목 : {len(final_results)}")
    print(f"발송종목 : {len(alert_candidates)}")

    for r in final_results[:10]:
        print(
            f"{r['name']:<10}",
            f"{r['decision']['trade_score']:<6}",
            f"{r['decision']['confidence']:<6}",
            f"{r['decision']['level']:<8}",
            f"{r['raw_features'].mom.rs_20d:<6}"
        )
    print("=" * 60)
            
    return {"market": market_context, "candidates": final_results, "alert_candidates": alert_candidates}
