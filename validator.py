import FinanceDataReader as fdr
import datetime
import pytz
import sqlite3
import pandas as pd
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
    today_str = datetime.datetime.now(kst).strftime("%Y-%m-%d")
    results = []
    
    try:
        conn = sqlite3.connect(DB_PATH)
        # 대기 상태인 모든 후보군을 가져와 차트 데이터를 기반으로 경과 영업일을 정밀 계산
        df = pd.read_sql("SELECT * FROM candidates WHERE exit_type = '대기'", conn)
        conn.close()
        
        if df.empty: return []
        
        for _, row in df.iterrows():
            code = str(row['code']).zfill(6)
            db_date = row['date'] # 종목이 DB에 들어간 날짜 (YYYY-MM-DD)
            
            try:
                # 안전하게 적재일 5일 전부터 오늘까지의 일봉 데이터 로드
                start_fetch = (datetime.datetime.strptime(db_date, "%Y-%m-%d") - datetime.timedelta(days=5)).strftime("%Y-%m-%d")
                hist = fdr.DataReader(code, start_fetch, today_str)
                if hist.empty: continue
                
                # 차트 데이터의 날짜 인덱스를 문자열 리스트로 변환
                trading_days = [d.strftime("%Y-%m-%d") for d in hist.index]
                
                if db_date not in trading_days: continue
                db_idx = trading_days.index(db_date)
                
                # [정밀 타격] DB 적재일 인덱스로부터 '정확히 실제 거래일 3영업일'이 지났는지 판별
                # 차트의 가장 마지막 로우(오늘 캔들)가 적재일로부터 정확히 3번째 뒤에 위치해야 타겟팅됨
                if len(trading_days) - 1 == db_idx + 3:
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
        print(f"D+3 실 거래일 정밀 추출 오류: {e}")
        
    return results
