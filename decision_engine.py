from models import CandidateFeature
from strategy_engine import assign_strategies
from trade_plan import generate_trade_plan

def evaluate_candidates(features_list: list[CandidateFeature], market_context: dict):
    final_results = []
    m_state = market_context["state"]
    breadth = market_context["breadth"]
    
    print("=" * 60)
    print("MARKET STATE (Engine) :", m_state)
    print("BREADTH (Engine)      :", breadth)
    print("=" * 60)
    
    for cf in features_list:
        # 1. Base Trade Score
        trade_score = min((cf.mom.rs_20d * 1.5) + (cf.vol.vr_20 * 10) + (cf.vol.money_flow_ratio * 5), 100)
        
        # 2. Pattern Bonus & Breadth Bonus
        pat_bonus = 0
        if cf.struc.last_pivot_low_price > cf.struc.prev_pivot_low_price and cf.struc.last_pivot_low_price > 0: pat_bonus += 10
        if cf.pat.gap_survived: pat_bonus += 10
        if cf.pat.is_bull_engulfing or cf.pat.is_hammer: pat_bonus += 5
        
        breadth_bonus = 10 if breadth.get("trend") == "Improving" else (-10 if breadth.get("trend") == "Weakening" else 0)
        
        # 3. Confidence Score
        confidence = round((trade_score * 0.4) + (pat_bonus * 0.2) + (breadth_bonus * 0.1) + 30, 1) 
        
        primary, secondary = assign_strategies(cf)
        plan = generate_trade_plan(cf)
        
        # 4. LEVEL 분류
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
                "pat_bonus": pat_bonus, "breadth_bonus": breadth_bonus, # 디버깅용 저장
                "primary_strategy": primary, "secondary_strategy": secondary, "trade_plan": plan
            },
            "raw_features": cf
        })
        
    final_results.sort(key=lambda x: x["decision"]["confidence"], reverse=True)
    
    # 5. 알림 필터
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
            
    # ✅ 형님 지시사항: Trade, Pattern, Breadth 구성 요소를 낱낱이 해부하여 출력
    print("=" * 60)
    print(f"분석종목 : {len(final_results)}")
    print(f"발송종목 : {len(alert_candidates)}")

    for r in final_results[:10]:
        dec = r["decision"]
        print(
            f"{r['name']:<8} | "
            f"Trade={dec['trade_score']:>5.1f} | "
            f"Pat={dec['pat_bonus']:>2} | "
            f"Brd={dec['breadth_bonus']:>3} | "
            f"Conf={dec['confidence']:>4.1f} | "
            f"{dec['level']:<7} | "
            f"RS20={r['raw_features'].mom.rs_20d:>6.2f}"
        )
    print("=" * 60)
            
    return {"market": market_context, "candidates": final_results, "alert_candidates": alert_candidates}
