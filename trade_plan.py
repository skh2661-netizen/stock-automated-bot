# trade_plan.py
import numpy as np
from copy import deepcopy
from version import TRADE_PLAN_CONTRACT_VERSION
from models import CandidateFeature, QuantConfig
from contract_utils import _is_finite_real, _is_strict_int
from typing import Dict, Any, List

def _create_envelope(is_valid: bool, reject_reason: str, data: dict = None) -> dict:
    base = {
        "contract_version": TRADE_PLAN_CONTRACT_VERSION,
        "entry": 0, "stop_loss": 0, "stop_distance": 0.0,
        "target1": 0, "target2": 0, "rr1": 0.0, "rr2": 0.0,
        "t2_probability_base": 0.0, "t2_probability_adjusted": 0.0,
        "expected_reward_rr": 0.0, "bayesian_win_rate": 0.0,
        "sizing": {"qty": 0, "amount": 0.0, "weight_ratio": 0.0, "actual_risk_ratio": 0.0, "ev": 0.0},
        "equity_at_plan": 0.0, "market_state_at_plan": "UNKNOWN",
        "atr_ratio_at_plan": 0.0, "adv_100m_at_plan": 0.0,
        "strategies_at_plan": [], "markov_t2_prob_at_plan": {},
        "future_proof": {"entry_zone": [0, 0], "trail_stop_dist": 0, "partial_sell_pct": 0.0, "max_holding_days": 1},
        "is_valid": is_valid,
        "reject_reason": reject_reason
    }
    if data:
        base.update(data)
    return base

def calculate_dynamic_sizing(entry: int, stop_distance: float, atr_ratio: float, adv_100m: float, bayesian_win_rate: float, expected_reward_rr: float, m_state: str, total_equity: float) -> Dict[str, Any]:
    ev = (bayesian_win_rate * expected_reward_rr) - ((1.0 - bayesian_win_rate) * 1.0) - QuantConfig.FEE_SLIPPAGE_COST_R
    if stop_distance <= 0 or expected_reward_rr <= 0 or ev < QuantConfig.MIN_EV_THRESHOLD: 
        return {"qty": 0, "amount": 0.0, "weight_ratio": 0.0, "actual_risk_ratio": 0.0, "ev": ev}
    
    kelly_fraction = bayesian_win_rate - ((1.0 - bayesian_win_rate) / expected_reward_rr)
    if kelly_fraction <= 0:
        return {"qty": 0, "amount": 0.0, "weight_ratio": 0.0, "actual_risk_ratio": 0.0, "ev": ev}
        
    target_risk_ratio = min(kelly_fraction * QuantConfig.KELLY_FRACTION_MULT, QuantConfig.KELLY_MAX_CAP_RATIO)
    vol_target_risk_ratio = QuantConfig.VOLATILITY_TARGET_RATIO / max(atr_ratio, 1e-5)
    target_risk_ratio = min(target_risk_ratio, vol_target_risk_ratio)
    
    risk_amount_krw = total_equity * target_risk_ratio
    risk_based_qty = int(risk_amount_krw / stop_distance)
    risk_based_amount_krw = risk_based_qty * entry
    
    slippage_adj = max(1.0, atr_ratio * QuantConfig.ATR_TO_LIQUIDITY_MULT)
    liq_cap_krw = (adv_100m * 100_000_000 * QuantConfig.ADV_PARTICIPATION_RATIO) / slippage_adj
    
    max_position_amount_krw = total_equity * QuantConfig.MAX_WEIGHTS_RATIO[m_state]
    
    position_amount_krw = min(risk_based_amount_krw, liq_cap_krw, max_position_amount_krw)
    position_qty = int(position_amount_krw / entry)
    
    if position_qty <= 0:
        return {"qty": 0, "amount": 0.0, "weight_ratio": 0.0, "actual_risk_ratio": 0.0, "ev": ev}
        
    final_amount = float(position_qty * entry)
    return {
        "qty": position_qty,
        "amount": final_amount,
        "weight_ratio": final_amount / total_equity,
        "actual_risk_ratio": (position_qty * stop_distance) / total_equity,
        "ev": ev
    }

