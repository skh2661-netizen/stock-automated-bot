from models import CandidateFeature
from strategy_engine import assign_strategies
from trade_plan import generate_trade_plan

def evaluate_candidates(features_list: list[CandidateFeature], market_context: dict):
    final_results = []
    m_state = market_context["state"]
    breadth = market_context["breadth"]
    
    for cf in features_list:
        cf.mom.rs_20d = min(max(cf.mom.rs_20d, -50), 100)
        
        # 1. Trade Score 산출
        trade_score = min((cf.vol.vr_20 * 15) + (cf.vol.money_flow_ratio * 10), 100)
        
        # 2. 패널티 및 보너스 통제
        pat_bonus = 0
        if cf.struc.last_pivot_low_price > cf.struc.prev_pivot_low_price and cf.struc.last_pivot_low_price > 0: pat_bonus += 10
        if cf.pat.gap_survived: pat_bonus += 10
        if cf.pat.is_bull_engulfing or cf.pat.is_hammer: pat_bonus += 5
        
        if breadth.get("trend") == "Unknown":
            breadth_bonus = 0
        else:
            breadth_bonus = 10 if breadth.get("trend") == "Improving" else (-10 if breadth.get("trend") == "Weakening" else 0)
        
        # 3. Confidence 산출
        confidence = round((trade_score * 0.6) + (pat_bonus * 0.3) + (breadth_bonus * 0.1) + 20, 1) 
        
        # 👑 형님 지시사항: Composite Rank 연산 점수 다중 팩터 분산식으로 기조 전면 변경
        rs_component = min(max(cf.mom.rs_20d, 0), 100)
        composite_rank = round(
            (0.55 * confidence) + (0.20 * trade_score) + (0.15 * rs_component) + (0.10 * pat_bonus), 2
        )
        
        primary, secondary = assign_strategies(cf)
        plan = generate_trade_plan(cf)
        
        # 매매 손익비(R:R) 및 변동성 지표(ATR) 계량 매핑
        risk = max(plan["entry"] - plan["stop_loss"], 1)
        reward = max(plan["target1"] - plan["entry"], 1)
        rr_ratio = round(reward / risk, 2)
        atr_val = cf.vty.atr_14
        
        # 👑 형님 지시사항: LEVEL 3 영역에도 철저한 RS 최소 하한 가드레일 장착
        if m_state == "CRASH":
            if cf.mom.rs_20d >= 10 and confidence >= 65: lvl = "LEVEL 4"
            elif cf.mom.rs_20d >= 0 and confidence >= 55: lvl = "LEVEL 3" 
            elif confidence >= 45: lvl = "LEVEL 2" 
            else: lvl = "LEVEL 0"
        else:
            if cf.mom.rs_20d >= 5 and confidence >= 70: lvl = "LEVEL 4"
            elif cf.mom.rs_20d >= 0 and confidence >= 55: lvl = "LEVEL 3"
            elif confidence >= 40: lvl = "LEVEL 2"
            else: lvl = "LEVEL 1"
            
        final_results.append({
            "code": cf.code, "name": cf.name, "price": cf.price, "chg": cf.chg,
            "decision": {
                "level": lvl, "confidence": confidence, "composite_rank": composite_rank,
                "trade_score": round(trade_score, 1), "pat_bonus": pat_bonus, "breadth_bonus": breadth_bonus,
                "primary_strategy": primary, "secondary_strategy": secondary, "trade_plan": plan,
                "rr_ratio": rr_ratio, "atr": atr_val
            },
            "raw_features": cf
        })
        
    # 계층형 우선 튜플 정렬 강제 집행
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
