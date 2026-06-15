import sqlite3
import FinanceDataReader as fdr
from datetime import datetime

DB_PATH = "candidates.db"

def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def update_performance():
    conn = connect()
    rows = conn.execute("SELECT * FROM candidates WHERE result_status = '대기'").fetchall()

    for row in rows:
        code = row['code']
        entry_date = row['date']
        unique_key = row['unique_key']
        buy_p, target1, stop = row['buy_p'], row['target1_p'], row['stop_p']

        try:
            hist = fdr.DataReader(code, entry_date)
            if len(hist) < 2: 
                continue 

            d1_data = hist.iloc[1]
            d1_high = int(d1_data['High'])
            d1_low = int(d1_data['Low'])
            d1_close = int(d1_data['Close'])

            entry_success = 1 if d1_low <= buy_p else 0
            
            if entry_success == 1:
                if d1_low <= stop and d1_high >= target1:
                    exit_type, result_status = "동시도달(손절우선)", "종료"
                elif d1_high >= target1:
                    exit_type, result_status = "익절(T1)", "종료"
                elif d1_low <= stop:
                    exit_type, result_status = "손절", "종료"
                else:
                    exit_type, result_status = "보유", "진행중"
            else:
                exit_type, result_status = "미체결", "종료"

            conn.execute("""
                UPDATE candidates
                SET d1_high=?, d1_low=?, d1_close=?,
                    entry_success=?, exit_type=?, result_status=?
                WHERE unique_key=?
            """, (d1_high, d1_low, d1_close, entry_success, exit_type, result_status, unique_key))
            
        except Exception as e:
            print(f"[{code}] 추적 연산 오류: {e}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    update_performance()
