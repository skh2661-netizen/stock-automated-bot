# strategy_engine.py
from typing import List, Tuple
from models import CandidateFeature

def assign_strategies(cf: CandidateFeature) -> Tuple[List[str], int]:
    strategies = []
    bonus_score = 0
    
    is_higher_low = cf.struc.last_pivot_low_price > cf.struc.prev_pivot_low_price > 0
    
    if cf.pat.is_gap_up and cf.pat.gap_survived and cf.vol.relative_vol_today >= 1.5:
        strategies.append("시초/갭돌파")
        bonus_score += 10
        
    if cf.mom.true_rs_composite >= 15 and cf.struc.dist_ma20 <= 10:
        strategies.append("주도주(RS)")
        bonus_score += 10
        
    if cf.struc.dist_52w_high > -5.0 and cf.vol.vr_20 >= 1.5:
        strategies.append("신고가돌파")
        bonus_score += 8
        
    if is_higher_low and cf.pat.is_hammer and cf.mom.is_trend_up:
        strategies.append("눌림목(HL)")
        bonus_score += 8
        
    if cf.pat.is_bull_engulfing:
        strategies.append("상승장악")
        bonus_score += 7
        
    if cf.mom.true_rs_composite <= -20 and cf.vol.vr_20 >= 1.5:
        strategies.append("과대낙폭반등")
        bonus_score += 5
        
    if not strategies:
        strategies.append("수급/종가베팅")
        bonus_score += 3
        
    final_strategies = strategies[:2]
    # [수정] 복수 전략 가점 한도 축소 (의미 없는 고득점 인플레이션 방지)
    final_bonus = min(bonus_score, 18) 
        
    return final_strategies, final_bonus
