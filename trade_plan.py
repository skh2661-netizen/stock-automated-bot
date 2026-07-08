from models import CandidateFeature

def generate_trade_plan(cf: CandidateFeature):
    entry = cf.price
    atr_stop = int(entry - (cf.vty.atr_14 * 1.5))
    pivot_stop = cf.struc.last_pivot_low_price if cf.struc.last_pivot_low_price > 0 else atr_stop
    stop_loss = min(atr_stop, pivot_stop)
    
    target1 = int(entry + (cf.vty.atr_14 * 2.0))
    target2 = int(entry + (cf.vty.atr_14 * 4.0))
    
    return {"entry": entry, "stop_loss": stop_loss, "target1": target1, "target2": target2}
