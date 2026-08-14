# contracts.py
import math
from version import TRADE_PLAN_CONTRACT_VERSION
from models import QuantConfig
from contract_utils import _is_finite_real, _is_strict_int

def validate_trade_plan_contract(plan: dict, total_equity: float, market_state: str, atr_ratio: float, adv_100m: float) -> tuple[bool, str]:
    try:
        # 1. Consumer Context 무결성 (타입 및 범위 검증)
        if not _is_finite_real(total_equity) or total_equity <= 0: return False, "INVALID_INPUT_TOTAL_EQUITY"
        if not _is_finite_real(atr_ratio) or atr_ratio <= 0: return False, "INVALID_INPUT_ATR_RATIO"
        if not _is_finite_real(adv_100m) or adv_100m < 0: return False, "INVALID_INPUT_ADV_100M"
        
        # [최후의 잔여 P0 해결] 외부 market_state 타입 검증
        if type(market_state) is not str or market_state not in QuantConfig.MAX_WEIGHTS_RATIO: 
            return False, "INVALID_MARKET_STATE_INPUT"

        if type(plan) is not dict: return False, "PLAN_NOT_DICT"

        # 2. Strict Schema 강제 비교
        required_keys = {
            "contract_version", "entry", "stop_loss", "stop_distance", "target1", "target2", 
            "rr1", "rr2", "t2_probability_base", "t2_probability_adjusted", "expected_reward_rr", 
            "bayesian_win_rate", "sizing", "equity_at_plan", "market_state_at_plan", 
            "atr_ratio_at_plan", "adv_100m_at_plan", "strategies_at_plan", "markov_t2_prob_at_plan", 
            "future_proof", "is_valid", "reject_reason"
        }
        if set(plan.keys()) != required_keys: return False, "ENVELOPE_SCHEMA_MISMATCH"

        if not _is_strict_int(plan["contract_version"]): return False, "INVALID_CONTRACT_VERSION_TYPE"
        if plan["contract_version"] != TRADE_PLAN_CONTRACT_VERSION: return False, "UNSUPPORTED_CONTRACT_VERSION"
        if type(plan["is_valid"]) is not bool: return False, "INVALID_IS_VALID_TYPE"
        if type(plan["reject_reason"]) is not str: return False, "INVALID_REJECT_REASON_TYPE"

        # [최후의 잔여 P0 해결] 3. Diagnostic Envelope 의미 명확화 (조기 차단)
        if plan["is_valid"] is False:
            return False, f"PRODUCER_DIAGNOSTIC_ENVELOPE:{plan.get('reject_reason', 'UNKNOWN')}"

        # 4. Context Snapshot 무결성 검증 (타입/값 순차 검증)
        for k in ["equity_at_plan", "atr_ratio_at_plan", "adv_100m_at_plan"]:
            if not _is_finite_real(plan[k]): return False, f"INVALID_SNAPSHOT_TYPE_{k.upper()}"
        
        if type(plan["market_state_at_plan"]) is not str: return False, "INVALID_MARKET_STATE_SNAPSHOT_TYPE"
        if plan["market_state_at_plan"] not in QuantConfig.MAX_WEIGHTS_RATIO: return False, "INVALID_MARKET_STATE_SNAPSHOT_VALUE"

        if not math.isclose(plan["equity_at_plan"], total_equity, rel_tol=0, abs_tol=1e-9): return False, "CONTEXT_EQUITY_MISMATCH"
        if not math.isclose(plan["atr_ratio_at_plan"], atr_ratio, rel_tol=0, abs_tol=1e-9): return False, "CONTEXT_ATR_MISMATCH"
        if not math.isclose(plan["adv_100m_at_plan"], adv_100m, rel_tol=0, abs_tol=1e-9): return False, "CONTEXT_ADV_MISMATCH"
        if plan["market_state_at_plan"] != market_state: return False, "CONTEXT_MARKET_STATE_MISMATCH"

        # 5. Strict Integer 가격 검증
        for k in ["entry", "stop_loss", "target1", "target2"]:
            if not _is_strict_int(plan[k]): return False, f"INVALID_INTEGER_TYPE_{k.upper()}"

        entry, stop_loss = plan["entry"], plan["stop_loss"]
        target1, target2 = plan["target1"], plan["target2"]

        if not (entry > 0 and 0 < stop_loss < entry): return False, "INVALID_ENTRY_STOP"
        if not (target1 > entry and target2 >= target1): return False, "INVALID_TARGETS"
        
        calc_stop_distance = float(entry - stop_loss)
        if calc_stop_distance <= 0: return False, "ZERO_STOP_DISTANCE"
        
        # [P1-1] 모든 Numeric 필드 Strict 검증
        numeric_fields = ["stop_distance", "rr1", "rr2", "t2_probability_base", "t2_probability_adjusted", "expected_reward_rr", "bayesian_win_rate"]
        for k in numeric_fields:
            if not _is_finite_real(plan[k]): return False, f"INVALID_NUMERIC_TYPE_{k.upper()}"

        if not math.isclose(plan["stop_distance"], calc_stop_distance, rel_tol=0, abs_tol=1e-9): return False, "STOP_DISTANCE_MISMATCH"
        if (calc_stop_distance / entry) > QuantConfig.MAX_STOP_LOSS_RATIO: return False, "POLICY_VIOLATION_STOP_TOO_WIDE"

        # 6. RR 재계산
        calc_rr1 = (target1 - entry) / calc_stop_distance
        calc_rr2 = (target2 - entry) / calc_stop_distance
        if not math.isclose(plan["rr1"], calc_rr1, rel_tol=0, abs_tol=QuantConfig.TOL_RR_ABS): return False, "RR1_MISMATCH"
        if not math.isclose(plan["rr2"], calc_rr2, rel_tol=0, abs_tol=QuantConfig.TOL_RR_ABS): return False, "RR2_MISMATCH"
        if not (calc_rr1 > 0 and calc_rr2 >= calc_rr1): return False, "INVALID_RR_ORDER"

        # 7. Bayesian Win Rate (Trusted Input Range 검증)
        win_rate = float(plan["bayesian_win_rate"])
        if not (0.0 <= win_rate <= 1.0): return False, "INVALID_BAYESIAN_WIN_RATE"

        # 8. T2 Source 무결성 및 완전 독립 재계산
        strats = plan["strategies_at_plan"]
        markov_db = plan["markov_t2_prob_at_plan"]
        
        if type(strats) is not list or len(strats) == 0: return False, "EMPTY_STRATEGY_SOURCE"
        if any(type(s) is not str or not s.strip() for s in strats): return False, "INVALID_STRATEGY_NAME"
        if len(strats) != len(set(strats)): return False, "DUPLICATE_STRATEGY"
        if type(markov_db) is not dict: return False, "INVALID_MARKOV_DB_TYPE"

        for s in strats:
            if s not in markov_db: return False, f"MISSING_T2_SOURCE_FOR_{s}"
            val = markov_db[s]
            if not _is_finite_real(val): return False, f"INVALID_T2_SOURCE_TYPE_FOR_{s}"
            if not (0.0 <= float(val) <= 1.0): return False, f"INVALID_T2_SOURCE_RANGE_FOR_{s}"

        calc_t2_base = max([float(markov_db[s]) for s in strats])
        if not math.isclose(float(plan["t2_probability_base"]), calc_t2_base, rel_tol=0, abs_tol=QuantConfig.TOL_PROB_ABS): 
            return False, "T2_BASE_PROB_MISMATCH"

        calc_t2_adj = calc_t2_base * math.exp(-QuantConfig.T2_DECAY_FACTOR * (calc_rr2 - calc_rr1))
        calc_t2_adj = max(0.0, min(1.0, calc_t2_adj))
        if not math.isclose(float(plan["t2_probability_adjusted"]), calc_t2_adj, rel_tol=0, abs_tol=QuantConfig.TOL_PROB_ABS): 
            return False, "T2_DECAY_MISMATCH"

        # 9. Expected RR 재계산
        calc_expected_rr = (QuantConfig.EXPECTED_RR_T1_WEIGHT * calc_rr1) + (QuantConfig.EXPECTED_RR_T2_WEIGHT * (calc_rr2 * calc_t2_adj))
        if not math.isclose(float(plan["expected_reward_rr"]), calc_expected_rr, rel_tol=0, abs_tol=QuantConfig.TOL_RR_ABS): 
            return False, "EXPECTED_RR_MISMATCH"
        if calc_expected_rr < QuantConfig.MIN_EXPECTED_RR: return False, "POLICY_VIOLATION_POOR_RR"

        # 10. Sizing 검증
        sizing = plan["sizing"]
        if type(sizing) is not dict: return False, "SIZING_NOT_DICT"
        if set(sizing.keys()) != {"qty", "amount", "weight_ratio", "actual_risk_ratio", "ev"}: return False, "SIZING_SCHEMA_MISMATCH"
        
        if not _is_strict_int(sizing["qty"]): return False, "INVALID_QTY_TYPE"
        if sizing["qty"] <= 0: return False, "INVALID_QTY_VALUE"

        for sk in ["amount", "weight_ratio", "actual_risk_ratio", "ev"]:
            if not _is_finite_real(sizing[sk]): return False, f"INVALID_SIZING_{sk.upper()}_TYPE"

        p_qty, p_amt = sizing["qty"], float(sizing["amount"])
        p_weight, p_risk, p_ev = float(sizing["weight_ratio"]), float(sizing["actual_risk_ratio"]), float(sizing["ev"])

        calc_ev = (win_rate * calc_expected_rr) - ((1.0 - win_rate) * 1.0) - QuantConfig.FEE_SLIPPAGE_COST_R
        if not math.isclose(p_ev, calc_ev, rel_tol=0, abs_tol=QuantConfig.TOL_EV_ABS): return False, "EV_MISMATCH"
        if calc_ev < QuantConfig.MIN_EV_THRESHOLD: return False, "POLICY_VIOLATION_EV_BELOW_THRESHOLD"

        k_frac = win_rate - ((1.0 - win_rate) / calc_expected_rr)
        if k_frac <= 0: return False, "NEGATIVE_KELLY"
        
        adj_k = k_frac * QuantConfig.KELLY_FRACTION_MULT
        t_risk = min(adj_k, QuantConfig.KELLY_MAX_CAP_RATIO)
        vol_t_risk = QuantConfig.VOLATILITY_TARGET_RATIO / max(atr_ratio, 1e-5)
        t_risk = min(t_risk, vol_t_risk)
        
        r_amt_krw = total_equity * t_risk
        r_qty = int(r_amt_krw / calc_stop_distance)
        r_amt_krw_final = r_qty * entry
        
        slip_adj = max(1.0, atr_ratio * QuantConfig.ATR_TO_LIQUIDITY_MULT)
        liq_cap = (adv_100m * 100_000_000 * QuantConfig.ADV_PARTICIPATION_RATIO) / slip_adj
        max_amt = total_equity * QuantConfig.MAX_WEIGHTS_RATIO[market_state]
        
        calc_final_amt = min(r_amt_krw_final, liq_cap, max_amt)
        calc_qty_final = int(calc_final_amt / entry)

        if calc_qty_final != p_qty: return False, "POLICY_VIOLATION_QTY_MISMATCH"

        if not math.isclose(p_amt, calc_qty_final * entry, rel_tol=0, abs_tol=QuantConfig.TOL_AMT_ABS): return False, "AMOUNT_MISMATCH"
        if not math.isclose(p_risk, (calc_qty_final * calc_stop_distance) / total_equity, rel_tol=0, abs_tol=1e-6): return False, "RISK_RATIO_MISMATCH"
        if not math.isclose(p_weight, (calc_qty_final * entry) / total_equity, rel_tol=0, abs_tol=1e-6): return False, "WEIGHT_RATIO_MISMATCH"

        # 11. Future Proof 검증
        fp = plan["future_proof"]
        if type(fp) is not dict or set(fp.keys()) != {"entry_zone", "trail_stop_dist", "partial_sell_pct", "max_holding_days"}: 
            return False, "FUTURE_PROOF_SCHEMA_MISMATCH"
        
        ez = fp["entry_zone"]
        if type(ez) is not list or len(ez) != 2: return False, "INVALID_FP_ENTRY_ZONE_TYPE"
        if not _is_strict_int(ez[0]) or not _is_strict_int(ez[1]) or ez[0] > ez[1]: return False, "INVALID_FP_ENTRY_ZONE_VALUES"
        if not (ez[0] <= entry <= ez[1]): return False, "ENTRY_OUT_OF_ZONE"
        
        if not _is_strict_int(fp["trail_stop_dist"]) or fp["trail_stop_dist"] <= 0: return False, "INVALID_FP_TRAIL_STOP"
        if not _is_finite_real(fp["partial_sell_pct"]) or not (0.0 <= float(fp["partial_sell_pct"]) <= 1.0): return False, "INVALID_FP_PARTIAL_SELL"
        if not _is_strict_int(fp["max_holding_days"]) or fp["max_holding_days"] <= 0: return False, "INVALID_FP_MAX_HOLDING"

        return True, "PASS"

    except Exception as e:
        return False, f"PLAN_EXCEPTION:{type(e).__name__}"