def generate_trade_plan(cf: CandidateFeature, strategies: List[str], bayesian_win_rate: float, sys_state: Dict, m_state: str = "NORMAL", total_equity: float = 10_000_000) -> Dict[str, Any]:
    # [P0-3] 최후의 Exception Barrier (크래시가 아닌 Fail-Closed Envelope 반환)
    try:
        # 1. 스칼라/외부 파라미터 무결성 선제 방어
        if type(m_state) is not str or m_state not in QuantConfig.MAX_WEIGHTS_RATIO:
            return _create_envelope(False, "UNSUPPORTED_MARKET_STATE")
        if not _is_finite_real(total_equity) or total_equity <= 0:
            return _create_envelope(False, "INVALID_EQUITY_INPUT")
        if not _is_finite_real(bayesian_win_rate) or not (0.0 <= bayesian_win_rate <= 1.0):
            return _create_envelope(False, "INVALID_BAYESIAN_WIN_RATE_INPUT")

        # 2. [P0-1] cf 객체 자체 및 하위 그룹 무결성 방어 (AttributeError 원천 차단)
        if cf is None:
            return _create_envelope(False, "INVALID_CANDIDATE_FEATURE")
        required_cf_groups = ["vty", "vol", "mom", "struc"]
        for group in required_cf_groups:
            if getattr(cf, group, None) is None:
                return _create_envelope(False, f"MISSING_FEATURE_GROUP_{group.upper()}")

        # 3. 객체 방어 통과 후 Raw Feature 추출 및 값 무결성 방어
        raw_features = [
            cf.price, cf.vty.atr_14, cf.vol.adv_100m, 
            cf.mom.ma_20, cf.struc.last_pivot_low_price, cf.struc.last_pivot_high_price
        ]
        for val in raw_features:
            if not _is_finite_real(val) or val < 0:
                return _create_envelope(False, "INVALID_RAW_FEATURE_VALUE")
        if cf.price <= 0 or cf.vty.atr_14 <= 0:
            return _create_envelope(False, "ZERO_OR_NEGATIVE_PRICE_ATR")

        current = cf.price
        atr14 = cf.vty.atr_14
        atr_ratio = atr14 / current

        # 4. [P0-2] sys_state 및 T2 Source 컨테이너 무결성 방어
        if type(sys_state) is not dict:
            return _create_envelope(False, "INVALID_SYS_STATE_TYPE")
        db_t2_probs = sys_state.get("markov_t2_prob")
        if type(db_t2_probs) is not dict:
            return _create_envelope(False, "INVALID_T2_SOURCE_CONTAINER")

        # 5. [P1-2] 전략(Strategies) 중복 및 무결성 방어
        if type(strategies) is not list or len(strategies) == 0:
            return _create_envelope(False, "EMPTY_STRATEGY_SOURCE")
        if len(strategies) != len(set(strategies)):
            return _create_envelope(False, "DUPLICATE_STRATEGY")

        required_markov_snapshot = {}
        for s in strategies:
            if type(s) is not str or not s.strip():
                return _create_envelope(False, "INVALID_STRATEGY_NAME")
            if s not in db_t2_probs:
                return _create_envelope(False, f"MISSING_T2_PROBABILITY_SOURCE_FOR_{s}")
            val = db_t2_probs[s]
            if not _is_finite_real(val) or not (0.0 <= float(val) <= 1.0):
                return _create_envelope(False, f"INVALID_T2_SOURCE_RANGE_TYPE_FOR_{s}")
            required_markov_snapshot[s] = float(val)

        # 6. 가격 연산 (정수화 전)
        if any(s in strategies for s in ["시초/갭돌파", "신고가돌파", "단기돌파"]):
            optimal_entry, stop_mult, target2_mult = current, 2.0, QuantConfig.TARGET2_MULT_BREAKOUT
        elif "눌림목(HL)" in strategies:
            optimal_entry, stop_mult, target2_mult = cf.mom.ma_20 * 1.01, 1.0, QuantConfig.TARGET2_MULT_PULLBACK
        else:
            optimal_entry, stop_mult, target2_mult = max(current * 0.98, cf.mom.ma_20), 1.5, QuantConfig.TARGET2_MULT_REVERSAL
            
        if optimal_entry > current: optimal_entry = current  
            
        atr_stop = optimal_entry - (atr14 * stop_mult)
        pivot_stop = cf.struc.last_pivot_low_price
        if 0 < pivot_stop < optimal_entry:
            pivot_dist = optimal_entry - pivot_stop
            base_stop = pivot_stop if (atr14 * 0.5) <= pivot_dist <= (atr14 * 2.5) else atr_stop
        else:
            base_stop = atr_stop
            
        min_stop_dist = current * QuantConfig.ATR_MIN_RATIO
        if (optimal_entry - base_stop) < min_stop_dist:
            base_stop = optimal_entry - min_stop_dist

        resistance1 = cf.struc.last_pivot_high_price
        min_t1 = optimal_entry + (atr14 * 1.5)
        max_t1 = optimal_entry + (atr14 * 3.0)
        base_t1 = resistance1 if min_t1 <= resistance1 <= max_t1 else optimal_entry + (atr14 * QuantConfig.TARGET1_ATR_MULT)
        
        base_t2 = max(optimal_entry + ((optimal_entry - base_stop) * target2_mult * QuantConfig.TARGET2_MARKET_MULT[m_state]), base_t1 + atr14)

        # 7. 가격 정수화(Rounding) 및 수학 파생연산
        entry, stop_loss = int(round(optimal_entry)), int(round(base_stop))
        target1, target2 = int(round(base_t1)), int(round(base_t2))

        stop_distance = float(entry - stop_loss)
        if stop_distance <= 0:
            return _create_envelope(False, "INVALID_STOP_DISTANCE_AFTER_ROUNDING")

        rr1, rr2 = (target1 - entry) / stop_distance, (target2 - entry) / stop_distance

        t2_probability_base = max([required_markov_snapshot[s] for s in strategies])
        t2_probability_adjusted = t2_probability_base
        if rr2 > rr1 > 0:
            t2_probability_adjusted *= np.exp(-QuantConfig.T2_DECAY_FACTOR * (rr2 - rr1))
            
        expected_reward_rr = (QuantConfig.EXPECTED_RR_T1_WEIGHT * rr1) + (QuantConfig.EXPECTED_RR_T2_WEIGHT * (rr2 * t2_probability_adjusted)) if (rr1 > 0 and rr2 > 0) else -1.0

        sizing = calculate_dynamic_sizing(entry, stop_distance, atr_ratio, cf.vol.adv_100m, bayesian_win_rate, expected_reward_rr, m_state, total_equity)

        # 8. Envelope 조립 및 Immutable Snapshot 확정
        plan_data = {
            "entry": entry, "stop_loss": stop_loss, "stop_distance": stop_distance,
            "target1": target1, "target2": target2, "rr1": rr1, "rr2": rr2,
            "t2_probability_base": t2_probability_base, "t2_probability_adjusted": t2_probability_adjusted,
            "expected_reward_rr": expected_reward_rr, "bayesian_win_rate": bayesian_win_rate,
            "sizing": sizing,
            "equity_at_plan": float(total_equity), "market_state_at_plan": m_state,
            "atr_ratio_at_plan": float(atr_ratio), "adv_100m_at_plan": float(cf.vol.adv_100m),
            "strategies_at_plan": list(strategies), 
            "markov_t2_prob_at_plan": deepcopy(required_markov_snapshot),
            "future_proof": {
                "entry_zone": [int(entry * 0.98), int(entry * 1.02)], 
                "trail_stop_dist": int(atr14 * 1.5), 
                "partial_sell_pct": 0.6, 
                "max_holding_days": 10
            }
        }
        
        is_valid, reject_reason = True, "PASS"
        if sizing["qty"] <= 0: is_valid, reject_reason = False, "ZERO_QTY"
        elif (stop_distance / entry) > QuantConfig.MAX_STOP_LOSS_RATIO: is_valid, reject_reason = False, "STOP_TOO_WIDE"
        elif expected_reward_rr < QuantConfig.MIN_EXPECTED_RR: is_valid, reject_reason = False, "POOR_RR"

        return _create_envelope(is_valid, reject_reason, plan_data)
        
    except Exception as e:
        return _create_envelope(False, f"PRODUCER_EXCEPTION:{type(e).__name__}")
