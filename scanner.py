import FinanceDataReader as fdr
import pandas as pd
import asyncio, datetime, pytz, time
from risk import get_market_risk
from scoring import calculate_score
from database import save_candidate

MIN_PRICE, MIN_AMOUNT, MAX_CANDIDATES = 2000, 10_000_000_000, 10

def get_krx_retry():
    for i in range(3):
        try:
            krx = fdr.StockListing("KRX")
            rename_map = {"ChagesRatio": "ChangesRatio", "ChgRate": "ChangesRatio", "ChangeRate": "ChangesRatio", "Changes": "ChangesRatio"}
            for old, new in rename_map.items():
                if old in krx.columns:
                    krx.rename(columns={old: new}, inplace=True)
            if "ChangesRatio" not in krx.columns: raise Exception("등락률 컬럼 없음")
            
            krx = krx.loc[:, ~krx.columns.duplicated()]
            if "Code" in krx.columns:
                krx = krx.drop_duplicates(subset=["Code"], keep="first")
            krx = krx.reset_index(drop=True)
            
            krx["ChangesRatio"] = pd.to_numeric(krx["ChangesRatio"], errors="coerce").fillna(0)
            krx["ChangesRatio"] = krx["ChangesRatio"] / 1000
            
            krx.loc[(krx["ChangesRatio"] > 30) | (krx["ChangesRatio"] < -30), "ChangesRatio"] = 0
            krx["ChangesRatio"] = krx["ChangesRatio"].fillna(0)
                
            return krx
        except Exception as e:
            print("KRX 재시도:", e)
            time.sleep(5)
    raise Exception("KRX 데이터 연결 실패")

def remove_bad_targets(df):
    if "Name" not in df.columns: return df
    pattern = '스팩|ETF|ETN|우$|우[A-Z]$|제[0-9]+호'
    return df[~df['Name'].str.contains(pattern, regex=True, na=False)]

