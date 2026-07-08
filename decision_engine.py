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
        # 1. Base Trade Score (RS 제거, 순수 수급 추적)
        trade_score = min((cf.vol.vr_20 * 15) + (cf.vol.money_flow_ratio * 10), 100)
        
        # 2. Pattern Bonus & Breadth Bonus
        pat_bonus = 0
        if cf.struc.last_pivot_low_price > cf.struc.prev_pivot_low_price and cf.struc.last_pivot_low_price > 0: pat_bonus += 10
        if cf.pat.gap_survived: pat_bonus += 10
        if cf.pat.is_bull_engulfing or cf.pat.is_hammer: pat_bonus += 5
        
        if breadth.get("trend") == "Unknown":
            breadth_bonus = 0
        else:
            breadth_bonus = 10 if breadth.get("trend") == "Improving" else (-10 if breadth.get("trend") == "Weakening" else 0)
        
        # 3. Confidence Score (상수 낮춰 점수 분산도 극대화)
        confidence = round((trade_score * 0.5) + (pat_bonus * 0.4) + (breadth_bonus * 0.2) + 15, 1) 
        
        # 4. Composite Rank (RS 아웃라이어 상한 100 캡핑 방어 탑재)
        rs_component = min(max(cf.mom.rs_20d, 0), 100)
        composite_rank = round(confidence + (rs_component * 0.15), 2)
        
        primary, secondary = assign_strategies(cf)
        plan = generate_trade_plan(cf)
        
        # 5. LEVEL 분류 (✅ 교정완료: RS20 최소 방어선 구축)
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
                "primary_strategy": primary, "secondary_strategy": secondary, "trade_plan": plan
            },
            "raw_features": cf
        })
        
    # 복합 서열 점수 기준으로 정렬
    final_results.sort(key=lambda x: x["decision"]["composite_rank"], reverse=True)
    
    # 6. 알림 필터
    alert_candidates = []
    for res in final_results:
        lvl = res["decision"]["level"]
        conf = res["decision"]["confidence"]
        
        if m_state == "CRASH":
            if lvl in ["LEVEL 3", "LEVEL 4"]: alert_candidates.append(res)
        else:
            if lvl in ["LEVEL 3", "LEVEL 4"]: alert_candidates.append(res)
            elif lvl == "LEVEL 2" and conf >= 45: alert_candidates.append(res)
            
    # [디버그 뷰포트]
    print("=" * 95)
    print(f"\n[ALL CANDIDATES (Top 15 - sorted by Composite Rank)]")
    for r in final_results[:15]:
        dec = r["decision"]
        rs20_val = r["raw_features"].mom.rs_20d
        print(
            f"{r['name']:<8} | "
            f"Trade={dec['trade_score']:>5.1f} | "
            f"Pat={dec['pat_bonus']:>2} | "
            f"Brd={dec['breadth_bonus']:>3} | "
            f"RS20={rs20_val:>6.2f} | "
            f"Conf={dec['confidence']:>4.1f} | "
            f"Comp={dec['composite_rank']:>5.1f} | "
            f"{dec['level']:<7} | "
            f"Str={dec['primary_strategy']}"
        )

    print("\n[ALERT CANDIDATES (Telegram)]")
    if not alert_candidates:
        print("(없음)")
    for a in alert_candidates:
        dec = a["decision"]
        rs20_val = a["raw_features"].mom.rs_20d
        print(
            f"- {a['name']:<8} | "
            f"RS20={rs20_val:>6.2f} | "
            f"Conf={dec['confidence']:<4.1f} | "
            f"Comp={dec['composite_rank']:<5.1f} | "
            f"{dec['level']:<7} | "
            f"Str={dec['primary_strategy']}"
        )
    print("\n" + "=" * 95)
            
    return {"market": market_context, "candidates": final_results, "alert_candidates": alert_candidates}
