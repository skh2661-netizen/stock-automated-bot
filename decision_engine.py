import logging
from typing import Dict, List
from models import CandidateFeature
from strategy_engine import assign_strategies
from trade_plan import generate_trade_plan

_logger = logging.getLogger(__name__)

def evaluate_candidates(features_list: List[CandidateFeature], market_context: Dict, holdings_data: List[Dict] = None, p_state=None, is_holding_eval: bool = False, total_equity: float = 10_000_000):
    m_state = market_context.get("state", "UNKNOWN")
    holding_codes = {h["code"] for h in holdings_data} if holdings_data else set()
    
    buy_blocked = False
    block_reason = "추천 대기"
    
    if not is_holding_eval:
        if m_state in ["CRASH", "INVALID"]: 
            buy_blocked, block_reason = True, f"{m_state} 국면"
        elif p_state and not p_state.get("allow_new_buy", True): 
            buy_blocked, block_reason = True, "계좌 위험"
        elif len(holding_codes) >= 5: 
            buy_blocked, block_reason = True, "슬롯 소진"

    final_results = []
    
    for cf in features_list:
        if not is_holding_eval and cf.code in holding_codes: continue
        
        strats, strat_score = assign_strategies(cf)
        plan = generate_trade_plan(cf, strats, total_equity=total_equity)
        
        # 필터 1: 상승 제한 (너무 높은 추격매수 차단)
        atr_pct = (cf.vty.atr_14 / cf.price * 100) if cf.price > 0 else 0
        chg_limit = max(6.0, atr_pct * 2.5)
        if not is_holding_eval and (cf.chg >= chg_limit or cf.price >= plan["target1"]): continue
        
        # 필터 2: 하방 제한 (-8% 이상 급락 종목은 '과대낙폭반등' 전략이 아니면 즉시 차단)
        if not is_holding_eval and cf.chg < -8.0 and "과대낙폭반등" not in strats: continue

        # =========================================================
        # 👑 Multi-Factor Scoring System 보강
        # =========================================================
        raw_score = strat_score  
        
        # 1. Volume & Money Flow Factor
        if cf.vol.vr_20 >= 3.0: raw_score += 15
        elif cf.vol.vr_20 >= 2.0: raw_score += 10
        elif cf.vol.vr_20 >= 1.2: raw_score += 5
        
        if cf.vol.relative_vol_today >= 2.0: raw_score += 10
        elif cf.vol.relative_vol_today >= 1.0: raw_score += 5
        
        if cf.vol.money_flow_ratio >= 60.0: raw_score += 5
        
        # 2. True RS Factor (상대강도)
        if cf.mom.true_rs_composite >= 20.0: raw_score += 25
        elif cf.mom.true_rs_composite >= 10.0: raw_score += 15
        elif cf.mom.true_rs_composite >= 0.0: raw_score += 5
        
        # 3. Structure & Trend Factor
        if cf.mom.is_trend_up: raw_score += 5
        
        abs_gap = abs(cf.struc.dist_ma20)
        if abs_gap <= 3.0: raw_score += 5
        elif abs_gap <= 8.0: raw_score += 3
        
        if cf.struc.dist_52w_high > -10.0: raw_score += 5
        
        # 4. Pattern & Volatility Factor
        if cf.vty.atr_compression: raw_score += 5
        if cf.pat.is_hammer: raw_score += 5
        if cf.pat.is_bull_engulfing: raw_score += 5
        if cf.pat.is_gap_up and cf.pat.gap_survived: raw_score += 5

        # =========================================================
        # 👑 Market Multiplier 적용
        # =========================================================
        multiplier = 1.0
        if m_state == "CAUTION": multiplier = 0.8
        elif m_state == "WEAK": multiplier = 0.6
        elif m_state in ["CRASH", "INVALID"]: multiplier = 0.3
        
        adj_score = round(raw_score * multiplier, 1)
        level = "LEVEL 3" if adj_score >= 60 else ("LEVEL 2" if adj_score >= 40 else "LEVEL 1")
        
        final_results.append({
            "code": cf.code, 
            "name": cf.name, 
            "price": cf.price, 
            "chg": cf.chg,
            "ma20_gap": round(cf.struc.dist_ma20, 2),  # [확실한 패치] formatter 에러 방지용 키 주입
            "plan": plan, 
            "strategies": strats,
            "decision": {
                "level": level,
                "raw_score": raw_score,
                "adj_score": adj_score,
                "true_rs": round(cf.mom.true_rs_composite, 2),
                "multiplier": multiplier
            }
        })
        
    final_results.sort(key=lambda x: x["decision"]["adj_score"], reverse=True)
    alert_cands = [r for r in final_results if r["decision"]["level"] == "LEVEL 3"] if not buy_blocked else []
    
    return {
        "market": market_context, 
        "candidates": final_results, 
        "alert_candidates": alert_cands, 
        "buy_blocked": buy_blocked, 
        "block_reason": block_reason
    }
