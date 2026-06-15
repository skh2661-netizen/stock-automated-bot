import FinanceDataReader as fdr
import datetime
import pytz
import sqlite3
import pandas as pd
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

# [신규 추가] D+3 보유 종목 추출 및 익절 수익률 계산기
def validate_d3_targets():
    kst = pytz.timezone('Asia/Seoul')
    # 현재일 기준 정확히 3일 전 날짜 역산
    target_date = (datetime.datetime.now(kst) - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    results = []
    
    try:
        conn = sqlite3.connect("candidates.db")
        # 컬럼 인덱스 오류 방지를 위해 pandas 데이터프레임으로 로드
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
                        "name": row['name'],
                        "code": code,
                        "buy_p": buy_p,
                        "current": current,
                        "change": change
                    })
            except: continue
    except Exception as e:
        print(f"D+3 타겟 추출 오류: {e}")
        
    return results
