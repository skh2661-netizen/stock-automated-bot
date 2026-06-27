import sqlite3
import pandas as pd
import FinanceDataReader as fdr
import time
from datetime import datetime
from database import DB_PATH

def process_outcomes():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ⚙️ Outcome Worker 가동")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT id, code, signal_date, price_at_signal FROM signal_outcome WHERE evaluation_status = 'PENDING'")
    pendings = c.fetchall()
    
    if not pendings:
        print("✅ 평가 대기 신호 없음.")
        conn.close()
        return

    for pid, code, sig_date, entry_price in pendings:
        if entry_price <= 0:
            c.execute("UPDATE signal_outcome SET evaluation_status = 'ERROR' WHERE id = ?", (pid,))
            continue
            
        try:
            # [수정 4] 데이터 조회 시 시계열 밀림(Index Shift) 방어 처리
            # 신호일(sig_date) 이후의 데이터만 추출하여 T+0을 엄격히 고정
            df = fdr.DataReader(code, sig_date)
            time.sleep(0.5)
            
            if len(df) < 2: continue # T+1 미도달
            
            days_passed = len(df) - 1
            future_df = df.iloc[1:] # T+1부터 T+N까지의 실제 추이
            
            # 저장된 entry_price(발생 당시 진입가)를 기준으로 미래 수익률 연산
            max_gain = round(((future_df['High'].max() / entry_price) - 1) * 100, 2)
            mdd = round(((future_df['Low'].min() / entry_price) - 1) * 100, 2)
            
            a1 = round(((df.iloc[1]['Close'] / entry_price) - 1) * 100, 2) if days_passed >= 1 else 0.0
            a3 = round(((df.iloc[3]['Close'] / entry_price) - 1) * 100, 2) if days_passed >= 3 else 0.0
            a5 = round(((df.iloc[5]['Close'] / entry_price) - 1) * 100, 2) if days_passed >= 5 else 0.0
            
            status = 'COMPLETED' if days_passed >= 5 else 'PENDING'
            
            c.execute('''
                UPDATE signal_outcome 
                SET after_1d_chg=?, after_3d_chg=?, after_5d_chg=?, max_gain=?, max_drawdown=?, evaluation_status=?
                WHERE id=?
            ''', (a1, a3, a5, max_gain, mdd, status, pid))
            print(f"  └ [{code}] 업데이트 완료 (상태: {status}, T+{days_passed} 경과)")
            
        except Exception as e:
            print(f"❌ [{code}] 에러: {e}")
            c.execute("UPDATE signal_outcome SET evaluation_status = 'ERROR' WHERE id = ?", (pid,))
            
    conn.commit()
    conn.close()
    print("🏁 Outcome Worker 종료")

if __name__ == "__main__":
    process_outcomes()