async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.datetime.now(kst)
    start_date = (now - datetime.timedelta(days=60)).strftime("%Y-%m-%d")

    try:
        risk_data = get_market_risk(start_date)
        risk_level = risk_data.get("level", 1)
        risk_pct = risk_data.get("change", 0)
    except:
        risk_level = 1
        risk_pct = 0
        
    if risk_level >= 2 and run_type == "CLOSE_SCAN":
        return {"market": {"kospi": 0, "kosdaq": 0, "mode": "🚨 위험", "risk_pct": risk_pct}, "stats": {"total":0, "pass1":0, "final":0}, "fail_stats": {"ma20": 0, "vol": 0, "score": 0, "etc": 0}, "candidates": []}
    
    min_score = 75 if risk_level == 0 else (80 if risk_level == 1 else 85)

    try:
        kospi_hist = fdr.DataReader("KS11", start_date)
        kosdaq_hist = fdr.DataReader("KQ11", start_date)
        
        market_5d_change = (kospi_hist['Close'].iloc[-1] / kospi_hist['Close'].iloc[-6] - 1) * 100 if len(kospi_hist) >= 6 else 0
        kospi_daily = (kospi_hist['Close'].iloc[-1] / kospi_hist['Close'].iloc[-2] - 1) * 100 if len(kospi_hist) >= 2 else 0
        kosdaq_daily = (kosdaq_hist['Close'].iloc[-1] / kosdaq_hist['Close'].iloc[-2] - 1) * 100 if len(kosdaq_hist) >= 2 else 0
    except: 
        market_5d_change, kospi_daily, kosdaq_daily = 0, 0, 0

    krx = remove_bad_targets(get_krx_retry())
    krx = krx.loc[:, ~krx.columns.duplicated()]
    krx = krx.reset_index(drop=True)
    
    krx['Close'] = pd.to_numeric(krx['Close'], errors='coerce')
    krx['Volume'] = pd.to_numeric(krx['Volume'], errors='coerce')
    krx['Amount'] = (krx['Close'] * krx['Volume']).fillna(0)

    candidates = krx[
        (krx['Close'] >= MIN_PRICE) & 
        (krx['Amount'] >= MIN_AMOUNT) & 
        (krx['ChangesRatio'] >= 3) & 
        (krx['ChangesRatio'] <= 18)
    ].sort_values("Amount", ascending=False).head(100)
    
    results = []
    fail_stats = {"ma20": 0, "vol": 0, "score": 0, "etc": 0}
    
    for _, row in candidates.iterrows():
        code = str(row['Code']).zfill(6)
        await asyncio.sleep(0.15)
        try:
            hist = fdr.DataReader(code, start_date)
            if len(hist) < 25: 
                fail_stats["etc"] += 1
                continue
            
            curr = hist.iloc[-1]
            vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
            if pd.isna(vol_ma) or vol_ma <= 0 or curr['High'] <= 0: 
                fail_stats["etc"] += 1
                continue
            
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            if pd.isna(ma20) or ma20 <= 0: 
                fail_stats["etc"] += 1
                continue
            
            ma_gap = (curr['Close'] - ma20) / ma20 * 100
            if ma_gap < 0:
                fail_stats["ma20"] += 1
                continue
                
            vol_ratio = curr['Volume'] / vol_ma  
            if vol_ratio < 1.3:
                fail_stats["vol"] += 1
                continue
            
            upper_shadow = ((curr['High'] - max(curr['Open'], curr['Close'])) / curr['High'] * 100)
            candle_pos = ((curr['Close'] - curr['Low']) / (curr['High'] - curr['Low']) * 100) if (curr['High'] > curr['Low']) else 0
            
            if upper_shadow > 5: 
                fail_stats["etc"] += 1
                continue
            
            five_change = (curr['Close'] / hist['Close'].iloc[-6] - 1) * 100
            rs = five_change - market_5d_change
            
            score = int(calculate_score(row['Amount'], vol_ratio, row['ChangesRatio'], upper_shadow, ma_gap, candle_pos, rs, five_change, risk_level))
            
            if score < min_score: 
                fail_stats["score"] += 1
                continue
            
            buy_p = int(curr['Close'] * 0.985)
            t1 = int(curr['Close'] * 1.023)
            t2 = int(curr['Close'] * 1.063)
            stop = int(curr['Close'] * 0.970)
            
            # [수정] 종가 베팅 최적화를 위해 표시 및 검증 임계값을 1.5배로 상향 커스터마이징
            c_vol = bool(vol_ratio >= 1.5)
            c_rs = bool(rs >= 5)
            c_heat = bool(ma_gap < 15)
            c_amt = bool(row['Amount'] >= 50_000_000_000)
            c_shadow = bool(upper_shadow <= 5)
            
            cond_count = int(sum([c_vol, c_rs, c_heat, c_amt, c_shadow]))

            save_candidate(
                run_type, code, row['Name'], score, buy_p, t1, t2, stop,
                int(curr['Close']), round(float(row['ChangesRatio']), 2), round(float(ma_gap), 2), round(float(rs), 2), 
                round(float(five_change), 2), round(float(market_5d_change), 2), int(c_vol), int(c_rs), int(c_heat), int(c_amt), int(c_shadow), cond_count
            )
            
            results.append({
                "code": code, "name": row['Name'], "score": score, "price": int(curr['Close']),
                "chg": round(float(row['ChangesRatio']), 2), "buy_p": buy_p, "target_1": t1, "target_2": t2, "stop_p": stop,
                "ma_gap": round(float(ma_gap), 2), "rs": round(float(rs), 2), "five_chg": round(float(five_change), 2), "kospi_chg": round(float(market_5d_change), 2),
                "c_vol": c_vol, "c_rs": c_rs, "c_heat": c_heat, "c_amt": c_amt, "c_shadow": c_shadow, "cond_count": cond_count
            })
            
            if len(results) >= MAX_CANDIDATES: break
        except Exception:
            fail_stats["etc"] += 1
            
    return {
        "market": {"kospi": round(float(kospi_daily), 2), "kosdaq": round(float(kosdaq_daily), 2), "mode": "🟢 정상", "risk_pct": risk_pct},
        "stats": {"total": len(krx), "pass1": len(candidates), "final": len(results)},
        "fail_stats": fail_stats,
        "candidates": results
    }
