import FinanceDataReader as fdr
import pandas as pd

def force_test():
    code = "005930" # 삼성전자
    print(f"=== [디버깅] 005930 5년 데이터 적재 시도 ===")
    
    try:
        df = fdr.DataReader(code, "2021-01-01", "2026-06-15")
        print(f"데이터 로드 성공! 총 행(일) 수: {len(df)}")
        
        if len(df) > 0:
            print("최근 5일간 데이터 미리보기:")
            print(df.tail(5))
            
            # 여기서 신호 조건 강제 검증
            df['MA20'] = df['Close'].rolling(20).mean()
            df['Vol_MA20'] = df['Volume'].rolling(20).mean()
            df['ChangesRatio'] = (df['Close'] / df['Close'].shift(1) - 1) * 100
            
            # 조건: 거래대금 100억 이상, 등락률 3~18%
            df['Amount'] = df['Close'] * df['Volume']
            hits = df[(df['Close'] >= 1000) & (df['Amount'] >= 10_000_000_000) & 
                      (df['ChangesRatio'] >= 3) & (df['ChangesRatio'] <= 18)]
            
            print(f"신호 조건에 부합하는 날짜 개수: {len(hits)}개")
            if len(hits) > 0:
                print("부합하는 첫 3개 날짜:")
                print(hits.head(3).index)
            else:
                print("데이터는 있는데 신호 조건에 맞는 날이 없습니다. 필터를 확인하십시오.")
        
    except Exception as e:
        print(f"데이터 로드 실패: {e}")

if __name__ == "__main__":
    force_test()
