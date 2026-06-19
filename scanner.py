import FinanceDataReader as fdr
import pandas as pd
import asyncio, datetime, pytz, time
from scoring import calculate_score
from risk import get_market_risk
from database import save_candidate

# [수정 1] 거래대금 컷오프 150억으로 하향 (중소형 돌파주 확보)
MIN_PRICE, MIN_AMOUNT, MAX_CANDIDATES = 2000, 15_000_000_000, 10

def get_krx_retry():
    for i in range(3):
        try:
            krx = fdr.StockListing("KRX")
            rename_map = {"ChagesRatio": "ChangesRatio", "ChgRate": "ChangesRatio"}
            for old, new in rename_map.items():
                if old in krx.columns: krx.rename(columns={old: new}, inplace=True)
            krx = krx.loc[:, ~krx.columns.duplicated()].reset_index(drop=True)
            krx["ChangesRatio"] = pd.to_numeric(krx["ChangesRatio"], errors="coerce").fillna(0)
            return krx
        except: time.sleep(5)
    raise Exception("KRX 연결 실패")

def remove_bad_targets(df):
    if "Name" not in df.columns: return df
    pattern = r'스팩|ETF|ETN|우$|우[A-Z]$|[0-9]+우[A-Z]?$|제[0-9]+호'
    return df[~df['Name'].str.contains(pattern, regex=True, na=False)]

def get_market_indices():
    try:
        kst = pytz.timezone("Asia/Seoul")
        start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=5)).strftime("%Y-%m-%d")
        kospi = fdr.DataReader("KS11", start_date)
        kosdaq = fdr.DataReader("KQ11", start_date)
        kp = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-2]) - 1) * 100
        kd = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-2]) - 1) * 100
        return round(kp, 2), round(kd, 2)
    except: return None, None

def get_market_bias(kp, kd):
    if kp is None or kd is None: return "판독 불가"
    if kp > 1.0 and kd < -1.0: return "⚠️ 양극화 (대형주 수급 집중)"
    if kp < -1.0 and kd > 1.0: return "⚠️ 양극화 (중소형 테마주 쏠림)"
    if kp > 0.5 and kd > 0.5: return "🟢 양시장 동반 강세"
    if kp < -0.5 and kd < -0.5: return "🚨 투심 악화 (현금 비중 확대)"
    return "보합 / 혼조세"

async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    try: risk_level = get_market_risk(start_date).get("level", 1)
    except: risk_level = 1
    
    kospi_pct, kosdaq_pct = get_market_indices()
    if kospi_pct is None: kospi_pct, kosdaq_pct = 0.0, 0.0
    market_bias = get_market_bias(kospi_pct, kosdaq_pct)
    
    krx = remove_bad_targets(get_krx_retry())
    krx['Close'] = pd.to_numeric(krx['Close'], errors='coerce')
    krx['Amount'] = (krx['Close'] * pd.to_numeric(krx['Volume'], errors='coerce')).fillna(0)
    
    candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & 
                     (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18)].sort_values("Amount", ascending=False).head(100)
    
    results = []
    fail_ma20, fail_vol, fail_score, fail_heat = 0, 0, 0, 0
    
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
        vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
        vr = curr['Volume'] / vol_ma
        ma_gap = (curr['Close'] - ma20) / ma20 * 100
        
        fail_ma20 += 1 if curr['Close'] < ma20 else 0
        
        rs_val = changes - kospi_pct
        
        if run_type == "BREAKOUT_1" and vr < 2:
            fail_vol += 1; continue
            
        if run_type == "BREAKOUT_2":
            if ma_gap > 15:
                fail_heat += 1; continue
            if rs_val < 5:  
                continue

        shadow_ratio = (curr['High'] - curr['Close']) / (curr['High'] - curr['Low'] + 0.0001)
        cp_val = (curr['Close'] - curr['Low']) / (curr['High'] - curr['Low'] + 0.0001) * 100
        
        score = calculate_score(row['Amount'], vr, changes, shadow_ratio, ma_gap, cp_val, rs_val, 0, risk_level)
        
        if run_type == "PRE_OPEN": score += 5 if ma_gap < 5 else 0
        if run_type == "BREAKOUT_1" and vr >= 2: score += 5
        if run_type == "CLOSE_BET" and cp_val >= 80: score += 5
        
        c_vol = 1 if vr >= 1.5 else 0
        c_amt = 1 if row['Amount'] >= 30_000_000_000 else 0
        c_heat = 1 if ma_gap <= 15 else 0
        c_shadow = 1 if shadow_ratio < 0.6 else 0
        c_rs = 1 if changes > kospi_pct else 0
        cond_count = c_vol + c_amt + c_heat + c_shadow + c_rs
        
        # [수정 2] cond_count 곱연산 페널티 삭제, 2개 이하일 때만 -5점
        if cond_count <= 2:
            score -= 5
            
        score = min(max(int(score), 0), 100)
        
        # [수정 3] TEST 모드일 경우 후보군 확보를 위해 컷오프 50으로 하향
        cut_score = 50 if run_type == "TEST" else 55
        if score < cut_score:
            fail_score += 1; continue
        
        buy_p, t1, t2, stop = int(curr['Close']*0.985), int(curr['Close']*1.023), int(curr['Close']*1.063), int(curr['Close']*0.970)
        
        save_candidate(run_type, code, row['Name'], score, buy_p, t1, t2, stop, 
                       int(curr['Close']), round(changes, 2), round(ma_gap, 2), 0,0,0,0,0,0,0,0,0)
        
        results.append({
            "code": code, "name": row['Name'], "score": score, "price": int(curr['Close']),
            "chg": round(changes, 2), "buy_p": buy_p, "target_1": t1, "target_2": t2, 
            "stop_p": stop, "ma_gap": round(ma_gap, 2), "rs": round(rs_val, 2),
            "cond_count": cond_count, "c_vol": c_vol, "c_amt": c_amt, "c_heat": c_heat, "c_shadow": c_shadow, "c_rs": c_rs,
            "vr": round(vr, 2), "amount": int(row['Amount'])
        })
            
    results = sorted(results, key=lambda x: (x['score'], x['cond_count'], x['chg']), reverse=True)[:MAX_CANDIDATES]
    
    return {
        "market": {"kospi": kospi_pct, "kosdaq": kosdaq_pct, "bias": market_bias, "mode": run_type, "risk_pct": risk_level},
        "stats": {"total": len(krx), "pass1": len(candidates), "final": len(results),
                  "fail_ma20": fail_ma20, "fail_vol": fail_vol, "fail_score": fail_score, "fail_heat": fail_heat},
        "candidates": results
    }
