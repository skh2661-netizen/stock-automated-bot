import FinanceDataReader as fdr
import pandas as pd
import sqlite3

DB_PATH = "candidates.db"

def build_history():
    print("=== [V8.4.2 데이터 적재 엔진: 원샷 생성 모드] ===")
    
    # 1. 연결과 동시에 테이블 생성 (DB가 없으면 생성, 있으면 열기)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS candidates (unique_key TEXT PRIMARY KEY, date TEXT, code TEXT, name TEXT, entry_success INTEGER, result_status TEXT)")
    conn.commit()
    
    krx = fdr.StockListing("KRX").head(100)
    total_signals = 0

    for _, row in krx.iterrows():
        code, name = str(row['Code']).zfill(6), row['Name']
        try:
            df = fdr.DataReader(code, "2021-01-01", "2026-06-15")
            df.index = pd.to_datetime(df.index)
            if len(df) < 30: continue
            
            df['MA20'] = df['Close'].rolling(20).mean()
            df['Vol_MA20'] = df['Volume'].rolling(20).mean()
            df['ChangesRatio'] = (df['Close'] / df['Close'].shift(1) - 1) * 100
            
            hits = df[(df['Close'] >= 1000) & (df['ChangesRatio'] >= 3) & (df['ChangesRatio'] <= 18)]
            for date_idx, row_hit in hits.iterrows():
                loc_idx = df.index.get_loc(date_idx)
                if loc_idx + 1 >= len(df): continue
                
                vol_ratio = row_hit['Volume'] / row_hit['Vol_MA20'] if row_hit['Vol_MA20'] > 0 else 0
                if vol_ratio < 1.0: continue
                
                if df.iloc[loc_idx + 1]['Low'] <= int(row_hit['Close'] * 0.985):
                    conn.execute("INSERT OR IGNORE INTO candidates VALUES (?,?,?,?,?,?)",
                                 (f"{date_idx.strftime('%Y-%m-%d')}_{code}", date_idx.strftime("%Y-%m-%d"), code, name, 1, "종료"))
                    total_signals += 1
        except: continue
                
    conn.commit()
    conn.close()
    print(f"=== [작전 종료] 적재 완료. 신호 개수: {total_signals}개 ===")

if __name__ == "__main__":
    build_history()
