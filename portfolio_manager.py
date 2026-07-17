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
    
    judgment: str = "🟢 보유"
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
    logging.info(f"[Portfolio Check] File target: {os.path.abspath(HOLDINGS_FILE)}")
    
    if not os.path.exists(HOLDINGS_FILE):
        logging.error(f"[{HOLDINGS_FILE}] MISSING - Cannot find file in directory.")
        return []
        
    if not os.access(HOLDINGS_FILE, os.R_OK):
        logging.error(f"[{HOLDINGS_FILE}] PERMISSION DENIED - Cannot read file.")
        return []
    
    try:
        with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            if not content.strip():
                logging.error(f"[{HOLDINGS_FILE}] EMPTY - File exists but has no content.")
                return []
            data = json.loads(content)
        
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
        logging.info(f"[{HOLDINGS_FILE}] LOAD SUCCESS - Loaded {len(holdings)} holdings.")
        return holdings
    except json.JSONDecodeError as e:
        logging.error(f"[{HOLDINGS_FILE}] DECODE ERROR - Invalid JSON format: {e}")
        return []
    except Exception as e:
        logging.error(f"[{HOLDINGS_FILE}] UNKNOWN ERROR Loading: {e}")
        return []

def assess_portfolio_health(holdings: List[Holding], holdings_eval: List[Dict]) -> PortfolioState:
    if not holdings or not holdings_eval:
        return PortfolioState(phs_score=100.0, tier="SURVIVAL", allow_new_buy=True)
        
    eval_map = {item['code']: item for item in holdings_eval}
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
            
            if h.conf < 30.0: h.judgment = "🚨 청산 (TIME STOP)"
            elif h.pnl <= -10.0: h.judgment = "🚨 청산 (손절 이탈)"
            else: h.judgment = "🟢 보유"
                
            total_conf += h.conf
            
    phs_score = round(total_conf / len(holdings), 1)
    
    if phs_score >= 60.0: tier, allow_new_buy = "AGGRESSIVE", True
    elif phs_score >= 45.0: tier, allow_new_buy = "DEFENSIVE", True
    else: tier, allow_new_buy = "DANGER", False
        
    return PortfolioState(phs_score=phs_score, tier=tier, allow_new_buy=allow_new_buy)
