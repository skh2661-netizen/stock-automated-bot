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
            
            # [핵심 수정 1] 거래량 0으로 인한 ZeroDivisionError 원천 차단
            if volume_avg <= 0:
                continue
            
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
        conn.row_factory = sqlite3.Row
        # exit_type이 '대기'인 스윙 포지션 종목만 스캔
        rows = conn.execute("SELECT * FROM candidates WHERE exit_type = '대기'").fetchall()
        
        if not rows:
            conn.close()
            return []
        
        targets_to_update = []
        
        for row in rows:
            code = str(row['code']).zfill(6)
            db_date = row['date']
            unique_key = row['unique_key']
            
            try:
                start_fetch = (datetime.datetime.strptime(db_date, "%Y-%m-%d") - datetime.timedelta(days=5)).strftime("%Y-%m-%d")
                hist = fdr.DataReader(code, start_fetch, today_str)
                if hist.empty: continue
                
                trading_days = [d.strftime("%Y-%m-%d") for d in hist.index]
                if db_date not in trading_days: continue
                db_idx = trading_days.index(db_date)
                
                # 순수 영업일 기준 3일 경과 시점 정밀 타격
                if len(trading_days) - 1 == db_idx + 3:
                    current = int(hist['Close'].iloc[-1])
                    buy_p = int(row['buy_p'])
                    
                    if buy_p > 0:
                        change = round((current / buy_p - 1) * 100, 2)
                        results.append({
                            "name": row['name'], "code": code,
                            "buy_p": buy_p, "current": current, "change": change
                        })
                        targets_to_update.append(unique_key)
            # [핵심 수정 2] PEP8 표준 권장에 따른 Exception 명시 (Bare Except 방지)
            except Exception: 
                continue
            
        # [추가] 알림 발송 완료된 종목은 'D3완료'로 업데이트하여 내일 중복 리포팅 방지
        if targets_to_update:
            for key in targets_to_update:
                conn.execute("UPDATE candidates SET exit_type = 'D3완료' WHERE unique_key = ?", (key,))
            conn.commit()
            
        conn.close()
    except Exception as e:
        print(f"D+3 실 거래일 정밀 추출 오류: {e}")
        
    return results
