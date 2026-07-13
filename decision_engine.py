from models import CandidateFeature
from strategy_engine import assign_strategies
from trade_plan import generate_trade_plan
import logging

def evaluate_candidates(features_list: list[CandidateFeature], market_context: dict, holdings_data: list = None, p_state = None, is_holding_eval: bool = False):
    m_state = market_context.get("state", "UNKNOWN")
    breadth = market_context.get("breadth", {})
    data_conf = market_context.get("data_confidence", "UNKNOWN")
    
    used_slots = len(holdings_data) if holdings_data else 0
    slot_full = used_slots >= 5
    
    holding_codes = {h.code for h in holdings_data} if holdings_data else set()
    
    buy_blocked = False
    block_reason = ""
    
    if not is_holding_eval:
        if m_state == "CRASH":
            buy_blocked = True
            block_reason = "CRASH 상태 - 매수 금지 (관찰 전용)"
        elif p_state and not p_state.allow_new_buy:
            buy_blocked = True
            block_reason = f"계좌 건강도 경고 ({p_state.tier}) - 매수 금지 (관찰 전용)"
        elif slot_full:
            buy_blocked = True
            block_reason = "슬롯 100% 소진 - 신규 매수 차단 (관찰 전용)"

    final_results = []
    filtered_by_actionable = 0
    filtered_by_holding = 0
    
    for cf in features_list:
        # 👑 중복 편입(와이씨 재추천 등) 원천 차단
        if not is_holding_eval and cf.code in holding_codes:
            filtered_by_holding += 1
            continue

        cf.mom.rs_20d = min(max(cf.mom.rs_20d, -50), 100)
        plan = generate_trade_plan(cf)
        
        # 👑 초저변동 종목 억울한 탈락 방지 (최소 6.0% 확보)
        atr_percent = (cf.vty.atr_14 / cf.price * 100) if cf.price > 0 else 0
        chg_limit = max(6.0, atr_percent * 2.5) if cf.price > 0 else 9.0
        
        if not is_holding_eval and (cf.chg >= chg_limit or cf.price >= plan["target1"]):
            filtered_by_actionable += 1
            continue

        trade_score = min((cf.vol.vr_20 * 15) + (cf.vol.money_flow_ratio * 10), 100)
        pat_bonus = 0
        if cf.struc.last_pivot_low_price > cf.struc.prev_pivot_low_price and cf.struc.last_pivot_low_price > 0: pat_bonus += 10
        if cf.pat.gap_survived: pat_bonus += 10
        if cf.pat.is_bull_engulfing or cf.pat.is_hammer: pat_bonus += 5
        
        if breadth.get("trend") == "Unknown": breadth_bonus = 0
        else: breadth_bonus = 10 if breadth.get("trend") == "Improving" else (-10 if breadth.get("trend") == "Weakening" else 0)
        
        confidence = min(round((trade_score * 0.6) + (pat_bonus * 0.3) + (breadth_bonus * 0.1) + 20, 1), 100)
        rs_component = min(max(cf.mom.rs_20d, 0), 100)
        
        risk = max(plan["entry"] - plan["stop_loss"], 1)
        reward = max(plan["target1"] - plan["entry"], 1)
        rr_ratio = round(reward / risk, 2)
        rr_score = min(rr_ratio * 20, 100)
        
        # 👑 시장 국면 및 신뢰도 기반 동적 밸런싱
        if m_state == "BULL":
            composite_rank = round((confidence * 0.4) + (rs_component * 0.4) + (rr_score * 0.2), 2)
        elif m_state == "CRASH":
            composite_rank = round((confidence * 0.4) + (rs_component * 0.2) + (rr_score * 0.4), 2)
        elif data_conf == "LOW (All Failed)":
            composite_rank = round((confidence * 0.6) + (rs_component * 0.2) + (rr_score * 0.2), 2)
        else:
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
                "rr_ratio": rr_ratio, "atr": cf.vty.atr_14
            },
            "raw_features": cf
        })
        
    level_map = {"LEVEL 4": 4, "LEVEL 3": 3, "LEVEL 2": 2, "LEVEL 1": 1, "LEVEL 0": 0}
    final_results.sort(key=lambda x: (level_map.get(x["decision"]["level"], 0), x["decision"]["composite_rank"]), reverse=True)
    
    if not is_holding_eval:
        logging.info(f"Engine Excluded -> Holding Match: {filtered_by_holding} | Actionable Filter: {filtered_by_actionable}")
        logging.info(f"Engine Final Leaders: {len(final_results)}")
        if final_results:
            top = final_results[0]
            logging.info(f"Prime Leader : {top['name']} (Score: {top['decision']['composite_rank']})")
    
    alert_candidates = [r for r in final_results if r["decision"]["level"] in ["LEVEL 3", "LEVEL 4"]]
    
    return {
        "market": market_context, 
        "candidates": final_results, 
        "alert_candidates": alert_candidates, 
        "buy_blocked": buy_blocked, 
        "block_reason": block_reason
    }
