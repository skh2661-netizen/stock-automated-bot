import FinanceDataReader as fdr
import pandas as pd
import sqlite3
import os

DB_PATH = "candidates.db"

def init_db():
    # 데이터베이스 연결 및 테이블 강제 생성
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS candidates") # 이전 꼬인 테이블 삭제
    conn.execute("""
        CREATE TABLE candidates (
            unique_key TEXT PRIMARY KEY,
            date TEXT, code TEXT, name TEXT, 
            entry_success INTEGER, result_status TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("=== [시스템] 테이블 초기화 완료 ===")

def build_history():
    init_db() # 테이블 먼저 만들고 시작
    conn = sqlite3.connect(DB_PATH)
    krx = fdr.StockListing("KRX").head(100)
    total_signals = 0

    for _, row in krx.iterrows():
        code, name = str(row['Code']).zfill(6), row['Name']
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
            
            buy_p = int(row_hit['Close'] * 0.985)
            if df.iloc[loc_idx + 1]['Low'] <= buy_p:
                conn.execute("INSERT OR IGNORE INTO candidates VALUES (?,?,?,?,?,?)",
                             (f"{date_idx.strftime('%Y-%m-%d')}_{code}", date_idx.strftime("%Y-%m-%d"), code, name, 1, "종료"))
                total_signals += 1
                
    conn.commit()
    conn.close()
    print(f"=== [작전 종료] 총 {total_signals}개 신호 적재 완료 ===")

if __name__ == "__main__":
    build_history()
