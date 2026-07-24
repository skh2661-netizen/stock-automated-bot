# strategy_engine.py
from typing import List, Tuple, Dict
from models import CandidateFeature, QuantConfig

def _calc_prior_ev(strat: str, sys_state: Dict) -> float:
    stats = sys_state.get("strat_db", {}).get(strat, {"w": 0, "l": 0, "rr": 1.0})
    total = stats["w"] + stats["l"]
    if total == 0: return 0.0
    win_rate = stats["w"] / total
    return (win_rate * stats["rr"]) - (1.0 - win_rate)

def assign_strategies(cf: CandidateFeature, sys_state: Dict) -> Tuple[List[str], float]:
    matched_groups = {"breakout": [], "pullback": [], "reversal": [], "other": []}
    
    is_higher_low = cf.struc.last_pivot_low_price > cf.struc.prev_pivot_low_price > 0
    
    if cf.pat.is_gap_up and cf.pat.gap_survived and cf.chg <= cf.risk.max_gap_allowed:
        matched_groups["breakout"].append("시초/갭돌파")
    if cf.struc.dist_52w_high > -5.0 and cf.vol.vr_20 >= 1.5:
        matched_groups["breakout"].append("신고가돌파")
    if cf.struc.is_5d_breakout:
        matched_groups["breakout"].append("단기돌파")
        
    if is_higher_low and cf.struc.is_higher_high and cf.pat.is_hammer and cf.mom.is_trend_up and cf.vol.is_vol_dry_up:
        matched_groups["pullback"].append("눌림목(HL)")
        
    if cf.pat.is_bull_engulfing:
        matched_groups["reversal"].append("상승장악")
    if cf.vol.vr_20 >= 1.5 and cf.chg < -8.0:
        matched_groups["reversal"].append("과대낙폭반등")
        
    if cf.mom.true_rs_composite >= 15 and cf.struc.dist_ma20 <= 10:
        matched_groups["other"].append("주도주(RS)")
        
    final_candidates = []
    for group, strats in matched_groups.items():
        if strats:
            best_strat = max(strats, key=lambda s: _calc_prior_ev(s, sys_state))
            final_candidates.append(best_strat)
            
    if not final_candidates:
        final_candidates.append("수급/종가베팅")
        
    final_strategies = final_candidates[:2]
    
    # [핵심] DB 기반 Empirical Bayes 실시간 업데이트 연동
    strat_db = sys_state.get("strat_db", QuantConfig.STRAT_DB_MOCK)
    
    total_w = sum(d.get("w", 0) for d in strat_db.values())
    total_l = sum(d.get("l", 0) for d in strat_db.values())
    global_prior_win = total_w / (total_w + total_l) if (total_w + total_l) > 0 else 0.5
    
    w_sum, l_sum = 0, 0
    total_prior_alpha, total_prior_beta = 0.0, 0.0
    
    for s in final_strategies:
        stats = strat_db.get(s, {"w": 0, "l": 0, "prior_alpha": QuantConfig.DEFAULT_PRIOR_ALPHA, "prior_beta": QuantConfig.DEFAULT_PRIOR_BETA})
        w_sum += stats["w"]
        l_sum += stats["l"]
        total_prior_alpha += stats["prior_alpha"]
        total_prior_beta += stats["prior_beta"]
        
    # 제임스-스타인 방식의 베이지안 글로벌 풀링 
    bayesian_win_rate = (total_prior_alpha + w_sum + (global_prior_win * QuantConfig.PRIOR_WEIGHT_K)) / \
                        (total_prior_alpha + total_prior_beta + w_sum + l_sum + QuantConfig.PRIOR_WEIGHT_K)
                        
    return final_strategies, bayesian_win_rate
