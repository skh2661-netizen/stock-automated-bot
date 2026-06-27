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
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        df_list = []
        for market in ["KOSPI", "KOSDAQ"]:
            res = requests.get(f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page=1&pageSize=2500", headers=headers, timeout=5)
            data = safe_json_decode(res)
            if not data or not data.get('stocks'): continue
            df = pd.DataFrame(data['stocks'])
            df.rename(columns={'itemCode': 'Code', 'stockName': 'Name', 'closePrice': 'Close', 'fluctuationsRatio': 'ChangesRatio', 'accumulatedTradingVolume': 'Volume'}, inplace=True)
            for col in ['Close', 'Volume']: df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            df['ChangesRatio'] = pd.to_numeric(df['ChangesRatio'], errors='coerce').fillna(0)
            df_list.append(df)
        if df_list: return pd.concat(df_list, ignore_index=True)
    except Exception: pass
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            cache_df = pd.read_sql_query("SELECT code AS Code, name AS Name, price AS Close, chg AS ChangesRatio FROM candidate_history WHERE scan_datetime = (SELECT max(scan_datetime) FROM candidate_history)", conn)
            conn.close()
            if not cache_df.empty: 
                cache_df["Volume"], cache_df["Amount"] = 1_000_000, pd.to_numeric(cache_df["Close"] * 1_000_000, errors='coerce').fillna(0)
                return cache_df
        except Exception: pass
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
        return round(kp_1d, 2), round(kd_1d, 2)
    except: return 0.0, 0.0

def fetch_history(code, start_date):
    for _ in range(3):
        try:
            df = fdr.DataReader(code, start_date)
            if not df.empty: return code, df
        except: time.sleep(1)
    return code, None

async def generate_raw_candidates(run_type="OPEN_SCAN"):
    """
    [역할 축소] 오직 지표 계산 및 Raw Data 생성만 수행
    판단 로직, 랭킹, 타점 계산은 모두 Decision Engine으로 이관됨.
    """
    try:
        kst = pytz.timezone("Asia/Seoul")
        scan_datetime = datetime.datetime.now(kst).strftime("%Y-%m-%d %H:%M")
        start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
        kp_1d, kd_1d = get_market_indices()
        
        if kp_1d <= -3.0 or kd_1d <= -4.0: risk_level = 3
        elif kp_1d <= -1.0 or kd_1d <= -1.5: risk_level = 2
        else: risk_level = 1

        krx = remove_bad_targets(get_krx_retry())
        
        market_score = 100
        if kp_1d < -2.0: market_score -= 30
        if kd_1d < -3.0: market_score -= 30

        if krx.empty or "Code" not in krx.columns:
            return {"market": {"mode": run_type, "kospi": kp_1d, "kosdaq": kd_1d, "market_score": market_score, "risk_level": risk_level}, "stats": {"data_error": True}, "raw_data": []}
        
        krx['Close'], krx['Volume'] = pd.to_numeric(krx['Close'], errors='coerce'), pd.to_numeric(krx['Volume'], errors='coerce')
        krx['Amount'], krx['ChangesRatio'] = (krx['Close'] * krx['Volume']).fillna(0), pd.to_numeric(krx['ChangesRatio'], errors='coerce').fillna(0)
        
        stats = {"total": len(krx), "pass1": 0, "fail_heat": 0, "fail_score": 0, "fail_reader": 0, "data_error": False}
        if run_type == "TEST": candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT)].sort_values("Amount", ascending=False).head(200)
        else: candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & (krx['ChangesRatio'] >= 1) & (krx['ChangesRatio'] <= 18)].sort_values("Amount", ascending=False).head(100)
        
        raw_results = []
        codes = candidates['Code'].apply(lambda x: str(x).zfill(6)).tolist()
        with ThreadPoolExecutor(max_workers=5) as ex: histories = dict(ex.map(lambda c: fetch_history(c, start_date), codes))
        
        for _, row in candidates.iterrows():
            stats["pass1"] += 1
            code, changes = str(row['Code']).zfill(6), float(row['ChangesRatio'])
            hist = histories.get(code)
            if hist is None or len(hist) < 30: stats["fail_reader"] += 1; continue
            
            hist = hist.copy()
            hist['Amt'] = hist['Close'] * hist['Volume']
            curr, ma20 = hist.iloc[-1], hist['Close'].rolling(20).mean().iloc[-1]
            ma_gap = ((curr['Close'] - ma20) / ma20 * 100) if ma20 > 0 else 0
            shadow_ratio, cp_val = (curr['High'] - curr['Close']) / (curr['High'] - curr['Low'] + 0.0001), (curr['Close'] - curr['Low']) / (curr['High'] - curr['Low'] + 0.0001) * 100
            
            heat_limit = 35 if (run_type == "CLOSE_BET" and row['Amount'] >= 100_000_000_000 and cp_val >= 70) else (35 if row['Amount'] >= 100_000_000_000 else 25)
            is_overheated = ma_gap > heat_limit
            rs_1d = changes - kp_1d
            rs_5d, rs_20d = ((hist['Close'].iloc[-1]/hist['Close'].iloc[-6]-1)*100 - kp_1d*5), ((hist['Close'].iloc[-1]/hist['Close'].iloc[-21]-1)*100 - kp_1d*20)
            amt_s = min(round(((hist['Amt'].tail(6).iloc[:-1].mean() if not pd.isna(hist['Amt'].tail(6).iloc[:-1].mean()) else 0) / (hist['Amt'].iloc[-21:-1].mean() + 1)), 2), 5.0) if (not pd.isna(hist['Amt'].iloc[-21:-1].mean()) and hist['Amt'].iloc[-21:-1].mean() > 0) else 0
            
            ps = get_prime_score(rs_1d, rs_5d, rs_20d, amt_s, True)
            if is_overheated and ps < 70: stats["fail_heat"] += 1; continue
            
            score = calculate_preopen_score(row['Amount'], curr['Volume']/(hist['Volume'].rolling(20).mean().iloc[-1]+1), changes, shadow_ratio, cp_val, rs_1d, risk_level) if run_type == "PRE_OPEN" else (calculate_breakout_score(row['Amount'], curr['Volume']/(hist['Volume'].rolling(20).mean().iloc[-1]+1), changes, rs_1d, risk_level) if "BREAKOUT" in run_type else calculate_close_score(row['Amount'], curr['Volume']/(hist['Volume'].rolling(20).mean().iloc[-1]+1), changes, shadow_ratio, 0, cp_val, rs_1d, risk_level, ma_gap))
            if score < 55: stats["fail_score"] += 1; continue
            
            conv = get_conviction_score(rs_1d, row['Amount'], curr['Volume']/(hist['Volume'].rolling(20).mean().iloc[-1]+1), risk_level, ma_gap, cp_val)
            
            ma_factor = max(0, 100 - (ma_gap * 2))
            prime_final = round((ps * 0.35 + score * 0.30 + conv * 0.15 + ma_factor * 0.20), 1)
            
            raw_results.append({
                "code": code,
                "name": row['Name'],
                "price": int(curr['Close']),
                "chg": round(changes, 2),
                "features": {
                    "rs_1d": round(rs_1d, 2),
                    "rs_5d": round(rs_5d, 2),
                    "rs_20d": round(rs_20d, 2),
                    "ma_gap": round(ma_gap, 2),
                    "ma20_price": int(ma20),
                    "amount": int(row['Amount']),
                    "amount_strength": amt_s,
                    "conviction": conv,
                    "is_overheated": is_overheated
                },
                "scores": {
                    "score": score,
                    "prime_score": ps,
                    "prime_final": prime_final
                }
            })
            
        raw_results = list({x["code"]: x for x in raw_results}.values())
        
        # 순위 부여를 위한 임시 1차 정렬 (DB 저장용)
        raw_results.sort(key=lambda x: x['scores']['prime_final'], reverse=True)
        raw_results = raw_results[:MAX_CANDIDATES]

        # Memory Layer 스냅샷 저장
        for rank_idx, i in enumerate(raw_results, 1):
            try:
                save_candidate_history(
                    scan_datetime=scan_datetime,
                    run_type=run_type,
                    code=i['code'],
                    name=i['name'],
                    rank_position=rank_idx,
                    price=i['price'],
                    chg=i['chg'],
                    prime_final=i['scores']['prime_final'],
                    prime_score=i['scores']['prime_score'],
                    conviction=i['features']['conviction'],
                    rs_1d=i['features']['rs_1d'],
                    rs_5d=i['features']['rs_5d'],
                    rs_20d=i['features']['rs_20d'],
                    ma_gap=i['features']['ma_gap'],
                    amount=i['features']['amount'],
                    amount_strength=i['features']['amount_strength'],
                    risk_level=risk_level
                )
            except Exception:
                traceback.print_exc()

        stats["final"] = len(raw_results)
        return {"market": {"mode": run_type, "kospi": kp_1d, "kosdaq": kd_1d, "market_score": market_score, "risk_level": risk_level}, "stats": stats, "raw_data": raw_results}
    except Exception:
        traceback.print_exc()
        return {"market": {"mode": run_type, "kospi": 0, "kosdaq": 0, "market_score": 100, "risk_level": 1}, "stats": {"total": 0, "final": 0, "data_error": True}, "raw_data": []}
