import sqlite3
import pandas as pd
from datetime import datetime
import pytz

DB_PATH = "candidates.db"

def show_dashboard():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    today = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d")

    print(f"=== [대시보드] {today} 오늘의 후보 ===")
    today_df = pd.read_sql_query(f"SELECT code, name, score, buy_p, target1_p, stop_p FROM candidates WHERE date = '{today}'", conn)
    if not today_df.empty:
        print(today_df.to_string(index=False))
    else:
        print("오늘 발생한 신규 후보가 없습니다.")

    print("\n=== [대시보드] V8.4.2 실시간 성과 요약 ===")
    ended_df = pd.read_sql_query("SELECT * FROM candidates WHERE result_status = '종료' AND entry_success = 1", conn)

    if not ended_df.empty:
        wins = len(ended_df[ended_df['exit_type'] == '익절(T1)'])
        win_rate = (wins / len(ended_df)) * 100

        ended_df['return_rate'] = 0.0
        for idx, row in ended_df.iterrows():
            if row['exit_type'] == '익절(T1)':
                ended_df.at[idx, 'return_rate'] = (row['target1_p'] / row['buy_p'] - 1) * 100
            elif '손절' in row['exit_type']:
                ended_df.at[idx, 'return_rate'] = (row['stop_p'] / row['buy_p'] - 1) * 100

        avg_return = ended_df['return_rate'].mean()

        print(f"누적 체결: {len(ended_df)}건")
        print(f"누적 승률: {win_rate:.2f}%")
        print(f"평균 수익률: {avg_return:.2f}%")
    else:
        print("아직 평가가 완료된 체결 데이터가 없습니다.")

    conn.close()

if __name__ == "__main__":
    show_dashboard()
