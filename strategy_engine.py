from models import CandidateFeature

def assign_strategies(cf: CandidateFeature):
    primary = "수급/종가베팅"
    secondary = None
    
    is_higher_low = cf.struc.last_pivot_low_price > cf.struc.prev_pivot_low_price and cf.struc.last_pivot_low_price > 0
    
    # 모델명 변수 동기화 교정: rvt -> relative_vol_today
    if cf.pat.is_gap_up and cf.pat.gap_survived and cf.vol.relative_vol_today >= 2.0:
        primary = "시초/갭돌파"
    elif cf.mom.rs_20d >= 20 and cf.struc.dist_ma20 <= 15 and cf.vol.vr_20 >= 2.0:
        primary = "맥점돌파"
    elif is_higher_low and cf.mom.ma_gap <= 5 and cf.pat.is_hammer:
        primary = "눌림목 (Higher Low)"
    elif cf.mom.rs_20d <= -20 and cf.pat.is_bull_engulfing:
        primary = "과대낙폭 반등"
        
    if cf.pat.is_bull_engulfing or cf.pat.is_hammer: secondary = "반전 캔들 출현"
        
    return primary, secondary
