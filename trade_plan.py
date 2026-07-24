# trade_plan.py
import numpy as np
from models import CandidateFeature, QuantConfig
from typing import Dict, Any, List, Tuple

def calculate_dynamic_sizing(entry: float, stop_distance: float, return_var_20d: float, atr_pct: float, adv_100m: float, bayesian_win_rate: float, expected_reward_rr: float, m_state: str, total_equity: float) -> Dict[str, Any]:
    ev = (bayesian_win_rate * expected_reward_rr) - ((1.0 - bayesian_win_rate) * 1.0) - QuantConfig.FEE_SLIPPAGE_COST
    
    if stop_distance <= 0 or expected_reward_rr <= 0 or ev < QuantConfig.MIN_EV_THRESHOLD: 
        return {"qty": 0, "amount": 0, "weight_pct": 0.0, "actual_risk_pct": 0.0, "ev": round(ev, 3)}
    
    # [핵심] 수익률 분산(Return Variance) 기반의 Merton-Kelly 공식 도입 (f = μ / σ²)
    # expected_return 근사치 산출 (리스크 금액 기준)
    mu = ev
    sigma_sq = return_var_20d + 1e-8 
    
    merton_kelly = mu / sigma_sq
    # 과대 베팅 방지를 위한 스케일 다운 및 Half-Kelly 적용
    kelly_fraction = min(max(0.0, merton_kelly * 0.05), QuantConfig.KELLY_MAX_CAP)
    
    target_risk_pct = kelly_fraction * QuantConfig.KELLY_FRACTION_MULT * 100.0

    vol_target_risk = QuantConfig.VOLATILITY_TARGET_PCT / max(atr_pct, 1e-5)
    target_risk_pct = min(target_risk_pct, vol_target_risk)
    
    risk_amount = total_equity * (target_risk_pct / 100.0)
    position_size_krw = (risk_amount / stop_distance) * entry if stop_distance > 0 else 0
    
    # [핵심] ADV + Spread/Depth 고려 (단순 ADV 참여율이 아닌 변동성 연동 유동성 캡)
    slippage_adj = max(1.0, atr_pct * 10.0)
    liq_cap_krw = (adv_100m * 100_000_000 * QuantConfig.ADV_PARTICIPATION_RATE) / slippage_adj
    position_size_krw = min(position_size_krw, liq_cap_krw)
    
    max_weight = QuantConfig.MAX_WEIGHTS.get(m_state, 0.20)
    max_amount = total_equity * max_weight
    position_size_krw = min(position_size_krw, max_amount)
    
    position_qty = int(position_size_krw / entry)
    if position_qty <= 0:
        return {"qty": 0, "amount": 0, "weight_pct": 0.0, "actual_risk_pct": 0.0, "ev": round(ev, 3)}
        
    actual_risk_amount = position_qty * stop_distance
    actual_risk_pct = round((actual_risk_amount / total_equity) * 100, 2)
    weight_pct = round((position_qty * entry / total_equity) * 100, 1)
    
    return {
        "qty": position_qty,
        "amount": int(position_qty * entry),
        "weight_pct": weight_pct,
        "actual_risk_pct": actual_risk_pct,
        "ev": round(ev, 3)
    }

def validate_trade_plan(plan: Dict[str, Any], entry: float) -> Tuple[bool, str]:
    if plan["sizing"]["qty"] <= 0:
        return False, "ZERO_QTY_OR_LOW_EV"
    if (plan["stop_distance"] / entry) > QuantConfig.MAX_STOP_LOSS_PCT:
        return False, "STOP_TOO_WIDE"
    if plan["expected_reward_rr"] < QuantConfig.MIN_EXPECTED_RR:
        return False, "POOR_RR"
    return True, "PASS"

