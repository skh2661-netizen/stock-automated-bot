import sqlite3
import pandas as pd
import FinanceDataReader as fdr

def run():
    # 1. 아예 새로운 이름으로 DB 생성 (꼬임 방지)
    conn = sqlite3.connect("final_test.db") 
    
    # 2. 강제 테이블 생성
    conn.execute("CREATE TABLE candidates (unique_key TEXT PRIMARY KEY, date TEXT, code TEXT, name TEXT, entry_success INTEGER, result_status TEXT)")
    
    # 3. 데이터 적재
    krx = fdr.StockListing("KRX").head(50)
    for _, row in krx.iterrows():
        code, name = str(row['Code']).zfill(6), row['Name']
        try:
            df = fdr.DataReader(code, "2026-06-01", "2026-06-15")
            if len(df) > 0:
                conn.execute("INSERT OR IGNORE INTO candidates VALUES (?,?,?,?,?,?)", 
                             (f"TEST_{code}", "2026-06-15", code, name, 1, "종료"))
        except: continue
    
    conn.commit()
    count = conn.execute("SELECT count(*) FROM candidates").fetchone()[0]
    conn.close()
    print(f"=== [성공] 총 {count}개 데이터가 final_test.db에 적재되었습니다. ===")

if __name__ == "__main__":
    run()
