import FinanceDataReader as fdr
import datetime
import pytz
import sqlite3
import pandas as pd
from pandas.tseries.offsets import BDay
from database import get_today_candidates, DB_PATH

def validate_candidates():
    candidates = get_today_candidates()
    results = []
    
    for row in candidates:
        try:
            code = str(row['code']).zfill(6)
            name = row['name']
            score = row['score']
            entry_price = row['buy_p'] 
            
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
            
            change = (current / entry_price - 1) * 100 if entry_price > 0 else 0
            if change < -3:
                survive = False
                reason.append("손절권 진입")
                
            results.append({
                "name": name, "code": code, "score": score, 
                "entry": entry_price, "current": int(current), 
                "change": round(change, 2), "survive": survive, "reason": reason
            })
        except Exception: 
            continue
            
    return results

def validate_d3_targets():
    kst = pytz.timezone('Asia/Seoul')
    # [수정] 단순 3일 차감이 아닌 Pandas BDay를 활용한 순수 영업일 3일전 계산
    target_date = (datetime.datetime.now(kst) - BDay(3)).strftime("%Y-%m-%d")
    results = []
    
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql(f"SELECT * FROM candidates WHERE date LIKE '{target_date}%'", conn)
        conn.close()
        
        if df.empty: return []
        
        for _, row in df.iterrows():
            code = str(row['code']).zfill(6)
            try:
                hist = fdr.DataReader(code, target_date)
                if hist.empty: continue
                
                current = int(hist['Close'].iloc[-1])
                buy_p = int(row.get('buy_p', 0))
                
                if buy_p > 0:
                    change = round((current / buy_p - 1) * 100, 2)
                    results.append({
                        "name": row['name'], "code": code,
                        "buy_p": buy_p, "current": current, "change": change
                    })
            except: continue
    except Exception as e:
        print(f"D+3 타겟 추출 오류: {e}")
        
    return results
