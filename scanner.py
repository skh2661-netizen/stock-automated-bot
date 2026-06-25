import FinanceDataReader as fdr
import pandas as pd
import asyncio, datetime, pytz, time, math
import requests
import sqlite3
import os
from scoring import calculate_breakout_score, calculate_close_score, calculate_open_score, get_conviction_score, get_prime_score
from risk import get_market_risk
from database import save_candidate, DB_PATH

MIN_PRICE, MIN_AMOUNT, MAX_CANDIDATES = 1000, 15_000_000_000, 10

def safe_json_decode(res, channel_name):
    try:
        text_stripped = res.text.strip()
        if text_stripped.startswith("<") or "text/html" in res.headers.get("Content-Type", "").lower():
            return None
        return res.json()
    except Exception:
        return None

def get_krx_retry():
    for i in range(2):
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
            data = safe_json_decode(res, f"네이버-{market}")
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
        kp_5d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-6]) - 1) * 100
        kd_5d = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-6]) - 1) * 100
        kp_20d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-21]) - 1) * 100 if len(kospi) >= 21 else 0
        kd_20d = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-21]) - 1) * 100 if len(kosdaq) >= 21 else 0
        return round(kp_1d, 2), round(kd_1d, 2), round(kp_5d, 2), round(kd_5d, 2), round(kp_20d, 2), round(kd_20d, 2)
    except: return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

def get_market_regime(kp, kd):
    if kp is None or kd is None: return "NORMAL", "보합"
    if kp <= -2.0 and kd <= -3.0: return "PANIC", "🚨 패닉 셀 (주도주 압축)"
    if kp < 0 and kd < 0: return "WEAK", "⚠️ 약세장 (보수적 접근)"
    if kp > 1.0 and kd < -1.0: return "NORMAL", "⚠️ 양극화 (대형주 수급 집중)"
    if kp > 0.5 and kd > 0.5: return "NORMAL", "🟢 양시장 강세"
    return "NORMAL", "보합 / 혼조세"

