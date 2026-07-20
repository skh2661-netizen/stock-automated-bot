from models import CandidateFeature
from typing import Dict, Any, List

def generate_trade_plan(cf: CandidateFeature, strategies: List[str], total_equity: float = 10_000_000, risk_per_trade_pct: float = 1.0) -> Dict[str, Any]:
    current = cf.price
    
    if "시초/갭돌파" in strategies or "신고가돌파" in strategies:
        optimal_entry = current  
    elif "눌림목(HL)" in strategies:
        optimal_entry = cf.mom.ma_20 * 1.01  
    else:
        optimal_entry = max(current * 0.98, cf.mom.ma_20)
        
    if optimal_entry > current: optimal_entry = current  
        
    # [수정] 손절가(Stop Loss): ATR과 Pivot 중 더 먼(min) 곳을 잡아 휩소 이탈 방지
    atr_stop = optimal_entry - (cf.vty.atr_14 * 1.5)
    pivot_stop = cf.struc.last_pivot_low_price
    
    stop_loss = min(atr_stop, pivot_stop) if pivot_stop > 0 else atr_stop
    stop_loss = min(stop_loss, optimal_entry * 0.95)  # 최소 5% 손절폭 보장
    
    # [핵심 수정] 목표가(Target): 단순 ATR이 아닌 직전 저항선(Pivot High) 기준 산출
    resistance1 = cf.struc.prev_pivot_high_price if cf.struc.prev_pivot_high_price > optimal_entry else optimal_entry * 1.10
    
    target1 = max(int(optimal_entry + (cf.vty.atr_14 * 2.0)), int(resistance1))
    target2 = max(int(optimal_entry + (cf.vty.atr_14 * 4.0)), int(resistance1 * 1.05))
    
    risk_amount = total_equity * (risk_per_trade_pct / 100.0)
    stop_distance = optimal_entry - stop_loss
    
    # [수정] 저항선 기반으로 계산된 실전 손익비(RR) 산출
    target_distance = target1 - optimal_entry
    rr_ratio = round(target_distance / stop_distance, 2) if stop_distance > 0 else -1.0
    
    if stop_distance > 0:
        position_qty = max(1, int(risk_amount / stop_distance))
        position_size_krw = position_qty * optimal_entry
    else:
        position_qty = 1
        position_size_krw = optimal_entry
        
    if position_size_krw > (total_equity * 0.3):
        position_size_krw = total_equity * 0.3
        position_qty = max(1, int(position_size_krw / optimal_entry))
        
    weight_pct = round((position_size_krw / total_equity) * 100, 1)

    return {
        "entry": int(optimal_entry), 
        "stop_loss": int(stop_loss), 
        "target1": int(target1), 
        "target2": int(target2),
        "rr_ratio": rr_ratio,
        "sizing": {
            "qty": position_qty,
            "amount": int(position_size_krw),
            "weight_pct": weight_pct
        }
    }
