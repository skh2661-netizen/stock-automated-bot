# strategy_engine.py
from models import CandidateFeature

def assign_strategies(cf: CandidateFeature):
    primary = "수급/종가베팅"
    secondary = None
    
    is_higher_low = cf.struc.last_pivot_low_price > cf.struc.prev_pivot_low_price and cf.struc.last_pivot_low_price > 0
    
    if cf.pat.is_gap_up and cf.pat.gap_survived and cf.vol.rvt >= 2.0:
        primary = "시초/갭돌파"
    elif cf.mom.rs_20d >= 20 and cf.struc.dist_ma20 <= 15 and cf.vol.vr_20 >= 2.0:
        primary = "맥점돌파"
    elif is_higher_low and cf.mom.ma_gap <= 5 and cf.pat.is_hammer:
        primary = "눌림목 (Higher Low)"
    elif cf.mom.rs_20d <= -20 and cf.pat.is_bull_engulfing:
        primary = "과대낙폭 반등"
        
    if cf.pat.is_bull_engulfing or cf.pat.is_hammer: secondary = "반전 캔들 출현"
        
    return primary, secondary

# trade_plan.py
from models import CandidateFeature

def generate_trade_plan(cf: CandidateFeature):
    entry = cf.price
    atr_stop = int(entry - (cf.vty.atr_14 * 1.5))
    pivot_stop = cf.struc.last_pivot_low_price if cf.struc.last_pivot_low_price > 0 else atr_stop
    stop_loss = min(atr_stop, pivot_stop)
    
    target1 = int(entry + (cf.vty.atr_14 * 2.0))
    target2 = int(entry + (cf.vty.atr_14 * 4.0))
    
    return {"entry": entry, "stop_loss": stop_loss, "target1": target1, "target2": target2}
