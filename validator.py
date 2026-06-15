import FinanceDataReader as fdr
import datetime
from database import get_today_candidates

def validate_candidates():
    candidates = get_today_candidates()
    results = []
    
    for row in candidates:
        try:
            db_id, date, code, name, score, entry_price, market_mode, *extra = row
            hist = fdr.DataReader(code, (datetime.datetime.now() - datetime.timedelta(days=40)).strftime("%Y-%m-%d"))
            if len(hist) < 20: continue
            
            current = hist['Close'].iloc[-1]
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            volume_now = hist['Volume'].iloc[-1]
            volume_avg = hist['Volume'].rolling(20).mean().iloc[-1]
            
            survive, reason = True, []
            if current < ma20:
                survive = False
                reason.append("MA20 이탈")
            if (volume_now / volume_avg) < 0.8:
                reason.append("거래량 감소")
            
            change = (current / entry_price - 1) * 100
            if change < -3:
                survive = False
                reason.append("손절권 진입")
                
            results.append({
                "name": name, "code": code, "score": score, 
                "entry": entry_price, "current": int(current), 
                "change": round(change, 2), "survive": survive, "reason": reason
            })
        except: continue
    return results
