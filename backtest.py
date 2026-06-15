import sqlite3
import pandas as pd
import FinanceDataReader as fdr
import datetime

def run_simulation():
    # 1. DB 로드
    conn = sqlite3.connect("final_test.db")
    df = pd.read_sql_query("SELECT * FROM candidates", conn)
    conn.close()

    print("=== [V8.4.2 5년 치 데이터 정밀 시뮬레이션 가동] ===")
    
    if df.empty:
        print("데이터가 없습니다. 적재 과정을 확인하십시오.")
        return

    total_trades = len(df)
    print(f"분석 대상 타점 수: {total_trades}건")
    print("수익률 백테스트 연산 중... (시간이 소요될 수 있습니다)")

    results = []
    
    # 2. 개별 타점 수익률 추적 (D+1 ~ D+5)
    for index, row in df.iterrows():
        try:
            # DB 구조에 맞게 컬럼명 매핑 (date, code, entry_price 등)
            entry_date = row['date']
            code = str(row['code']).zfill(6)
            buy_price = float(row.get('buy_p', row.get('entry_price', 0))) # 호환성
            
            if buy_price <= 0: continue
            
            # 진입일 이후 10일치 데이터만 로드하여 연산 속도 확보
            end_date = (datetime.datetime.strptime(entry_date, "%Y-%m-%d") + datetime.timedelta(days=15)).strftime("%Y-%m-%d")
            hist = fdr.DataReader(code, entry_date, end_date)
            
            if len(hist) < 2: continue # 거래 정지 등 예외 처리
            
            # D+1, D+3, D+5 종가 기준 수익률 계산
            d1_close = hist['Close'].iloc[1] if len(hist) > 1 else hist['Close'].iloc[-1]
            d3_close = hist['Close'].iloc[3] if len(hist) > 3 else hist['Close'].iloc[-1]
            d5_close = hist['Close'].iloc[5] if len(hist) > 5 else hist['Close'].iloc[-1]
            
            results.append({
                'code': code,
                'd1_yield': (d1_close / buy_price - 1) * 100,
                'd3_yield': (d3_close / buy_price - 1) * 100,
                'd5_yield': (d5_close / buy_price - 1) * 100
            })
            
            # 진행률 표시 (1000건 단위)
            if (index + 1) % 1000 == 0:
                print(f"... {index + 1}/{total_trades} 건 연산 완료")
                
        except Exception as e:
            continue

    # 3. 최종 통계 산출
    if not results:
        print("수익률 연산에 실패했습니다. DB의 날짜/가격 데이터를 확인하십시오.")
        return
        
    res_df = pd.DataFrame(results)
    
    print("\n=== [시뮬레이션 분석 완료] ===")
    print(f"총 유효 분석 건수: {len(res_df)}건")
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
