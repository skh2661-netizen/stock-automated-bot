# portfolio_manager.py
import json
import os
from models import Holding

@dataclass
class PortfolioState:
    phs_score: float
    tier: str
    allow_new_buy: bool
    allow_adding: bool
    allow_lvl2_buy: bool
    strict_swap: bool
    force_reval: bool

def load_holdings(filepath="holdings.json") -> list[Holding]:
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [Holding(**item) for item in data]

def save_holdings(holdings: list[Holding], filepath="holdings.json"):
    data = [h.__dict__ for h in holdings]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def calculate_pnl_score(avg_pnl_pct: float) -> float:
    score = 50 + (avg_pnl_pct * (50 / 15))
    return min(max(score, 0), 100)

def calculate_portfolio_health(holdings_eval: list, market: dict) -> PortfolioState:
    """
    원인(Conf, Comp)과 결과(PnL)를 결합하고 시장 매트릭스를 할인율로 반영하는 PHS 연산기
    """
    if not holdings_eval:
        return PortfolioState(75.0, "NORMAL", True, True, True, False, False)
        
    sum_conf = sum(h["decision"]["confidence"] for h in holdings_eval)
    sum_comp = sum(h["decision"]["composite_rank"] for h in holdings_eval)
    
    # 임시 PnL (실전 연동 전 0% 기준 스코어 50점 매핑)
    pnl_score = 50.0 
    
    avg_conf = sum_conf / len(holdings_eval)
    avg_comp = sum_comp / len(holdings_eval)
    
    base_phs = (avg_conf * 0.50) + (avg_comp * 0.30) + (pnl_score * 0.20)
    
    m_state = market.get("state", "NORMAL")
    b_trend = market.get("breadth", {}).get("trend", "Unknown")
    
    multiplier = 1.0
    if m_state == "BULL": multiplier = 1.05
    elif m_state == "RISK": multiplier = 0.93
    elif m_state == "CRASH": multiplier = 0.85
    
    if b_trend == "Improving": multiplier += 0.02
    elif b_trend == "Weakening": multiplier -= 0.02
    
    final_phs = round(base_phs * multiplier, 1)
    
    tier = "SURVIVAL"
    allow_new_buy, allow_adding, allow_lvl2_buy, strict_swap, force_reval = False, False, False, True, True
    
    if final_phs >= 85:
        tier = "AGGRESSIVE"
        allow_new_buy, allow_adding, allow_lvl2_buy, strict_swap, force_reval = True, True, True, False, False
    elif final_phs >= 70:
        tier = "NORMAL"
        allow_new_buy, allow_adding, allow_lvl2_buy, strict_swap, force_reval = True, True, True, False, False
    elif final_phs >= 55:
        tier = "CAUTION"
        allow_new_buy, allow_adding, allow_lvl2_buy, strict_swap, force_reval = True, False, True, False, False
    elif final_phs >= 40:
        tier = "DEFENSIVE"
        allow_new_buy, allow_adding, allow_lvl2_buy, strict_swap, force_reval = True, False, False, True, True
        
    return PortfolioState(final_phs, tier, allow_new_buy, allow_adding, allow_lvl2_buy, strict_swap, force_reval)

def evaluate_time_stop(holding: Holding, current_eval: dict, market_state: str, phs_tier: str) -> bool:
    """
    ✅ [교정] 형님 지시사항 ①: 리스크 역전 현상 전면 수리 (폭락장 시 청산 Threshold 라인을 상향하여 칼손절 강제)
    """
    if phs_tier == "AGGRESSIVE":
        return False
        
    curr_conf = current_eval["confidence"]
    curr_comp = current_eval["composite_rank"]
    
    # 폭락장 가산 패널티 (위험할수록 커트라인을 높여 조기 청산 유도)
    penalty = 0
    if market_state == "RISK": penalty = 5
    elif market_state == "CRASH": penalty = 10
    
    if holding.entry_level == "LEVEL 4":
        conf_drop = curr_conf <= (holding.entry_confidence - 20)
        abs_conf = curr_conf < (55 + penalty)  # CRASH 면 65점 미만 시 즉시 컷
        comp_drop = curr_comp <= (holding.entry_composite - 15)
        if conf_drop and abs_conf and comp_drop: return True
            
    elif holding.entry_level == "LEVEL 3":
        conf_drop = curr_conf <= (holding.entry_confidence - 15)
        abs_conf = curr_conf < (50 + penalty)  # CRASH 면 60점 미만 시 즉시 컷
        comp_drop = curr_comp <= (holding.entry_composite - 10)
        if conf_drop and abs_conf and comp_drop: return True
            
    else: # LEVEL 2 (정찰병 필터)
        conf_drop = curr_conf <= (holding.entry_confidence - 10)
        abs_conf = curr_conf < (45 + penalty)
        if conf_drop or abs_conf: return True
            
    return False
