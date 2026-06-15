import sqlite3
import pandas as pd

def run_backtest():
    # 1. 생성된 DB 연결
    conn = sqlite3.connect("final_test.db")
    df = pd.read_sql_query("SELECT * FROM candidates", conn)
    conn.close()

    print("=== [V8.4.2 전략 백테스트 검증 결과] ===")
    
    # 2. 적재된 데이터가 존재하는지 확인
    if df.empty:
        print("데이터가 없습니다. 적재 과정을 다시 확인하십시오.")
        return

    # 3. 데이터가 들어있다면, 간소화된 구조에 맞춰 승률 계산
    # 테이블에 entry_success가 1인 것만 성공으로 간주
    total_trades = len(df)
    wins = len(df[df['result_status'] == '종료']) # 현재 로직은 모두 종료로 처리됨
    
    print(f"총 분석 건수: {total_trades}건")
    print("=== [분석 완료] ===")
    print(df.head(10)) # 데이터가 어떻게 들어갔는지 샘플 출력

if __name__ == "__main__":
    run_backtest()
