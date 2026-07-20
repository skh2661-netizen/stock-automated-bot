import json
import os
import logging
import datetime
import FinanceDataReader as fdr
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

def save_holdings(holdings: List[Dict], filepath: str = "holdings.json"):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(holdings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _logger.error("Failed to save holdings.json: %s", e)

def evaluate_holdings(holdings: List[Dict]) -> List[Dict[str, Any]]:
    results = []
    start_date = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    
    for h in holdings:
        code = h["code"]
        name = h["name"]
        entry_price = h.get("entry_price", 0)
        stop_loss = h.get("stop_loss", entry_price * 0.95)
        target1 = h.get("target1", entry_price * 1.1)
        target2 = h.get("target2", entry_price * 1.2)
        highest_price = h.get("highest_price", entry_price)
        
        try:
            # 독립 데이터 조회 (스캐너 필터링 무시)
            df = fdr.DataReader(code, start_date)
            if df is None or df.empty:
                raise ValueError("No data returned")
                
            current_price = int(df['Close'].iloc[-1])
            chg = round((current_price / df['Close'].iloc[-2] - 1) * 100, 2) if len(df) > 1 else 0.0
            
            # 트레일링 스탑을 위한 최고가 갱신
            if current_price > highest_price:
                h["highest_price"] = current_price
                highest_price = current_price
                
        except Exception as e:
            _logger.error(f"보유종목 {name}({code}) 조회 실패: {e}")
            results.append({
                "code": code, "name": name, "entry_price": entry_price, 
                "current_price": 0, "return_pct": 0.0, "action": "ERROR", "reason": "데이터 수집 실패"
            })
            continue
            
        return_pct = round((current_price / entry_price - 1) * 100, 2) if entry_price > 0 else 0.0
        
        action = "HOLD"
        reason = "정상 보유 범위"
        
        # 실전 관리 로직 (Trailing Stop 7%)
        trailing_stop = highest_price * 0.93 
        
        if current_price <= stop_loss:
            action = "STOP_LOSS"
            reason = f"지정 손절가({stop_loss:,}원) 이탈"
        elif current_price <= trailing_stop and return_pct > 0:
            action = "TAKE_PROFIT"
            reason = f"트레일링 스탑 이탈 (고점대비 7% 하락). 수익 확보."
        elif current_price >= target2:
            action = "TAKE_PROFIT"
            reason = f"2차 목표가({target2:,}원) 도달. 전량 매도."
        elif current_price >= target1:
            action = "REDUCE"
            reason = f"1차 목표가({target1:,}원) 도달. 절반 익절 권장."
        elif chg < -8.0:
            action = "WEAK_HOLD"
            reason = f"당일 {chg}% 급락 발생. 추세 이탈 주의."
            
        results.append({
            "code": code, "name": name, "entry_price": entry_price, 
            "current_price": current_price, "return_pct": return_pct, 
            "action": action, "reason": reason
        })
        
    save_holdings(holdings) # 갱신된 highest_price 저장
    return results
