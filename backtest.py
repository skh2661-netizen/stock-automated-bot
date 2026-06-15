import sqlite3
import pandas as pd

DB_PATH = "candidates.db"

def run_backtest():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    query = "SELECT * FROM candidates WHERE result_status = '종료' AND entry_success = 1"
    df = pd.read_sql_query(query, conn)
    conn.close()

    print("=== [V8.4.2 전략 백테스트 검증 결과] ===")
    if df.empty:
        print("검증 가능한 체결 완료 데이터가 없습니다.")
        return

    total_trades = len(df)
    wins = len(df[df['exit_type'] == '익절(T1)'])
    losses = len(df[df['exit_type'].str.contains('손절')])

    win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0

    df['return_rate'] = 0.0
    for idx, row in df.iterrows():
        if row['exit_type'] == '익절(T1)':
            df.at[idx, 'return_rate'] = (row['target1_p'] / row['buy_p'] - 1) * 100
        elif '손절' in row['exit_type']:
            df.at[idx, 'return_rate'] = (row['stop_p'] / row['buy_p'] - 1) * 100

    avg_return = df['return_rate'].mean()

    print(f"총 체결 건수: {total_trades}건")
    print(f"승리(익절): {wins}건 / 패배(손절): {losses}건")
    print(f"전체 승률: {win_rate:.2f}%")
    print(f"평균 수익률: {avg_return:.2f}%")

if __name__ == "__main__":
    run_backtest()
