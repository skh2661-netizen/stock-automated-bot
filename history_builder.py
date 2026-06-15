import FinanceDataReader as fdr
import pandas as pd
import sqlite3
from datetime import datetime
from scoring import calculate_score

DB_PATH = "candidates.db"
START_DATE = "2021-01-01"
END_DATE = "2026-06-15"
# [완화] 최소 거래대금 50억, 가격 1000원으로 조정
MIN_PRICE, MIN_AMOUNT = 1000, 5_000_000_000

def connect():
    return sqlite3.connect(DB_PATH, timeout=30)

def build_history():
    print(f"=== [V8.4.2 5년 타임머신 가동 (필터 완화)] ===")
    krx = fdr.StockListing("KRX").head(100) # 상위 100종목
    
    conn = connect()
    total_signals = 0

    for _, row in krx.iterrows():
        code, name = str(row['Code']).zfill(6), row['Name']
        try:
            df = fdr.DataReader(code, START_DATE, END_DATE)
            if len(df) < 30: continue
            
            df['MA20'] = df['Close'].rolling(20).mean()
            df['Vol_MA20'] = df['Volume'].rolling(20).mean()
            df['ChangesRatio'] = (df['Close'] / df['Close'].shift(1) - 1) * 100
            
            # [완화] 등락률 2%~20%로 확대
            signal_candidates = df[(df['Close'] >= MIN_PRICE) & (df['ChangesRatio'] >= 2) & (df['ChangesRatio'] <= 20)]
            
            for i in range(len(signal_candidates)):
                date_idx = signal_candidates.index[i]
                loc_idx = df.index.get_loc(date_idx)
                if loc_idx + 1 >= len(df): continue
                
                curr = df.iloc[loc_idx]
                # [완화] 거래량 비율 1.0배 이상만 돼도 통과
                vol_ratio = curr['Volume'] / curr['Vol_MA20'] if curr['Vol_MA20'] > 0 else 0
                if vol_ratio < 1.0: continue
                
                buy_p, target1, stop = int(curr['Close'] * 0.985), int(curr['Close'] * 1.023), int(curr['Close'] * 0.970)
                
                d1_data = df.iloc[loc_idx + 1]
                entry_success = 1 if d1_data['Low'] <= buy_p else 0
                exit_type, result_status = "미체결", "종료"
                
                if entry_success == 1:
                    max_forward = min(loc_idx + 6, len(df))
                    for f_idx in range(loc_idx + 1, max_forward):
                        step = f_idx - loc_idx
                        f_curr = df.iloc[f_idx]
                        if f_curr['Low'] <= stop and f_curr['High'] >= target1: exit_type, result_status = "동시도달", "종료"
                        elif f_curr['High'] >= target1: exit_type, result_status = "익절", "종료"
                        elif f_curr['Low'] <= stop: exit_type, result_status = "손절", "종료"
                        elif step == 5: exit_type, result_status = "기간종료", "종료"

                conn.execute("INSERT OR IGNORE INTO candidates (unique_key, date, code, name, score, buy_p, target1_p, stop_p, entry_success, exit_type, result_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (f"{date_idx.strftime('%Y-%m-%d')}_{code}_HIST", date_idx.strftime("%Y-%m-%d"), code, name, 80, buy_p, target1, stop, entry_success, exit_type, result_status))
                total_signals += 1
        except Exception: continue
            
    conn.commit()
    conn.close()
    print(f"=== [작전 종료] 총 {total_signals}개 신호 적재 완료 ===")

if __name__ == "__main__":
    build_history()
