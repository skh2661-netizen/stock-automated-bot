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
    df['return_rate'] = 0.0

    for idx, row in df.iterrows():
        if '익절' in row['exit_type']:
            df.at[idx, 'return_rate'] = (row['target1_p'] / row['buy_p'] - 1) * 100
        elif '손절' in row['exit_type']:
            df.at[idx, 'return_rate'] = (row['stop_p'] / row['buy_p'] - 1) * 100
        elif '기간종료' in row['exit_type']:
            if pd.notna(row['d5_close']): # D+5 종가 청산 기준
                df.at[idx, 'return_rate'] = (row['d5_close'] / row['buy_p'] - 1) * 100

    # 1. 전체 성과 요약
    wins = len(df[df['exit_type'].str.contains('익절')])
    win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
    avg_return = df['return_rate'].mean()
    print(f"[전체 성과] 체결: {total_trades}건 | 승률: {win_rate:.2f}% | 평균수익률: {avg_return:.2f}%\n")

    # 2. [추가] 점수 구간별 정밀 분석 (형님 지시사항 반영)
    print("=== [점수 구간별 정밀 분석] ===")
    bins = [0, 79, 84, 100]
    labels = ['75~79점 (상승장 컷)', '80~84점 (중립장 컷)', '85점 이상 (하락장 컷)']
    df['score_group'] = pd.cut(df['score'], bins=bins, labels=labels)

    for group in labels:
        group_df = df[df['score_group'] == group]
        if group_df.empty:
            print(f"- {group}: 데이터 없음")
            continue
        
        g_total = len(group_df)
        g_wins = len(group_df[group_df['exit_type'].str.contains('익절')])
        g_win_rate = (g_wins / g_total) * 100
        g_avg_return = group_df['return_rate'].mean()
        
        print(f"- {group}: {g_total}건 체결 | 승률: {g_win_rate:.2f}% | 평균수익률: {g_avg_return:.2f}%")

if __name__ == "__main__":
    run_backtest()
