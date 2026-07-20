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
    level_counts = {"LEVEL 3": 0, "LEVEL 2": 0, "LEVEL 1": 0, "GATED": 0}
    
    for cf in features_list:
        if not is_holding_eval and cf.code in holding_codes: continue
        
        strats, strat_score = assign_strategies(cf)
        plan = generate_trade_plan(cf, strats, total_equity=total_equity)
        
        atr_pct = (cf.vty.atr_14 / cf.price * 100) if cf.price > 0 else 0
        chg_limit = max(6.0, atr_pct * 2.5)
        if not is_holding_eval and (cf.chg >= chg_limit or cf.price >= plan["target1"]): continue
        if not is_holding_eval and cf.chg < -8.0 and "과대낙폭반등" not in strats: continue

        # =========================================================
        # ⭐ Final Buy Gate (실전 매매 필수 가이드 검증)
        # =========================================================
        if not is_holding_eval:
            # 1. R:R (손익비) 1.2 미만은 아무리 좋아도 진입 불가 (이제 저항선 기준으로 정상 연산됨)
            if plan["rr_ratio"] != -1.0 and plan["rr_ratio"] < 1.2:
                level_counts["GATED"] += 1
                continue
                
            # 2. 20일선 이격도 12% 이상 초과 급등 추격 금지
            if cf.struc.dist_ma20 > 12.0:
                level_counts["GATED"] += 1
                continue
                
            # 3. 평균 거래대금 100억 미만 소외주 금지 (이제 20일 평균 기준이라 작전주 걸러냄)
            if cf.vol.trading_value_100m < 100.0:
                level_counts["GATED"] += 1
                continue
                
            # 4. 강한 매도세를 뜻하는 장대 윗꼬리 캔들 제외 (고가 대비 밀린 폭 기준)
            if cf.pat.has_long_upper_shadow:
                level_counts["GATED"] += 1
                continue

        # =========================================================
        # 👑 Multi-Factor Scoring System
        # =========================================================
        raw_score = strat_score  
        
        # 1. Trading Value Factor (이제 20일 평균 기준이므로 더욱 견고함)
        if cf.vol.trading_value_100m >= 3000: raw_score += 15
        elif cf.vol.trading_value_100m >= 1000: raw_score += 10
        elif cf.vol.trading_value_100m >= 300: raw_score += 5
        
        # 2. Volume & Money Flow Factor
        if cf.vol.vr_20 >= 3.0: raw_score += 15
        elif cf.vol.vr_20 >= 2.0: raw_score += 10
        elif cf.vol.vr_20 >= 1.2: raw_score += 5
        
        if cf.vol.relative_vol_today >= 2.0: raw_score += 10
        elif cf.vol.relative_vol_today >= 1.0: raw_score += 5
        
        if cf.vol.money_flow_ratio >= 60.0: raw_score += 5
        
        # 3. True RS Factor
        if cf.mom.true_rs_composite >= 20.0: raw_score += 20
        elif cf.mom.true_rs_composite >= 10.0: raw_score += 10
        elif cf.mom.true_rs_composite >= 0.0: raw_score += 5
        
        # 4. Structure & Trend Factor
        if cf.mom.is_trend_up: raw_score += 5
        abs_gap = abs(cf.struc.dist_ma20)
        if abs_gap <= 3.0: raw_score += 5
        elif abs_gap <= 8.0: raw_score += 3
        
        if cf.struc.dist_52w_high > -10.0: raw_score += 5
        
        # 5. Pattern & Volatility Factor
        if cf.vty.atr_compression: raw_score += 5
        if cf.pat.is_hammer: raw_score += 5
        if cf.pat.is_bull_engulfing: raw_score += 5
        if cf.pat.is_gap_up and cf.pat.gap_survived: raw_score += 5

        if cf.struc.high_stay_days >= 10: raw_score += 5
        elif cf.struc.high_stay_days >= 5: raw_score += 3

        # =========================================================
        # 👑 Market Multiplier
        # =========================================================
        multiplier = 1.0
        if m_state == "CAUTION": multiplier = 0.8
        elif m_state == "WEAK": multiplier = 0.6
        # [수정] CRASH는 어차피 BUY BLOCK이므로 불필요한 연산 제거
        
        adj_score = round(raw_score * multiplier, 1)
        level = "LEVEL 3" if adj_score >= 60 else ("LEVEL 2" if adj_score >= 40 else "LEVEL 1")
        
        level_counts[level] += 1
        
        final_results.append({
            "code": cf.code, 
            "name": cf.name, 
            "price": cf.price, 
            "chg": cf.chg,
            "ma20_gap": round(cf.struc.dist_ma20, 2),
            "trading_value": round(cf.vol.trading_value_100m, 1),
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
        "block_reason": block_reason,
        "level_counts": level_counts
    }
