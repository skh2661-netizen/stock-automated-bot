import sqlite3
import FinanceDataReader as fdr
from datetime import datetime
import pytz

DB_PATH = "candidates.db"

def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def update_performance():
    conn = connect()
    # 평가 대기 중인 종목만 스캔
    rows = conn.execute("SELECT * FROM candidates WHERE result_status = '대기'").fetchall()

    for row in rows:
        code = row['code']
        entry_date = row['date']
        unique_key = row['unique_key']
        buy_p = row['buy_p']
        target1 = row['target1_p']
        stop = row['stop_p']

        try:
            # 추천일 이후의 데이터 호출
            hist = fdr.DataReader(code, entry_date)
            # 아직 D+1 데이터가 생성되지 않았다면 스킵 (휴장일 또는 장 시작 전)
            if len(hist) < 2:
                continue 

            # D+1 확정 데이터 추출
            d1_data = hist.iloc[1]
            d1_high = int(d1_data['High'])
            d1_low = int(d1_data['Low'])
            d1_close = int(d1_data['Close'])

            # 1. 체결 여부 확인 (D+1 저가가 매수가보다 낮으면 체결)
            entry_success = 1 if d1_low <= buy_p else 0
            
            exit_type = "대기"
            result_status = "대기"

            # 2. 결과 판정 연산
            if entry_success == 1:
                if d1_low <= stop and d1_high >= target1:
                    exit_type = "동시도달(손절우선)" # 가장 보수적인 리스크 억제 연산
                    result_status = "종료"
                elif d1_high >= target1:
                    exit_type = "익절(T1)"
                    result_status = "종료"
                elif d1_low <= stop:
                    exit_type = "손절"
                    result_status = "종료"
                else:
                    exit_type = "보유"
                    result_status = "진행중" # D+3, D+5 추적을 위해 진행중으로 이관
            else:
                exit_type = "미체결"
                result_status = "종료"

            # 3. DB 업데이트
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
