import FinanceDataReader as fdr
import pandas as pd
import asyncio, datetime, pytz, time
import requests
import sqlite3
import os
from scoring import calculate_breakout_score, calculate_close_score, calculate_preopen_score, get_conviction_score, get_prime_score
from database import save_candidate, DB_PATH

MIN_PRICE, MIN_AMOUNT, MAX_CANDIDATES = 1000, 15_000_000_000, 15

def safe_json_decode(res):
    try:
        text = res.text.strip()
        if text.startswith("<") or "text/html" in res.headers.get("Content-Type", "").lower(): return None
        return res.json()
    except Exception: return None

def get_krx_retry():
    for _ in range(2):
        try:
            krx = fdr.StockListing("KRX")
            if not krx.empty:
                if "Symbol" in krx.columns: krx.rename(columns={"Symbol": "Code"}, inplace=True)
                elif "ISU_CD" in krx.columns: krx.rename(columns={"ISU_CD": "Code"}, inplace=True)
                if "Code" in krx.columns:
                    krx.rename(columns={"ChagesRatio": "ChangesRatio", "ChgRate": "ChangesRatio"}, inplace=True)
                    krx = krx.loc[:, ~krx.columns.duplicated()].reset_index(drop=True)
                    krx["ChangesRatio"] = pd.to_numeric(krx["ChangesRatio"], errors="coerce").fillna(0)
                    return krx
        except Exception: time.sleep(1)
    
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        df_list = []
        for market in ["KOSPI", "KOSDAQ"]:
            url = f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page=1&pageSize=2500"
            res = requests.get(url, headers=headers, timeout=5)
            data = safe_json_decode(res)
            if not data: continue
            stocks = data.get('stocks', [])
            if not stocks: continue
            df = pd.DataFrame(stocks)
            df.rename(columns={'itemCode': 'Code', 'stockName': 'Name', 'closePrice': 'Close', 'fluctuationsRatio': 'ChangesRatio', 'accumulatedTradingVolume': 'Volume'}, inplace=True)
            for col in ['Close', 'Volume']:
                df[col] = df[col].astype(str).str.replace(',', '')
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            df['ChangesRatio'] = pd.to_numeric(df['ChangesRatio'], errors='coerce').fillna(0)
            df_list.append(df)
        if df_list: return pd.concat(df_list, ignore_index=True)
    except Exception: pass

    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            cache_df = pd.read_sql_query("SELECT code AS Code, name AS Name, price AS Close, chg AS ChangesRatio FROM candidates WHERE date = (SELECT max(date) FROM candidates)", conn)
            conn.close()
            if not cache_df.empty: return cache_df
        except Exception: pass
    return pd.DataFrame(columns=['Code', 'Name', 'Close', 'ChangesRatio', 'Amount', 'Volume'])

def remove_bad_targets(df):
    if "Name" not in df.columns: return df
    pattern = r'스팩|ETF|ETN|우$|우[A-Z]$|[0-9]+우[A-Z]?$|제[0-9]+호'
    return df[~df['Name'].str.contains(pattern, regex=True, na=False)]

def get_market_indices():
    try:
        kst = pytz.timezone("Asia/Seoul")
        start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=40)).strftime("%Y-%m-%d")
        kospi = fdr.DataReader("KS11", start_date)
        kosdaq = fdr.DataReader("KQ11", start_date)
        kp_1d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-2]) - 1) * 100
        kd_1d = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-2]) - 1) * 100
        return round(kp_1d, 2), round(kd_1d, 2)
    except: return 0.0, 0.0

async def scan_market(run_type="OPEN_SCAN"):
    try:
        kp_1d, kd_1d = get_market_indices()
        krx = remove_bad_targets(get_krx_retry())
        if krx.empty or "Code" not in krx.columns:
            return {"market": {"mode": run_type, "kospi": kp_1d, "kosdaq": kd_1d}, "stats": {"data_error": True}, "candidates": []}
            
        krx['Close'] = pd.to_numeric(krx['Close'], errors='coerce')
        krx['Volume'] = pd.to_numeric(krx['Volume'], errors='coerce')
        krx['Amount'] = (krx['Close'] * krx['Volume']).fillna(0)
        krx['ChangesRatio'] = pd.to_numeric(krx['ChangesRatio'], errors='coerce').fillna(0)
        
        candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & (krx['ChangesRatio'] >= 1) & (krx['ChangesRatio'] <= 18)].sort_values("Amount", ascending=False).head(100)
        results = []
        
        for _, row in candidates.iterrows():
            changes = float(row['ChangesRatio'])
            hist = fdr.DataReader(str(row['Code']).zfill(6), datetime.datetime.now().strftime("%Y-%m-%d"))
            if len(hist) < 25: continue
            
            curr = hist.iloc[-1]
            ma5 = hist['Close'].rolling(5).mean().iloc[-1]
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            vr = curr['Volume'] / (hist['Volume'].rolling(20).mean().iloc[-1] + 1)
            ma_gap = (curr['Close'] - ma20) / ma20 * 100
            cp_val = (curr['Close'] - curr['Low']) / (curr['High'] - curr['Low'] + 0.0001) * 100
            
            # [V8.8.4] 방어: 가변 손절 ATR 연산
            tr = pd.concat([hist['High'] - hist['Low'], (hist['High'] - hist['Close'].shift(1)).abs(), (hist['Low'] - hist['Close'].shift(1)).abs()], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            volatility_stop = int(curr['Close'] - (atr * 1.5))
            
            # [V8.8.4] 방어: 5MA 추세 확인
            is_ma5_rising = ma5 > hist['Close'].rolling(5).mean().shift(1).iloc[-1]
            
            prime_score = get_prime_score(changes, changes, changes, 1.0, True)
            score = calculate_close_score(row['Amount'], vr, changes, 0, 0, cp_val, changes, 1, ma_gap)
            
            candidate_type = "NONE"
            if (score >= 80) and (prime_score >= 85) and (ma_gap <= 15) and is_ma5_rising: candidate_type = "STRONG_BUY"
            elif (score >= 65) and (ma_gap <= 15) and is_ma5_rising: candidate_type = "BUY"
            elif (score >= 60) and (15 < ma_gap <= 25): candidate_type = "SETUP"
            elif (prime_score >= 70) and (ma_gap > 25): candidate_type = "WATCH"

            if candidate_type == "NONE": continue
                
            results.append({
                "code": str(row['Code']).zfill(6), "name": row['Name'], "score": score, "price": int(curr['Close']),
                "buy_p": int(curr['Close']*0.985), "stop_p": max(int(curr['Close']*0.95), volatility_stop),
                "t1": int(curr['Close']*1.05), "t2": int(curr['Close']*1.10),
                "ma_gap": round(ma_gap, 2), "prime_score": prime_score, "type": candidate_type
            })
            
        return {"market": {"mode": run_type, "kospi": kp_1d, "kosdaq": kd_1d}, "stats": {"total": total_universe, "final": len(results), "data_error": False}, "candidates": results}
    except Exception: return {"stats": {"data_error": True}, "candidates": []}
