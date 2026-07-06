import FinanceDataReader as fdr
import pandas as pd
import asyncio, datetime, pytz, time, requests, sqlite3, os, traceback
from concurrent.futures import ThreadPoolExecutor
from scoring import calculate_breakout_score, calculate_close_score, calculate_preopen_score, get_conviction_score, get_prime_score
from database import save_candidate_history, DB_PATH

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
    return pd.DataFrame(columns=['Code', 'Name', 'Close', 'ChangesRatio', 'Amount', 'Volume'])

def remove_bad_targets(df):
    if df.empty or "Name" not in df.columns: return df
    pattern = r'스팩|ETF|ETN|우$|우[A-Z]$|[0-9]+우[A-Z]?$|제[0-9]+호'
    return df[~df['Name'].astype(str).str.contains(pattern, regex=True, na=False)]

def get_market_indices():
    try:
        kst = pytz.timezone("Asia/Seoul")
        start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=40)).strftime("%Y-%m-%d")
        kospi, kosdaq = fdr.DataReader("KS11", start_date), fdr.DataReader("KQ11", start_date)
        kp_1d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-2]) - 1) * 100
        kd_1d = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-2]) - 1) * 100
        kp_5d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-6]) - 1) * 100
        kp_20d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-21]) - 1) * 100
        return round(kp_1d, 2), round(kd_1d, 2), round(kp_5d, 2), round(kp_20d, 2)
    except: return 0.0, 0.0, 0.0, 0.0

def fetch_history(code, start_date):
    for _ in range(3):
        try:
            df = fdr.DataReader(code, start_date)
            if not df.empty: return code, df
        except: time.sleep(1)
    return code, None

async def generate_raw_candidates(run_type="OPEN_SCAN"):
    try:
        kst = pytz.timezone("Asia/Seoul")
        scan_datetime = datetime.datetime.now(kst).strftime("%Y-%m-%d %H:%M")
        start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
        
        kp_1d, kd_1d, kp_5d, kp_20d = get_market_indices()
        
        risk_level = 3 if kp_1d <= -3.0 else (2 if kp_1d <= -1.0 else 1)
        krx = remove_bad_targets(get_krx_retry())
        
        if krx.empty: return {"stats": {"data_error": True}, "raw_data": []}
        
        krx['Close'], krx['Volume'] = pd.to_numeric(krx['Close'], errors='coerce'), pd.to_numeric(krx['Volume'], errors='coerce')
        krx['Amount'] = (krx['Close'] * krx['Volume']).fillna(0)
        
        candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & (krx['ChangesRatio'] >= 1)].sort_values("Amount", ascending=False).head(100)
        
        raw_results = []
        codes = candidates['Code'].apply(lambda x: str(x).zfill(6)).tolist()
        with ThreadPoolExecutor(max_workers=5) as ex: histories = dict(ex.map(lambda c: fetch_history(c, start_date), codes))
        
        for _, row in candidates.iterrows():
            code, changes = str(row['Code']).zfill(6), float(row['ChangesRatio'])
            hist = histories.get(code)
            if hist is None or len(hist) < 30: continue
            
            hist = hist.copy()
            hist['Amt'] = hist['Close'] * hist['Volume']
            curr, ma20 = hist.iloc[-1], hist['Close'].rolling(20).mean().iloc[-1]
            ma_gap = ((curr['Close'] - ma20) / ma20 * 100) if ma20 > 0 else 0
            
            stock_20d_return = ((curr['Close'] / hist['Close'].iloc[-21]) - 1) * 100
            rs_20d = round(stock_20d_return - kp_20d, 2)
            
            stock_5d_return = ((curr['Close'] / hist['Close'].iloc[-6]) - 1) * 100
            rs_5d = round(stock_5d_return - kp_5d, 2)
            
            rs_1d = round(changes - kp_1d, 2)
            
            amt_s = min(round((hist['Amt'].tail(6).iloc[:-1].mean() / (hist['Amt'].iloc[-21:-1].mean() + 1)), 2), 5.0)
            
            avg_vol_20d = hist['Volume'].rolling(20).mean().iloc[-2]
            vr = round(curr['Volume'] / avg_vol_20d, 2) if avg_vol_20d > 0 else 1.0
            
            high_20d = hist['High'].rolling(20).max().iloc[-1]
            low_20d = hist['Low'].rolling(20).min().iloc[-1]
            cp = round(((curr['Close'] - low_20d) / (high_20d - low_20d)) * 100, 1) if high_20d > low_20d else 50.0
            
            ps = get_prime_score(rs_1d, rs_5d, rs_20d, amt_s, True)
            score = calculate_close_score(row['Amount'], vr, changes, 0, 0, cp, rs_1d, risk_level, ma_gap)
            conv = get_conviction_score(rs_1d, row['Amount'], vr, risk_level, ma_gap, cp)
            prime_final = round((ps * 0.35 + score * 0.30 + conv * 0.15 + max(0, 100 - (ma_gap * 2)) * 0.20), 1)
            
            # [신규] 형님이 요청하신 핵심 수치 컴포넌트 강제 출력 로그
            print(f"📊 [SCANNER AUDIT] {row['Name']:<10} | PS={ps:<3} | Score={score:<3} | Conv={conv:<3} | Final={prime_final:<5} | RS20={rs_20d:<6.2f} | VR={vr:<5.2f} | CP={cp:<5.1f}")
            
            raw_results.append({
                "code": code, "name": row['Name'], "price": int(curr['Close']), "chg": round(changes, 2),
                "features": {
                    "rs_1d": rs_1d, "rs_20d": rs_20d, "ma_gap": round(ma_gap, 2), "ma20_price": int(ma20),
                    "amount": int(row['Amount']), "amount_strength": amt_s, "conviction": conv, "is_overheated": ma_gap > 35
                },
                "scores": {"score": score, "prime_score": ps, "prime_final": prime_final}
            })
            
        return {"market": {"mode": run_type, "kospi": kp_1d, "kosdaq": kd_1d, "risk_level": risk_level}, "raw_data": raw_results}
    except Exception:
        traceback.print_exc()
        return {"stats": {"data_error": True}, "raw_data": []}
