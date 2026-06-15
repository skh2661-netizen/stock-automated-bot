import FinanceDataReader as fdr
import pandas as pd

def debug_check():
    print("=== [디버깅 시작] KRX 상장종목 로드 및 데이터 확인 ===")
    krx = fdr.StockListing("KRX").head(100)
    print(f"로드된 종목 수: {len(krx)}개")
    
    found_any = False
    for _, row in krx.iterrows():
        code = str(row['Code']).zfill(6)
        df = fdr.DataReader(code, "2026-06-01", "2026-06-15") # 최근 2주만 짧게 확인
        
        if len(df) > 0:
            found_any = True
            # 거래대금 계산
            df['Amount'] = df['Close'] * df['Volume']
            # 신호 조건 로그 (단 1건이라도 조건 맞는지 확인)
            hits = df[(df['Close'] >= 1000) & (df['Amount'] >= 1_000_000_000)]
            if not hits.empty:
                print(f"[성공] {row['Name']}({code}) 최근 2주간 신호 가능성 있음: {len(hits)}건")
                break
    
    if not found_any:
        print("[실패] 데이터를 전혀 가져오지 못했습니다. 네트워크나 Fdr 모듈을 점검하십시오.")

if __name__ == "__main__":
    debug_check()
