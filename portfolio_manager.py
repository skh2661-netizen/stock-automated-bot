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
    
    judgment: str = "보유"
    pnl: float = 0.0
    conf: float = 0.0
    rs: float = 0.0
    stop_p: float = 0.0

@dataclass
class PortfolioState:
    phs_score: float
    tier: str
    allow_new_buy: bool

def load_holdings() -> List[Holding]:
    logging.info(f"========== [PORTFOLIO DIAGNOSTICS] ==========")
    logging.info(f"Target File : {os.path.abspath(HOLDINGS_FILE)}")
    
    if not os.path.exists(HOLDINGS_FILE):
        logging.warning(f"Status : MISSING. Initiating 100% Cash State.")
        return []
        
    logging.info(f"Status : EXISTS")
    
    try:
        file_size = os.path.getsize(HOLDINGS_FILE)
        logging.info(f"File Size : {file_size} bytes")
        
        with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            if not content.strip():
                # 👑 파일이 비어있는 것은 자연스러운 현금 대기 상태이므로 Warning으로 격하
                logging.warning("Content : EMPTY (0 chars). Assuming 100% Cash State.")
                return []
            
            data = json.loads(content)
            logging.info(f"JSON Decode : SUCCESS | Items: {len(data)}")
        
        holdings = []
        for item in data:
            h = Holding(
                code=item.get("code", ""),
                name=item.get("name", ""),
                entry_price=float(item.get("entry_price", 0.0)),
                quantity=int(item.get("quantity", 0)),
                entry_date=item.get("entry_date", ""),
                entry_level=item.get("entry_level", ""),
                conf_history=item.get("conf_history", [])
            )
            holdings.append(h)
            logging.info(f"Loaded Item : {h.name} ({h.code}) | Entry: {h.entry_price}")
            
        logging.info(f"========== [PORTFOLIO LOAD END] ==========")
        return holdings
    except json.JSONDecodeError as e:
        # 👑 JSON 파싱 실패 시에도 시스템 붕괴 없이 현금 대기 상태로 강제 전환
        logging.warning(f"JSON DECODE WARNING : Invalid format ({e}). Resetting to empty portfolio.")
        return []
    except Exception as e:
        logging.error(f"UNKNOWN ERROR : {e}")
        return []

def assess_portfolio_health(holdings: List[Holding], holdings_eval: List[Dict]) -> PortfolioState:
    if not holdings:
        return PortfolioState(phs_score=100.0, tier="정상 (100% 현금)", allow_new_buy=True)
        
    eval_map = {item['code']: item for item in holdings_eval} if holdings_eval else {}
    total_conf = 0.0
    
    for h in holdings:
        ev = eval_map.get(h.code)
        if ev:
            current_price = ev.get('price', 0)
            decision = ev.get('decision', {})
            plan = decision.get('trade_plan', {})
            
            if h.entry_price > 0:
                h.pnl = round(((current_price / h.entry_price) - 1) * 100, 2)
                
            h.conf = decision.get('confidence', 0.0)
            h.rs = decision.get('rs_20d', 0.0)
            h.stop_p = plan.get('stop_loss', 0.0)
            
            if h.conf < 30.0: h.judgment = "청산 (동력상실)"
            elif h.pnl <= -10.0: h.judgment = "청산 (손절이탈)"
            else: h.judgment = "보유"
                
            total_conf += h.conf
            
    phs_score = round(total_conf / len(holdings), 1) if holdings else 100.0
    
    if phs_score >= 60.0: tier, allow_new_buy = "정상", True
    elif phs_score >= 45.0: tier, allow_new_buy = "방어", True
    else: tier, allow_new_buy = "위험", False
        
    return PortfolioState(phs_score=phs_score, tier=tier, allow_new_buy=allow_new_buy)
