import json
import os
import logging
from dataclasses import dataclass, field
from typing import List, Dict

HOLDINGS_FILE = "holdings.json"

@dataclass
class Holding:
    code: str
    name: str
    entry_price: float
    quantity: int
    entry_date: str
    entry_level: str
    conf_history: List[float] = field(default_factory=list)
    
    # 텔레그램 관제용 실시간 매핑 변수
    judgment: str = "🟢 보유"
    pnl: float = 0.0
    conf: float = 0.0
    stop_p: float = 0.0

@dataclass
class PortfolioState:
    phs_score: float
    tier: str
    allow_new_buy: bool

def load_holdings() -> List[Holding]:
    if not os.path.exists(HOLDINGS_FILE):
        logging.info(f"[{HOLDINGS_FILE}] Not found. Initiating 100% CASH state.")
        return []
    
    try:
        with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        holdings = []
        for item in data:
            holdings.append(Holding(
                code=item.get("code", ""),
                name=item.get("name", ""),
                entry_price=float(item.get("entry_price", 0.0)),
                quantity=int(item.get("quantity", 0)),
                entry_date=item.get("entry_date", ""),
                entry_level=item.get("entry_level", ""),
                conf_history=item.get("conf_history", [])
            ))
        return holdings
    except Exception as e:
        logging.error(f"Portfolio Loading Failed: {e}")
        return []

def assess_portfolio_health(holdings: List[Holding], holdings_eval: List[Dict]) -> PortfolioState:
    """
    실시간 재평가된 종목 데이터를 기반으로 개별 종목의 PNL/청산 판정을 업데이트하고,
    전체 계좌 건강도(PHS)를 산출하여 신규 매수 통제 여부를 결정합니다.
    """
    if not holdings or not holdings_eval:
        return PortfolioState(phs_score=100.0, tier="SURVIVAL (100% CASH)", allow_new_buy=True)
        
    eval_map = {item['code']: item for item in holdings_eval}
    total_conf = 0.0
    
    for h in holdings:
        ev = eval_map.get(h.code)
        if ev:
            current_price = ev.get('price', 0)
            decision = ev.get('decision', {})
            plan = decision.get('trade_plan', {})
            
            # 실시간 PNL 연산 (평단가 대비 손익)
            if h.entry_price > 0:
                h.pnl = round(((current_price / h.entry_price) - 1) * 100, 2)
                
            h.conf = decision.get('confidence', 0.0)
            h.stop_p = plan.get('stop_loss', 0.0)
            
            # 👑 런타임 종목 판정 (Time Stop 및 손절가 이탈 로직)
            if h.conf < 30.0:
                h.judgment = "🚨 청산 (TIME STOP - 동력 상실)"
            elif h.pnl <= -10.0:
                h.judgment = "🚨 청산 (손절가 이탈)"
            else:
                h.judgment = "🟢 보유"
                
            total_conf += h.conf
            
    # 계좌 건강도(PHS) 연산 및 태세 결정
    phs_score = round(total_conf / len(holdings), 1)
    
    if phs_score >= 60.0:
        tier = "AGGRESSIVE"
        allow_new_buy = True
    elif phs_score >= 45.0:
        tier = "DEFENSIVE"
        allow_new_buy = True
    else:
        tier = "DANGER"
        allow_new_buy = False
        
    return PortfolioState(phs_score=phs_score, tier=tier, allow_new_buy=allow_new_buy)
