import sqlite3
import pandas as pd
import FinanceDataReader as fdr
import datetime
import time

def run_simulation():
    print("=== [V8.4.3 5년 치 데이터 기반 D+N 수익률 검증 엔진 가동] ===")
    
    # 1. history_builder가 생성한 실제 DB 로드 (수정 완료)
    conn = sqlite3.connect("candidates.db")
    df = pd.read_sql_query("SELECT * FROM candidates", conn)
    conn.close()

    total_trades = len(df)
    if total_trades == 0:
        print("DB에 데이터가 없습니다. history_builder.py를 먼저 실행하십시오.")
        return

    print(f"분석 대상 신호 수: {total_trades}건")
    print("수익률 추적 연산 중... (API 보호를 위해 시간이 소요됩니다)")

    results = []
    
    # 2. 타점별 수익률 추적 (D+1, D+3, D+5)
    for index, row in df.iterrows():
        try:
            entry_date = row['date']
            code = str(row['code']).zfill(6)
            
            # history_builder의 진입 조건: 당일 종가의 0.985
            end_date = (datetime.datetime.strptime(entry_date, "%Y-%m-%d") + datetime.timedelta(days=15)).strftime("%Y-%m-%d")
            
            hist = fdr.DataReader(code, entry_date, end_date)
            if len(hist) < 2: continue
            
            # 진입 당일 종가 대비 0.985 지점을 매수가로 설정
            buy_price = int(hist['Close'].iloc[0] * 0.985)
            if buy_price <= 0: continue
            
            # D+1, D+3, D+5 종가
            d1_close = hist['Close'].iloc[1] if len(hist) > 1 else hist['Close'].iloc[-1]
            d3_close = hist['Close'].iloc[3] if len(hist) > 3 else hist['Close'].iloc[-1]
            d5_close = hist['Close'].iloc[5] if len(hist) > 5 else hist['Close'].iloc[-1]
            
            results.append({
                'd1_yield': (d1_close / buy_price - 1) * 100,
                'd3_yield': (d3_close / buy_price - 1) * 100,
                'd5_yield': (d5_close / buy_price - 1) * 100
            })
            
            # [안전장치] 서버 과부하 및 IP 차단 방지 로직 (1,000건당 0.5초 대기)
            if (index + 1) % 1000 == 0:
                print(f"... {index + 1} / {total_trades} 건 연산 완료")
                time.sleep(0.5) 
                
        except Exception as e:
            continue

    # 3. 최종 최적화 통계 산출
    if not results:
        print("연산 실패. DB 데이터를 확인하십시오.")
        return
        
    res_df = pd.DataFrame(results)
    print("\n=== [보유 기간별 수익률 분포 분석 완료] ===")
    print(f"유효 분석 건수: {len(res_df)}건")
    print(f"D+1 평균 수익률: {res_df['d1_yield'].mean():.2f}%")
    print(f"D+3 평균 수익률: {res_df['d3_yield'].mean():.2f}%")
    print(f"D+5 평균 수익률: {res_df['d5_yield'].mean():.2f}%")
    
    # 가장 효율이 좋은 보유 기간 판별
    best_yield = max(res_df['d1_yield'].mean(), res_df['d3_yield'].mean(), res_df['d5_yield'].mean())
    if best_yield == res_df['d1_yield'].mean(): best_day = "1일"
    elif best_yield == res_df['d3_yield'].mean(): best_day = "3일"
    else: best_day = "5일"
    
    print(f"\n[최적화 결론] 형님의 전략은 '{best_day} 보유' 시 통계적 수익 효율이 가장 높습니다.")

if __name__ == "__main__":
    run_simulation()
