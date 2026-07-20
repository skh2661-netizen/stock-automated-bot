import json
import os
import logging
from typing import List, Dict, Any
from models import CandidateFeature
from trade_plan import generate_trade_plan

_logger = logging.getLogger(__name__)

def load_holdings(filepath: str = "holdings.json") -> List[Dict]:
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _logger.error("Failed to load holdings.json: %s", e)
        return []

def evaluate_holdings(holdings: List[Dict], features_map: Dict[str, CandidateFeature]) -> List[Dict[str, Any]]:
    results = []
    
    for h in holdings:
        code = h["code"]
        name = h["name"]
        entry_price = h["entry_price"]
        
        cf = features_map.get(code)
        if not cf:
            results.append({"name": name, "entry_price": entry_price, "current_price": 0, "return_pct": 0.0, "action": "HOLD", "reason": "데이터 수집 실패"})
            continue
            
        current_price = cf.price
        return_pct = round((current_price / entry_price - 1) * 100, 2)
        
        plan = generate_trade_plan(cf, ["보유종목평가"])
        
        action = "HOLD"
        reason = "정상 보유 범위"
        
        if current_price <= plan["stop_loss"]:
            action = "STOP_LOSS"
            reason = f"손절가({plan['stop_loss']:,}원) 이탈"
        elif current_price >= plan["target2"]:
            action = "TAKE_PROFIT"
            reason = f"2차 목표가({plan['target2']:,}원) 도달"
        elif current_price >= plan["target1"]:
            if not cf.mom.is_trend_up or cf.mom.true_rs_composite < 0:
                action = "TAKE_PROFIT_EARLY"
                reason = "1차 목표가 도달 및 상승 둔화 (전량매도)"
            else:
                action = "REDUCE"
                reason = f"1차 목표가({plan['target1']:,}원) 돌파, 비중 축소"
        elif not cf.mom.is_trend_up and cf.mom.true_rs_composite < -15:
            action = "WEAK_HOLD"
            reason = "역배열 전환 및 상대강도 심각 악화"
            
        results.append({
            "code": code,
            "name": name,
            "entry_price": entry_price,
            "current_price": current_price,
            "return_pct": return_pct,
            "action": action,
            "reason": reason
        })
        
    return results
