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
    # [수정] 대기 및 진행중인 모든 종목 스캔
    rows = conn.execute("SELECT * FROM candidates WHERE result_status IN ('대기', '진행중')").fetchall()

    for row in rows:
        code, entry_date, unique_key = row['code'], row['date'], row['unique_key']
        buy_p, target1, stop = row['buy_p'], row['target1_p'], row['stop_p']
        
        # 기존 기록 보존
        d1_h, d1_l, d1_c = row['d1_high'], row['d1_low'], row['d1_close']
        d3_h, d3_l, d3_c = row['d3_high'], row['d3_low'], row['d3_close']
        d5_h, d5_l, d5_c = row['d5_high'], row['d5_low'], row['d5_close']
        entry_success = row['entry_success']
        exit_type = row['exit_type']
        result_status = row['result_status']

        try:
            hist = fdr.DataReader(code, entry_date)
            trading_days = len(hist) - 1
            if trading_days < 1: continue # 아직 D+1 데이터도 없다면 패스

            # 1. D+1 미체결 판정 로직
            if entry_success is None:
                d1_data = hist.iloc[1]
                d1_h, d1_l, d1_c = int(d1_data['High']), int(d1_data['Low']), int(d1_data['Close'])
                entry_success = 1 if d1_l <= buy_p else 0
                
                if entry_success == 0:
                    exit_type, result_status = "미체결", "종료"
                    conn.execute("UPDATE candidates SET d1_high=?, d1_low=?, d1_close=?, entry_success=?, exit_type=?, result_status=? WHERE unique_key=?", 
                                 (d1_h, d1_l, d1_c, entry_success, exit_type, result_status, unique_key))
                    continue # 미체결 시 더 이상 추적하지 않음
                else:
                    result_status = "진행중"

            # 2. 체결 종목 D+1 ~ D+5 누적 추적 루프
            max_days = min(len(hist), 6) # D+1(인덱스1)부터 D+5(인덱스5)까지만 추적
            for i in range(1, max_days):
                curr = hist.iloc[i]
                curr_h, curr_l, curr_c = int(curr['High']), int(curr['Low']), int(curr['Close'])

                # 지정일 고가/저가/종가 갱신
                if i == 1: d1_h, d1_l, d1_c = curr_h, curr_l, curr_c
                elif i == 3: d3_h, d3_l, d3_c = curr_h, curr_l, curr_c
                elif i == 5: d5_h, d5_l, d5_c = curr_h, curr_l, curr_c

                # 이미 종료된 종목은 상태 업데이트 무시
                if result_status == "종료": continue

                # 도달 여부 판정
                if curr_l <= stop and curr_h >= target1:
                    exit_type, result_status = f"동시도달(손절/D+{i})", "종료"
                elif curr_h >= target1:
                    exit_type, result_status = f"익절(T1/D+{i})", "종료"
                elif curr_l <= stop:
                    exit_type, result_status = f"손절(D+{i})", "종료"
                elif i == 5: # D+5까지 들고 왔는데 타겟에 안 왔다면 강제 청산
                    exit_type, result_status = "기간종료(D+5)", "종료"

            # DB 최종 반영
            conn.execute("""
                UPDATE candidates
                SET d1_high=?, d1_low=?, d1_close=?,
                    d3_high=?, d3_low=?, d3_close=?,
                    d5_high=?, d5_low=?, d5_close=?,
                    entry_success=?, exit_type=?, result_status=?
                WHERE unique_key=?
            """, (d1_h, d1_l, d1_c, d3_h, d3_l, d3_c, d5_h, d5_l, d5_c, 
                  entry_success, exit_type, result_status, unique_key))
            
        except Exception as e:
            print(f"[{code}] 추적 연산 오류: {e}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    update_performance()
