from models import CandidateFeature
from strategy_engine import assign_strategies
from trade_plan import generate_trade_plan

def evaluate_candidates(features_list: list[CandidateFeature], market_context: dict, holdings_data: list = None):
    final_results = []
    m_state = market_context["state"]
    breadth = market_context["breadth"]
    
    # 포트폴리오 슬롯 제어 로직 (현금 비중 및 중복 진입 억제)
    used_slots = len(holdings_data) if holdings_data else 0
    slot_full = used_slots >= 5
    
    for cf in features_list:
        cf.mom.rs_20d = min(max(cf.mom.rs_20d, -50), 100)
        plan = generate_trade_plan(cf)
        
        # 1. Actionable Filter First (상한가 및 목표가 선도달 종목 영구 제명)
        if cf.chg >= 15.0 or cf.price >= plan["target1"]:
            continue

        # 2. Base Confidence 연산
        trade_score = min((cf.vol.vr_20 * 15) + (cf.vol.money_flow_ratio * 10), 100)
        pat_bonus = 0
        if cf.struc.last_pivot_low_price > cf.struc.prev_pivot_low_price and cf.struc.last_pivot_low_price > 0: pat_bonus += 10
        if cf.pat.gap_survived: pat_bonus += 10
        if cf.pat.is_bull_engulfing or cf.pat.is_hammer: pat_bonus += 5
        
        if breadth.get("trend") == "Unknown": breadth_bonus = 0
        else: breadth_bonus = 10 if breadth.get("trend") == "Improving" else (-10 if breadth.get("trend") == "Weakening" else 0)
        
        confidence = min(round((trade_score * 0.6) + (pat_bonus * 0.3) + (breadth_bonus * 0.1) + 20, 1), 100)
        
        # 3. Composite Rank 정규화 (Conf 50% + RS 30% + RR 20%)
        rs_component = min(max(cf.mom.rs_20d, 0), 100)
        risk = max(plan["entry"] - plan["stop_loss"], 1)
        reward = max(plan["target1"] - plan["entry"], 1)
        rr_ratio = round(reward / risk, 2)
        rr_score = min(rr_ratio * 20, 100)  # R:R 5.0 이상 시 만점(100) 처리
        
        composite_rank = round((confidence * 0.5) + (rs_component * 0.3) + (rr_score * 0.2), 2)
        primary, secondary = assign_strategies(cf)
        
        # 4. 엄격해진 Level 컷오프
        if m_state == "CRASH":
            if cf.mom.rs_20d >= 25 and confidence >= 75: lvl = "LEVEL 4"
            elif cf.mom.rs_20d >= 10 and confidence >= 60: lvl = "LEVEL 3" 
            elif confidence >= 45: lvl = "LEVEL 2" 
            else: lvl = "LEVEL 0"
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
                "rr_ratio": rr_ratio, "atr": cf.vty.atr_14
            },
            "raw_features": cf
        })
        
    level_map = {"LEVEL 4": 4, "LEVEL 3": 3, "LEVEL 2": 2, "LEVEL 1": 1, "LEVEL 0": 0}
    final_results.sort(key=lambda x: (level_map.get(x["decision"]["level"], 0), x["decision"]["composite_rank"]), reverse=True)
    
    # 5. 계좌 상태에 따른 Leader 차단 (슬롯 만석 시 신규 발굴 차단)
    alert_candidates = [r for r in final_results if r["decision"]["level"] in ["LEVEL 3", "LEVEL 4"]]
    if slot_full:
        alert_candidates = []  # 매수 불가 상태이므로 전량 제외

    return {"market": market_context, "candidates": final_results, "alert_candidates": alert_candidates, "slot_full": slot_full}
