# trade_plan.py
import numpy as np
from models import CandidateFeature, QuantConfig
from typing import Dict, Any, List, Tuple

def calculate_dynamic_sizing(entry: float, stop_distance: float, return_var_20d: float, atr_pct: float, adv_100m: float, bayesian_win_rate: float, expected_reward_rr: float, m_state: str, total_equity: float) -> Dict[str, Any]:
    # 순수 기대값(EV) 연산 (단위: R)
    ev = (bayesian_win_rate * expected_reward_rr) - ((1.0 - bayesian_win_rate) * 1.0) - QuantConfig.FEE_SLIPPAGE_COST
    
    if stop_distance <= 0 or expected_reward_rr <= 0 or ev < QuantConfig.MIN_EV_THRESHOLD: 
        return {"qty": 0, "amount": 0, "weight_pct": 0.0, "actual_risk_pct": 0.0, "ev": round(ev, 3)}
    
    # =========================================================================
    # [수술 1] 차원 불일치 해결: 이산형 트레이딩 표준 Kelly 공식 적용
    # =========================================================================
    # 기존: R단위 기대값을 주가수익률 분산으로 나누는 논리적 오류 폐기
    # 신규: 승률(W)과 기대손익비(R)를 활용한 정확한 켈리 비중 산출 (f = W - (1-W)/R)
    
    W = bayesian_win_rate
    R = expected_reward_rr
    
    kelly_fraction = W - ((1.0 - W) / R)
    
    # 켈리 비중이 음수(통계적 우위 없음)면 매수 차단
    if kelly_fraction <= 0:
        return {"qty": 0, "amount": 0, "weight_pct": 0.0, "actual_risk_pct": 0.0, "ev": round(ev, 3)}
        
    # 과대 베팅 방지를 위한 Half-Kelly (또는 설정된 비율) 적용
    adjusted_kelly = kelly_fraction * QuantConfig.KELLY_FRACTION_MULT
    
    # 켈리 캡 적용 (예: 아무리 좋아도 최대 허용 리스크 이상 베팅 금지)
    target_risk_pct = min(adjusted_kelly * 100.0, QuantConfig.KELLY_MAX_CAP * 100.0)

    # =========================================================================
    # [방어 로직] 변동성(ATR) 기반 타겟 리스크 조정 및 유동성 캡
    # =========================================================================
    # 변동성이 너무 큰 종목은 리스크 비중을 강제로 축소
    vol_target_risk = QuantConfig.VOLATILITY_TARGET_PCT / max(atr_pct, 1e-5)
    target_risk_pct = min(target_risk_pct, vol_target_risk)
    
    # 리스크(Risk) 기반 진입 금액 산출 (target_risk_pct는 계좌 전체 대비 잃을 수 있는 최대 금액 비율)
    risk_amount = total_equity * (target_risk_pct / 100.0)
    position_size_krw = (risk_amount / stop_distance) * entry if stop_distance > 0 else 0
    
    # ADV + Spread/Depth 고려 (유동성 참여율 캡)
    slippage_adj = max(1.0, atr_pct * 10.0)
    liq_cap_krw = (adv_100m * 100_000_000 * QuantConfig.ADV_PARTICIPATION_RATE) / slippage_adj
    position_size_krw = min(position_size_krw, liq_cap_krw)
    
    # 시장 상태별 최대 비중 캡 적용 (예: 특정 종목에 계좌의 30% 이상 투자 금지)
    max_weight = QuantConfig.MAX_WEIGHTS.get(m_state, 0.20)
    max_amount = total_equity * max_weight
    position_size_krw = min(position_size_krw, max_amount)
    
    # 최종 수량 계산
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
