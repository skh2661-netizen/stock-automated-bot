import FinanceDataReader as fdr
import pandas as pd
import sqlite3

DB_PATH = "candidates.db"

def build_history():
    print("=== [V8.4.2 데이터 적재 엔진: 인덱스 교정판] ===")
    krx = fdr.StockListing("KRX").head(100)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    total_signals = 0

    for _, row in krx.iterrows():
        code, name = str(row['Code']).zfill(6), row['Name']
        df = fdr.DataReader(code, "2021-01-01", "2026-06-15")
        
        # [핵심 수정] 인덱스를 강제로 Datetime으로 변환
        df.index = pd.to_datetime(df.index)
        
        if len(df) < 30: continue
        
        df['MA20'] = df['Close'].rolling(20).mean()
        df['Vol_MA20'] = df['Volume'].rolling(20).mean()
        df['ChangesRatio'] = (df['Close'] / df['Close'].shift(1) - 1) * 100
        
        # 신호 필터링: 거래대금 50억, 등락률 3~18%
        hits = df[(df['Close'] >= 1000) & (df['ChangesRatio'] >= 3) & (df['ChangesRatio'] <= 18)]
        
        for date_idx, row_hit in hits.iterrows():
            loc_idx = df.index.get_loc(date_idx)
            if loc_idx + 1 >= len(df): continue
            
            # 조건: 거래량 비율 1.0배
            vol_ratio = row_hit['Volume'] / row_hit['Vol_MA20'] if row_hit['Vol_MA20'] > 0 else 0
            if vol_ratio < 1.0: continue
            
            # 성과 판정
            buy_p = int(row_hit['Close'] * 0.985)
            d1 = df.iloc[loc_idx + 1]
            if d1['Low'] <= buy_p:
                conn.execute("INSERT OR IGNORE INTO candidates (unique_key, date, code, name, entry_success, result_status) VALUES (?,?,?,?,?,?)",
                             (f"{date_idx.strftime('%Y-%m-%d')}_{code}", date_idx.strftime("%Y-%m-%d"), code, name, 1, "종료"))
                total_signals += 1
                
    conn.commit()
    conn.close()
    print(f"=== [작전 종료] 적재된 신호 개수: {total_signals}개 ===")

if __name__ == "__main__":
    build_history()
