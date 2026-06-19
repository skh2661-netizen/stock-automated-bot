import FinanceDataReader as fdr
import pandas as pd
import asyncio, datetime, pytz, time
import requests
from scoring import calculate_score, get_conviction_score
from risk import get_market_risk
from database import save_candidate

MIN_PRICE, MIN_AMOUNT, MAX_CANDIDATES = 2000, 15_000_000_000, 10

def get_krx_retry():
    for i in range(2):
        try:
            krx = fdr.StockListing("KRX")
            krx.rename(columns={"ChagesRatio": "ChangesRatio", "ChgRate": "ChangesRatio"}, inplace=True)
            krx = krx.loc[:, ~krx.columns.duplicated()].reset_index(drop=True)
            krx["ChangesRatio"] = pd.to_numeric(krx["ChangesRatio"], errors="coerce").fillna(0)
            return krx
        except: time.sleep(2)
        
    print("🚨 KRX 차단 감지. 네이버 금융 우회.")
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        df_list = []
        for market in ["KOSPI", "KOSDAQ"]:
            res = requests.get(f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page=1&pageSize=2500", headers=headers)
            stocks = res.json().get('stocks', [])
            if not stocks: continue
            df = pd.DataFrame(stocks)
            df.rename(columns={'itemCode': 'Code', 'stockName': 'Name', 'closePrice': 'Close', 'fluctuationsRatio': 'ChangesRatio', 'accumulatedTradingVolume': 'Volume'}, inplace=True)
            for col in ['Close', 'Volume']:
                df[col] = df[col].astype(str).str.replace(',', '')
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            df['ChangesRatio'] = pd.to_numeric(df['ChangesRatio'], errors='coerce').fillna(0)
            df_list.append(df)
        return pd.concat(df_list, ignore_index=True)
    except Exception as e: raise Exception(f"연결 실패: {e}")

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
        
        # [수정 1] 20일(약 1개월) 누적 등락률 산출
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

# [수정 4] Prime Leader 판별 로직 (3중 RS, 대금 지속성 추가)
def is_prime_leader(score, rs_1d, rs_5d, rs_20d, amount, amount_strength, ma_gap, cp, vr, defense_passed):
    if score < 65: return False
    if rs_1d < 10: return False
    if rs_5d < 5: return False
    if rs_20d < 0: return False # 한 달 추세 생존 여부
    if amount < 50_000_000_000: return False
    if amount_strength < 1.5: return False # 단발성 수급 차단
    if ma_gap > 12: return False
    if cp < 70: return False
    if vr < 2: return False
    if not defense_passed: return False
    return True

async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    try: risk_level = get_market_risk(start_date).get("level", 1)
    except: risk_level = 1
    
    kp_1d, kd_1d, kp_5d, kd_5d, kp_20d, kd_20d = get_market_indices()
    regime, bias_text = get_market_regime(kp_1d, kd_1d)
    
    krx = remove_bad_targets(get_krx_retry())
    krx['Close'] = pd.to_numeric(krx['Close'], errors='coerce')
    krx['Amount'] = (krx['Close'] * pd.to_numeric(krx['Volume'], errors='coerce')).fillna(0)
    
    candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & 
                     (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18)].sort_values("Amount", ascending=False).head(100)
    
    results = []
    fail_ma20, fail_vol, fail_score, fail_heat, fail_panic = 0, 0, 0, 0, 0
    
    for _, row in candidates.iterrows():
        changes = float(row['ChangesRatio'])
        if run_type != "TEST":
            if run_type == "PRE_OPEN" and not (0 <= changes <= 7): continue
            if run_type == "BREAKOUT_1" and not (3 <= changes <= 12): continue
            if run_type == "CLOSE_BET" and not (1 <= changes <= 5): continue

        code = str(row['Code']).zfill(6)
        hist = fdr.DataReader(code, start_date)
        if len(hist) < 25: continue
        
        curr = hist.iloc[-1]
        ma20 = hist['Close'].rolling(20).mean().iloc[-1]
        ma60 = hist['Close'].rolling(60).mean().iloc[-1]
        vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
        vr = curr['Volume'] / vol_ma
        ma_gap = (curr['Close'] - ma20) / ma20 * 100
        
        fail_ma20 += 1 if curr['Close'] < ma20 else 0
        
        # 1일, 5일, 20일 RS 계산
        market_penalty = abs(min(kp_1d, 0))
        rs_1d = changes - kp_1d - (market_penalty * 0.5)
        
        stock_5d = ((curr['Close'] / hist['Close'].iloc[-6]) - 1) * 100
        rs_5d = stock_5d - kp_5d
        
        stock_20d = ((curr['Close'] / hist['Close'].iloc[-21]) - 1) * 100 if len(hist) >= 21 else 0
        rs_20d = stock_20d - kp_20d
        
        # [수정 2] 보유자 방어력 (하락일수 + 5일 수익률 동시 검증)
        down_days = sum(1 for i in range(-5, 0) if hist['Close'].iloc[i] < hist['Close'].iloc[i-1])
        defense_passed = (down_days <= 2) and (stock_5d > 3)
        
        # [수정 4] 거래대금 지속성 산출
        hist['Amount'] = hist['Close'] * hist['Volume']
        amount_ma5 = hist['Amount'].rolling(5).mean().iloc[-1]
        amount_strength = row['Amount'] / amount_ma5 if amount_ma5 > 0 else 0
        
        # [수정 3] 패닉장 MA60 이격 허용폭 완화 (-3%)
        if regime == "PANIC":
            survival_score = 0
            if rs_1d >= 10: survival_score += 1
            if row['Amount'] >= 50_000_000_000: survival_score += 1
            if curr['Close'] >= (ma60 * 0.97): survival_score += 1
            
            if survival_score < 2:
                fail_panic += 1; continue

        if run_type == "BREAKOUT_1" and vr < 2: fail_vol += 1; continue
        if run_type == "BREAKOUT_2":
            if ma_gap > 15: fail_heat += 1; continue
            if rs_1d < 5: continue

        shadow_ratio = (curr['High'] - curr['Close']) / (curr['High'] - curr['Low'] + 0.0001)
        cp_val = (curr['Close'] - curr['Low']) / (curr['High'] - curr['Low'] + 0.0001) * 100
        
        score = calculate_score(row['Amount'], vr, changes, shadow_ratio, ma_gap, cp_val, rs_1d, 0, risk_level)
        
        if run_type == "PRE_OPEN": score += 5 if ma_gap < 5 else 0
        if run_type == "BREAKOUT_1" and vr >= 2: score += 5
        if run_type == "CLOSE_BET" and cp_val >= 80: score += 5
        
        c_vol = 1 if vr >= 1.5 else 0
        c_amt = 1 if row['Amount'] >= 30_000_000_000 else 0
        c_heat = 1 if ma_gap <= 15 else 0
        c_shadow = 1 if shadow_ratio < 0.6 else 0
        c_rs = 1 if changes > kp_1d else 0
        cond_count = c_vol + c_amt + c_heat + c_shadow + c_rs
        
        if cond_count <= 2: score -= 5
        score = min(max(int(score), 0), 100)
        
        conviction = get_conviction_score(rs_1d, row['Amount'], vr, risk_level, ma_gap, cp_val)
        is_prime = is_prime_leader(score, rs_1d, rs_5d, rs_20d, row['Amount'], amount_strength, ma_gap, cp_val, vr, defense_passed)
        
        cut_score = 45 if run_type == "TEST" else 55
        if score < cut_score and not is_prime:
            fail_score += 1; continue
        
        buy_p = int(curr['Close']*0.985)
        t1, t2, stop = int(curr['Close']*1.023), int(curr['Close']*1.063), int(curr['Close']*0.970)
        
        high_low = hist['High'] - hist['Low']
        high_close = (hist['High'] - hist['Close'].shift(1)).abs()
        low_close = (hist['Low'] - hist['Close'].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        if pd.isna(atr) or atr == 0: atr = curr['Close'] * 0.05
        pullback_price = int(curr['Close'] - min(atr, curr['Close'] * 0.08))
        
        save_candidate(run_type, code, row['Name'], score, buy_p, t1, t2, stop, 
                       int(curr['Close']), round(changes, 2), round(ma_gap, 2), 0,0,0,0,0,0,0,0,0)
        
        results.append({
            "code": code, "name": row['Name'], "score": score, "price": int(curr['Close']),
            "chg": round(changes, 2), "buy_p": buy_p, "target_1": t1, "target_2": t2, 
            "stop_p": stop, "ma_gap": round(ma_gap, 2), "rs": round(rs_1d, 2),
            "cond_count": cond_count, "c_vol": c_vol, "c_amt": c_amt, "c_heat": c_heat, "c_shadow": c_shadow, "c_rs": c_rs,
            "vr": round(vr, 2), "amount": int(row['Amount']),
            "pullback_price": pullback_price,
            "conviction": conviction,
            "is_prime": is_prime
        })
            
    # [수정 5] Prime Leader(원픽) 무조건 1순위 정렬 보장
    results = sorted(results, key=lambda x: (x['is_prime'], x['score'], x['conviction'], x['cond_count'], x['amount'], x['chg']), reverse=True)[:MAX_CANDIDATES]
    
    return {
        "market": {"kospi": kp_1d, "kosdaq": kd_1d, "bias": bias_text, "regime": regime, "mode": run_type, "risk_pct": risk_level},
        "stats": {"total": len(krx), "pass1": len(candidates), "final": len(results),
                  "fail_ma20": fail_ma20, "fail_vol": fail_vol, "fail_score": fail_score, "fail_heat": fail_heat, "fail_panic": fail_panic},
        "candidates": results
    }