async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    try: risk_level = get_market_risk(start_date).get("level", 1)
    except: risk_level = 1
    
    kp_1d, kd_1d, kp_5d, kd_5d, kp_20d, kd_20d = get_market_indices()
    regime, bias_text = get_market_regime(kp_1d, kd_1d)
    
    krx = remove_bad_targets(get_krx_retry())
    
    if krx.empty or "Code" not in krx.columns:
        return {
            "market": {"kospi": kp_1d, "kosdaq": kd_1d, "bias": bias_text, "regime": regime, "mode": run_type, "risk_pct": risk_level},
            "stats": {"total": 0, "pass1": 0, "final": 0, "fail_price": 0, "fail_amount": 0, "fail_change": 0, "fail_ma20": 0, "fail_vol": 0, "fail_score": 0, "fail_heat": 0, "fail_panic": 0, "fail_mode": 0, "fail_position": 0, "data_error": True},
            "candidates": []
        }
        
    krx['Close'] = pd.to_numeric(krx['Close'], errors='coerce')
    krx['Volume'] = pd.to_numeric(krx['Volume'], errors='coerce')
    krx['Amount'] = (krx['Close'] * krx['Volume']).fillna(0)
    krx['ChangesRatio'] = pd.to_numeric(krx['ChangesRatio'], errors='coerce').fillna(0)
    
    total_universe = len(krx)
    fail_price = len(krx[krx['Close'] < MIN_PRICE])
    fail_amount = len(krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] < MIN_AMOUNT)])
    
    if run_type == "TEST":
        fail_change = 0
        candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT)].sort_values("Amount", ascending=False).head(150)
    else:
        fail_change = len(krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & ((krx['ChangesRatio'] < 1) | (krx['ChangesRatio'] > 18))])
        candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & 
                         (krx['ChangesRatio'] >= 1) & (krx['ChangesRatio'] <= 18)].sort_values("Amount", ascending=False).head(100)
    
    results = []
    fail_ma20, fail_vol, fail_score, fail_heat, fail_panic, fail_mode, fail_position = 0, 0, 0, 0, 0, 0, 0
    
    for _, row in candidates.iterrows():
        changes = float(row['ChangesRatio'])
        code = str(row['Code']).zfill(6)
        
        hist = fdr.DataReader(code, start_date)
        if len(hist) < 25: continue
        
        curr = hist.iloc[-1]
        ma20 = hist['Close'].rolling(20).mean().iloc[-1]
        ma60 = hist['Close'].rolling(60).mean().iloc[-1]
        vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
        vr = curr['Volume'] / vol_ma
        ma_gap = (curr['Close'] - ma20) / ma20 * 100
        shadow_ratio = (curr['High'] - curr['Close']) / (curr['High'] - curr['Low'] + 0.0001)
        cp_val = (curr['Close'] - curr['Low']) / (curr['High'] - curr['Low'] + 0.0001) * 100
        
        # [V8.4.27] 모드별 필터 완화 및 윗꼬리(위치) 컷오프 추가
        if run_type != "TEST":
            if run_type == "PRE_OPEN":
                if not (0 <= changes <= 7): fail_mode += 1; continue
            if run_type == "BREAKOUT_1":
                if not (3 <= changes <= 12): fail_mode += 1; continue
                if vr < 2: fail_vol += 1; continue
                if cp_val < 60: fail_position += 1; continue # 윗꼬리 필터
            if run_type == "BREAKOUT_2":
                if not (3 <= changes <= 12): fail_mode += 1; continue
                if ma_gap > 30: fail_heat += 1; continue # 15 -> 30 완화
                if vr < 1.5: fail_vol += 1; continue
            if run_type == "CLOSE_BET":
                if not (1 <= changes <= 8): fail_mode += 1; continue
                if ma_gap > 35: fail_heat += 1; continue # 25 -> 35 완화
                if curr['Close'] < ma20: fail_ma20 += 1; continue
                
        market_penalty = abs(min(kp_1d, 0))
        rs_1d = changes - kp_1d - (market_penalty * 0.5)
        stock_5d = ((curr['Close'] / hist['Close'].iloc[-6]) - 1) * 100
        rs_5d = stock_5d - kp_5d
        stock_20d = ((curr['Close'] / hist['Close'].iloc[-21]) - 1) * 100 if len(hist) >= 21 else 0
        rs_20d = stock_20d - kp_20d
        
        down_days = sum(1 for i in range(-5, 0) if hist['Close'].iloc[i] < hist['Close'].iloc[i-1])
        defense_passed = (down_days <= 2) and (stock_5d > 3)
        
        hist['Amt'] = hist['Close'] * hist['Volume']
        amount_ma5 = hist['Amt'].tail(6).iloc[:-1].mean() if len(hist) >= 6 else 0
        amount_prev20 = hist['Amt'].iloc[-21:-1].mean() if len(hist) >= 21 else hist['Amt'].head(20).mean()
        amount_strength = round(amount_ma5 / amount_prev20, 2) if amount_prev20 > 0 else 0
        amount_strength = min(amount_strength, 5.0)
        
        # [V8.4.27] 엔진별 스코어 호출 및 타임프레임별 가중치 재정의
        norm_conviction = get_conviction_score(rs_1d, row['Amount'], vr, risk_level, ma_gap, cp_val)
        prime_score = get_prime_score(rs_1d, rs_5d, rs_20d, amount_strength, defense_passed, ma_gap)
        
        if run_type == "PRE_OPEN":
            score = calculate_open_score(row['Amount'], vr, changes, shadow_ratio, cp_val, rs_1d, risk_level)
            final_rank = (prime_score * 0.50) + (score * 0.30) + (norm_conviction * 0.20)
        elif "BREAKOUT" in run_type:
            score = calculate_breakout_score(row['Amount'], vr, changes, rs_1d, risk_level)
            vol_sc = min(vr * 10, 100)
            final_rank = (score * 0.40) + (prime_score * 0.40) + (vol_sc * 0.20)
        elif run_type == "CLOSE_BET":
            score = calculate_close_score(row['Amount'], vr, changes, shadow_ratio, 0, cp_val, rs_1d, risk_level, ma_gap)
            final_rank = (score * 0.50) + (prime_score * 0.40) + (norm_conviction * 0.10)
        else: # TEST
            score = calculate_close_score(row['Amount'], vr, changes, shadow_ratio, 0, cp_val, rs_1d, risk_level, ma_gap)
            final_rank = (score * 0.50) + (prime_score * 0.40) + (norm_conviction * 0.10)
            
        prime_blend_rank = (prime_score * 0.7) + (score * 0.3)
        
        # [V8.4.27] TEST 모드 가상 통과 여부 시뮬레이션
        test_pre_open = "PASS" if (0 <= changes <= 7) else "FAIL"
        test_breakout = "PASS" if (3 <= changes <= 12) and vr >= 1.5 and ma_gap <= 30 and cp_val >= 60 else "FAIL"
        test_close = "FAIL (과열)" if ma_gap > 35 else ("PASS" if (1 <= changes <= 8) and curr['Close'] >= ma20 else "FAIL")
        
        cut_score = 30 if run_type == "TEST" else 50
        if score < cut_score:
            fail_score += 1; continue
        
        buy_p = int(curr['Close']*0.985)
        t1, t2, stop = int(curr['Close']*1.023), int(curr['Close']*1.063), int(curr['Close']*0.970)
        
        tr = pd.concat([hist['High'] - hist['Low'], (hist['High'] - hist['Close'].shift(1)).abs(), (hist['Low'] - hist['Close'].shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        if pd.isna(atr) or atr == 0: atr = curr['Close'] * 0.05
        pullback_price = int(curr['Close'] - min(atr, curr['Close'] * 0.08))
        
        save_candidate(run_type, code, row['Name'], score, buy_p, t1, t2, stop, 
                       int(curr['Close']), round(changes, 2), round(ma_gap, 2), 
                       prime_score, final_rank, norm_conviction, amount_strength, 
                       round(rs_1d, 2), round(rs_5d, 2), round(rs_20d, 2), 
                       int(defense_passed), risk_level)
        
        results.append({
            "code": code, "name": row['Name'], "score": score, "price": int(curr['Close']),
            "chg": round(changes, 2), "buy_p": buy_p, "target_1": t1, "target_2": t2, 
            "stop_p": stop, "ma_gap": round(ma_gap, 2), "rs": round(rs_1d, 2),
            "vr": round(vr, 2), "amount": int(row['Amount']),
            "pullback_price": pullback_price,
            "conviction": norm_conviction,
            "amount_strength": amount_strength,
            "prime_score": prime_score,
            "final_rank": final_rank,
            "prime_blend_rank": prime_blend_rank,
            "test_pre_open": test_pre_open,
            "test_breakout": test_breakout,
            "test_close": test_close
        })
            
    results = sorted(results, key=lambda x: (x['final_rank'], x['amount'], x['chg']), reverse=True)[:MAX_CANDIDATES]
    
    if results:
        p_scores = [c['prime_score'] for c in results]
        p_scores.sort(reverse=True)
        dynamic_cutoff = max(p_scores[min(2, len(p_scores)-1)], 60)
        prime_candidates = [c for c in results if c['prime_score'] >= dynamic_cutoff]
        prime = max(prime_candidates, key=lambda x: x['prime_blend_rank']) if prime_candidates else None
    else:
        prime = None
    
    if prime:
        for c in results: c['is_prime_leader'] = (c['code'] == prime['code'])
    else:
        for c in results: c['is_prime_leader'] = False
            
    return {
        "market": {"kospi": kp_1d, "kosdaq": kd_1d, "bias": bias_text, "regime": regime, "mode": run_type, "risk_pct": risk_level},
        "stats": {
            "total": total_universe, "pass1": len(candidates), "final": len(results),
            "fail_price": fail_price, "fail_amount": fail_amount, "fail_change": fail_change,
            "fail_ma20": fail_ma20, "fail_vol": fail_vol, "fail_score": fail_score, "fail_heat": fail_heat, "fail_panic": fail_panic, "fail_mode": fail_mode, "fail_position": fail_position, "data_error": False
        },
        "candidates": results
    }