def generate_trade_plan(cf: CandidateFeature, strategies: List[str], bayesian_win_rate: float, sys_state: Dict, m_state: str = "NORMAL", total_equity: float = 10_000_000) -> Dict[str, Any]:
    current = cf.price
    atr14 = cf.vty.atr_14
    
    if any(s in strategies for s in ["시초/갭돌파", "신고가돌파", "단기돌파"]):
        optimal_entry = current  
    elif "눌림목(HL)" in strategies:
        optimal_entry = cf.mom.ma_20 * 1.01  
    else:
        optimal_entry = max(current * 0.98, cf.mom.ma_20)
        
    if optimal_entry > current: optimal_entry = current  
        
    stop_mult = 1.5
    target2_mult = QuantConfig.TARGET2_MULT_REVERSAL
    
    if any(s in strategies for s in ["시초/갭돌파", "신고가돌파", "단기돌파"]):
        stop_mult = 2.0
        target2_mult = QuantConfig.TARGET2_MULT_BREAKOUT
    elif "눌림목(HL)" in strategies:
        stop_mult = 1.0
        target2_mult = QuantConfig.TARGET2_MULT_PULLBACK
        
    atr_stop = optimal_entry - (atr14 * stop_mult)
    pivot_stop = cf.struc.last_pivot_low_price
    
    if 0 < pivot_stop < optimal_entry:
        pivot_dist = optimal_entry - pivot_stop
        if (atr14 * 0.5) <= pivot_dist <= (atr14 * 2.5):
            base_stop = pivot_stop
        else:
            base_stop = atr_stop
    else:
        base_stop = atr_stop
        
    stop_loss = base_stop
    stop_distance = optimal_entry - stop_loss
    min_stop_dist = atr14 * QuantConfig.STOP_MIN_ATR_MULT
    
    if stop_distance < min_stop_dist:
        stop_loss = optimal_entry - min_stop_dist
        stop_distance = min_stop_dist
    
    resistance1 = cf.struc.last_pivot_high_price
    min_t1 = optimal_entry + (atr14 * 1.5)
    max_t1 = optimal_entry + (atr14 * 3.0)
    
    if min_t1 <= resistance1 <= max_t1:
        target1 = int(resistance1)
    else:
        target1 = int(optimal_entry + (atr14 * QuantConfig.TARGET1_ATR_MULT))
    
    m_state_mult = QuantConfig.TARGET2_MARKET_MULT.get(m_state, 1.0)
    adjusted_target2_mult = target2_mult * m_state_mult
    target2_3r = optimal_entry + (stop_distance * adjusted_target2_mult)
    
    fibo_target2 = optimal_entry + (stop_distance * 2.618 * m_state_mult)
    target2 = max(int(target2_3r), int(fibo_target2))
    
    if target2 <= target1:
        target2 = target1 + int(atr14)
    
    target_dist_1 = target1 - optimal_entry
    target_dist_2 = target2 - optimal_entry
    
    rr1 = target_dist_1 / stop_distance if stop_distance > 0 else -1.0
    rr2 = target_dist_2 / stop_distance if stop_distance > 0 else -1.0
    
    # [핵심] Markov Transition T1->T2 DB 실시간 확률 반영
    db_t2_probs = sys_state.get("markov_t2_prob", {})
    prob_t2_given_t1 = max([db_t2_probs.get(s, 0.45) for s in strategies]) if strategies else 0.45
    
    if rr2 > rr1 > 0:
        prob_t2_given_t1 *= np.exp(-QuantConfig.T2_DECAY_FACTOR * (rr2 - rr1))
        
    expected_reward_rr = (0.6 * rr1) + (0.4 * (rr2 * prob_t2_given_t1)) if (rr1 > 0 and rr2 > 0) else -1.0
    
    sizing = calculate_dynamic_sizing(
        optimal_entry, stop_distance, cf.vty.return_var_20d, cf.risk.atr_pct, cf.vol.adv_100m, 
        bayesian_win_rate, expected_reward_rr, m_state, total_equity
    )
    
    plan = {
        "entry": int(optimal_entry), 
        "stop_loss": int(stop_loss), 
        "stop_distance": stop_distance,
        "target1": int(target1), 
        "target2": int(target2),
        "rr1": round(rr1, 2),
        "rr2": round(rr2, 2),
        "expected_reward_rr": round(expected_reward_rr, 2),
        "sizing": sizing,
        "future_proof": {
            "entry_zone": [int(optimal_entry * 0.98), int(optimal_entry * 1.02)],
            "trail_stop_dist": int(atr14 * 1.5),
            "partial_sell_pct": 0.6,
            "max_holding_days": 10
        }
    }
    
    is_valid, reject_reason = validate_trade_plan(plan, optimal_entry)
    plan["is_valid"] = is_valid
    plan["reject_reason"] = reject_reason
    
    return plan
