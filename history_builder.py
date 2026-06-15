import FinanceDataReader as fdr
import pandas as pd
import sqlite3
import time
from datetime import datetime, timedelta
from scoring import calculate_score

DB_PATH = "candidates.db"
START_DATE = "2021-01-01"
END_DATE = "2026-06-15"
MIN_PRICE, MIN_AMOUNT = 2000, 10_000_000_000

def connect():
    return sqlite3.connect(DB_PATH, timeout=30)

def build_history():
    print(f"=== [V8.4.2 5년 타임머신 가동] {START_DATE} ~ {END_DATE} ===")
    
    # 1. 시장 데이터 사전 로드 (벤치마크용)
    print("[1/3] KOSPI 지수 사전 로드 중...")
    market_df = fdr.DataReader("KS11", START_DATE, END_DATE)
    market_df['M_Change'] = (market_df['Close'] / market_df['Close'].shift(5) - 1) * 100
    
    # 2. 상장 종목 로드
    print("[2/3] KRX 상장 종목 로드 중...")
    krx = fdr.StockListing("KRX")
    pattern = '스팩|ETF|ETN|우$|우[A-Z]$|제[0-9]+호'
    krx = krx[~krx['Name'].str.contains(pattern, regex=True, na=False)]
    
    conn = connect()
    total_symbols = len(krx)
    
    print(f"[3/3] 총 {total_symbols}개 종목 5년치 딥스캔 시작 (약 30분~1시간 소요)")
    
    # 프로그레스 트래킹 변수
    processed = 0
    total_signals = 0

    for _, row in krx.iterrows():
        code = str(row['Code']).zfill(6)
        name = row['Name']
        processed += 1
        
        if processed % 100 == 0:
            print(f"... 진행률: {processed}/{total_symbols} | 현재 누적 신호: {total_signals}개")

        try:
            # 종목별 5년치 데이터 한 번에 로드
            df = fdr.DataReader(code, START_DATE, END_DATE)
            if len(df) < 30: continue # 상장 직후 종목 패스
            
            # 벡터 연산으로 지표 일괄 계산 (속도 최적화)
            df['MA20'] = df['Close'].rolling(20).mean()
            df['Vol_MA20'] = df['Volume'].rolling(20).mean()
            df['Amount'] = df['Close'] * df['Volume']
            df['ChangesRatio'] = (df['Close'] / df['Close'].shift(1) - 1) * 100
            
            # 조건 1차 필터링 (빠른 탐색용)
            signal_candidates = df[
                (df['Close'] >= MIN_PRICE) & 
                (df['Amount'] >= MIN_AMOUNT) & 
                (df['ChangesRatio'] >= 3) & 
                (df['ChangesRatio'] <= 18)
            ]
            
            # 1차 필터를 통과한 날짜(시점)에 대해서만 정밀 시뮬레이션
            for i in range(len(signal_candidates)):
                # iloc 인덱스를 찾기 위해 날짜 기준으로 매핑
                date_idx = signal_candidates.index[i]
                loc_idx = df.index.get_loc(date_idx)
                
                # 미래 데이터(D+1~D+5)가 없으면(최근일이면) 패스
                if loc_idx + 1 >= len(df): continue
                
                curr = df.iloc[loc_idx]
                prev_6 = df.iloc[loc_idx - 5] if loc_idx >= 5 else None
                if prev_6 is None or pd.isna(curr['MA20']) or pd.isna(curr['Vol_MA20']): continue
                
                # V8.4.2 필터 재현
                ma_gap = (curr['Close'] - curr['MA20']) / curr['MA20'] * 100
                vol_ratio = curr['Volume'] / curr['Vol_MA20'] if curr['Vol_MA20'] > 0 else 0
                upper_shadow = ((curr['High'] - max(curr['Open'], curr['Close'])) / curr['High'] * 100)
                candle_pos = ((curr['Close'] - curr['Low']) / (curr['High'] - curr['Low']) * 100) if curr['High'] > curr['Low'] else 0
                
                if ma_gap < 0 or vol_ratio < 1.3 or upper_shadow > 5: continue
                
                five_change = (curr['Close'] / prev_6['Close'] - 1) * 100
                m_change = market_df.loc[date_idx, 'M_Change'] if date_idx in market_df.index else 0
                
                # 점수 계산 (과거는 리스크 레벨 추적이 어려우므로 기본 1로 가정하여 보수적 채점)
                score = calculate_score(curr['Amount'], vol_ratio, curr['ChangesRatio'], 
                                        upper_shadow, ma_gap, candle_pos, (five_change - m_change), five_change, 1)
                
                if score < 75: continue # 75점 이상만 적재 (나중에 backtest에서 구간별 분석)
                
                # === [미래 성과(D+1~D+5) 즉시 추적] ===
                buy_p, target1, stop = int(curr['Close'] * 0.985), int(curr['Close'] * 1.023), int(curr['Close'] * 0.970)
                
                d1_data = df.iloc[loc_idx + 1]
                d1_h, d1_l, d1_c = int(d1_data['High']), int(d1_data['Low']), int(d1_data['Close'])
                
                entry_success = 1 if d1_l <= buy_p else 0
                exit_type, result_status = "미체결", "종료"
                
                d3_h, d3_l, d3_c = None, None, None
                d5_h, d5_l, d5_c = None, None, None

                if entry_success == 1:
                    max_forward = min(loc_idx + 6, len(df))
                    for f_idx in range(loc_idx + 1, max_forward):
                        step = f_idx - loc_idx
                        f_curr = df.iloc[f_idx]
                        c_h, c_l, c_c = int(f_curr['High']), int(f_curr['Low']), int(f_curr['Close'])
                        
                        if step == 3: d3_h, d3_l, d3_c = c_h, c_l, c_c
                        if step == 5: d5_h, d5_l, d5_c = c_h, c_l, c_c
                        
                        if result_status == "종료": continue
                        
                        if c_l <= stop and c_h >= target1: exit_type, result_status = f"동시도달(손절/D+{step})", "종료"
                        elif c_h >= target1: exit_type, result_status = f"익절(T1/D+{step})", "종료"
                        elif c_l <= stop: exit_type, result_status = f"손절(D+{step})", "종료"
                        elif step == 5: exit_type, result_status = "기간종료(D+5)", "종료"

                # DB 기록
                run_type = "HISTORY_SCAN"
                date_str = date_idx.strftime("%Y-%m-%d")
                unique_key = f"{date_str}_{code}_{run_type}"
                
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO candidates 
                        (unique_key, date, timestamp, run_type, strategy_version, score_version, 
                         code, name, score, buy_p, target1_p, target2_p, stop_p, 
                         entry_success, exit_type, result_status, 
                         d1_high, d1_low, d1_close, d3_high, d3_low, d3_close, d5_high, d5_low, d5_close) 
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (unique_key, date_str, "00:00:00", run_type, "V8.4.2", "SCORE_A",
                          code, name, score, buy_p, target1, int(curr['Close'] * 1.063), stop,
                          entry_success, exit_type, result_status,
                          d1_h, d1_l, d1_c, d3_h, d3_l, d3_c, d5_h, d5_l, d5_c))
                    total_signals += 1
                except: pass

    conn.commit()
    conn.close()
    print(f"=== [작전 종료] 총 {total_signals}개의 과거 백데이터가 DB에 완벽히 적재되었습니다. ===")

if __name__ == "__main__":
    build_history()
