from models import MarketContext
from dataclasses import dataclass

@dataclass
class PortfolioState:
    phs_score: float
    tier: str
    allow_new_buy: bool
    allow_adding: bool
    allow_lvl2_buy: bool
    strict_swap: bool
    force_reval: bool

def calculate_pnl_score(avg_pnl_pct: float) -> float:
    """
    미실현 손익(%)을 0~100점 스케일로 정규화
    -15% 이하는 0점, +15% 이상은 100점, 0%는 50점으로 매핑
    """
    score = 50 + (avg_pnl_pct * (50 / 15))
    return min(max(score, 0), 100)

def calculate_portfolio_health(holdings: list, market: dict) -> PortfolioState:
    # 1. 포트폴리오가 비어있을 경우 (초기 상태)
    if not holdings:
        return PortfolioState(75.0, "NORMAL", True, True, True, False, False)
        
    # 2. Base PHS 산출 (원인 80% + 결과 20%)
    avg_conf = sum(h.confidence for h in holdings) / len(holdings)
    avg_comp = sum(h.composite_rank for h in holdings) / len(holdings)
    avg_pnl = sum(h.pnl_pct for h in holdings) / len(holdings)
    
    pnl_score = calculate_pnl_score(avg_pnl)
    base_phs = (avg_conf * 0.50) + (avg_comp * 0.30) + (pnl_score * 0.20)
    
    # 3. Market State & Breadth Modifier (할인율 적용)
    m_state = market.get("state", "NORMAL")
    b_trend = market.get("breadth", {}).get("trend", "Unknown")
    
    multiplier = 1.0
    if m_state == "BULL": multiplier = 1.05
    elif m_state == "RISK": multiplier = 0.93
    elif m_state == "CRASH": multiplier = 0.85
    
    if b_trend == "Improving": multiplier += 0.02
    elif b_trend == "Weakening": multiplier -= 0.02
    
    # 4. Final PHS 도출
    final_phs = round(base_phs * multiplier, 1)
    
    # 5. 5단계 생존(Survivability) 상태 머신 제어
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
