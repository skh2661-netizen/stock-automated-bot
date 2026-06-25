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
    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    risk_level = 1
    kp_1d, kd_1d = get_market_indices()
    
    krx = remove_bad_targets(get_krx_retry())
    if krx.empty or "Code" not in krx.columns:
        return {"market": {"mode": run_type, "kospi": kp_1d, "kosdaq": kd_1d}, "stats": {"data_error": True}, "candidates": []}
        
    krx['Close'] = pd.to_numeric(krx['Close'], errors='coerce')
    krx['Volume'] = pd.to_numeric(krx['Volume'], errors='coerce')
    krx['Amount'] = (krx['Close'] * krx['Volume']).fillna(0)
    krx['ChangesRatio'] = pd.to_numeric(krx['ChangesRatio'], errors='coerce').fillna(0)
    
    total_universe = len(krx)
    if run_type == "TEST":
        candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT)].sort_values("Amount", ascending=False).head(150)
    else:
        candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & 
                         (krx['ChangesRatio'] >= 1) & (krx['ChangesRatio'] <= 18)].sort_values("Amount", ascending=False).head(100)
    
    results = []
    
    for _, row in candidates.iterrows():
        changes = float(row['ChangesRatio'])
        code = str(row['Code']).zfill(6)
        
        hist = fdr.DataReader(code, start_date)
        if len(hist) < 25: continue
        
        curr = hist.iloc[-1]
        ma20 = hist['Close'].rolling(20).mean().iloc[-1]
        vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
        vr = curr['Volume'] / (vol_ma + 1)
        ma_gap = (curr['Close'] - ma20) / ma20 * 100
        shadow_ratio = (curr['High'] - curr['Close']) / (curr['High'] - curr['Low'] + 0.0001)
        cp_val = (curr['Close'] - curr['Low']) / (curr['High'] - curr['Low'] + 0.0001) * 100
        
        if run_type == "CLOSE_BET":
            is_mega_cap = row['Amount'] >= 100_000_000_000
            is_solid_candle = cp_val >= 70
            if is_mega_cap and is_solid_candle: heat_limit = 35 
            else: heat_limit = 25 
        else:
            heat_limit = 35 if row['Amount'] >= 100_000_000_000 else 25
            
        is_overheated = ma_gap > heat_limit
        rs_1d = changes - kp_1d
        
        hist['Amt'] = hist['Close'] * hist['Volume']
        amount_prev20 = hist['Amt'].iloc[-21:-1].mean() if len(hist) >= 21 else hist['Amt'].head(20).mean()
        amount_strength = min(round((hist['Amt'].tail(6).iloc[:-1].mean() if len(hist) >= 6 else 0) / (amount_prev20 + 1), 2), 5.0)
        
        norm_conviction = get_conviction_score(rs_1d, row['Amount'], vr, risk_level, ma_gap, cp_val)
        prime_score = get_prime_score(rs_1d, rs_1d, rs_1d, amount_strength, True)
        
        if run_type == "PRE_OPEN": score = calculate_preopen_score(row['Amount'], vr, changes, shadow_ratio, cp_val, rs_1d, risk_level)
        elif "BREAKOUT" in run_type: score = calculate_breakout_score(row['Amount'], vr, changes, rs_1d, risk_level)
        else: score = calculate_close_score(row['Amount'], vr, changes, shadow_ratio, 0, cp_val, rs_1d, risk_level, ma_gap)
            
        heat_score = max(0, 100 - max(ma_gap, 0))
        prime_final = (prime_score * 0.5) + (score * 0.3) + (heat_score * 0.2)
        
        candidate_type = "NONE"
        if is_overheated and prime_score >= 70: candidate_type = "WATCH" 
        elif not is_overheated and score >= 55: candidate_type = "ENTRY"
        elif prime_score >= 75: candidate_type = "LEADER" 

        if candidate_type == "NONE" and run_type != "TEST": continue

        # [V8.8] 과열도 기반 동적 매수 타점 교정 (-8% ~ -1.5%)
        if ma_gap > 20:
            buy_p = int(curr['Close'] * 0.92)
        elif ma_gap > 10:
            buy_p = int(curr['Close'] * 0.96)
        else:
            buy_p = int(curr['Close'] * 0.985)
            
        results.append({
            "code": code, "name": row['Name'], "score": score, "price": int(curr['Close']),
            "chg": round(changes, 2), "buy_p": buy_p, "ma_gap": round(ma_gap, 2), 
            "rs": round(rs_1d, 2), "amount": int(row['Amount']),
            "conviction": norm_conviction, "prime_score": prime_score,
            "prime_final": round(prime_final, 1),
            "type": candidate_type, "is_overheated": is_overheated
        })
            
    type_priority = {"ENTRY": 3, "LEADER": 2, "WATCH": 1, "NONE": 0}
    results = sorted(results, key=lambda x: (type_priority.get(x['type'], 0), x['prime_final'], x['amount']), reverse=True)[:MAX_CANDIDATES]
    
    return {
        "market": {"mode": run_type, "kospi": kp_1d, "kosdaq": kd_1d},
        "stats": {"total": total_universe, "final": len(results), "data_error": False},
        "candidates": results
    }
