import FinanceDataReader as fdr
import pandas as pd
import asyncio, datetime, pytz, time
from scoring import calculate_score
from risk import get_market_risk
from database import save_candidate

MIN_PRICE, MIN_AMOUNT, MAX_CANDIDATES = 2000, 10_000_000_000, 10

def get_krx_retry():
    for i in range(3):
        try:
            krx = fdr.StockListing("KRX")
            if "ChagesRatio" in krx.columns: krx.rename(columns={"ChagesRatio": "ChangesRatio"}, inplace=True)
            elif "ChgRate" in krx.columns: krx.rename(columns={"ChgRate": "ChangesRatio"}, inplace=True)
            if "ChangesRatio" not in krx.columns: raise Exception("등락률 컬럼 없음")
            return krx
        except Exception as e:
            print(f"KRX 연결 오류 {i+1}/3 : {e}")
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
        risk = get_market_risk(start_date)
        risk_level = risk["level"]
    except:
        risk_level = 1
        
    if risk_level >= 2 and run_type == "CLOSE_SCAN":
        return {
            "market": {"kospi": 0}, 
            "stats": {"final": 0}, 
            "candidates": []
        }
    
    min_score = 75 if risk_level == 0 else (80 if risk_level == 1 else 85)

    try:
        market_hist = fdr.DataReader("KS11", start_date)
        market_change = (market_hist['Close'].iloc[-1] / market_hist['Close'].iloc[-6] - 1) * 100 if len(market_hist) >= 6 else 0
    except: 
        market_change = 0

    krx = remove_bad_targets(get_krx_retry())
    krx['Amount'] = krx['Close'] * krx['Volume']
    candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & 
                     (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18)].sort_values("Amount", ascending=False).head(100)
    
    results = []
    for _, row in candidates.iterrows():
        code = str(row['Code']).zfill(6)
        await asyncio.sleep(0.15)
        try:
            hist = fdr.DataReader(code, start_date)
            if len(hist) < 25: continue
            
            curr = hist.iloc[-1]
            vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
            if pd.isna(vol_ma) or vol_ma <= 0 or curr['High'] <= 0: continue
            
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            if pd.isna(ma20) or ma20 <= 0: continue
            
            ma_gap = (curr['Close'] - ma20) / ma20 * 100
            vol_ratio = row['Volume'] / vol_ma
            upper_shadow = ((curr['High'] - max(curr['Open'], curr['Close'])) / curr['High'] * 100)
            candle_pos = ((curr['Close'] - curr['Low']) / (curr['High'] - curr['Low']) * 100) if (curr['High'] > curr['Low']) else 0
            
            if ma_gap < 0 or vol_ratio < 1.3 or upper_shadow > 5: continue
            
            p6 = hist['Close'].iloc[-6]
            if p6 <= 0: continue
            five_change = (curr['Close'] / p6 - 1) * 100
            
            score = calculate_score(row['Amount'], vol_ratio, row['ChangesRatio'], upper_shadow, 
                                   ma_gap, candle_pos, (five_change - market_change), five_change, risk_level)
            
            if score < min_score: continue
            
            buy_p = int(curr['Close'] * 0.985)
            t1 = int(curr['Close'] * 1.023)
            t2 = int(curr['Close'] * 1.063)
            stop = int(curr['Close'] * 0.970)
            
            if save_candidate(run_type, code, row['Name'], score, buy_p, t1, t2, stop):
                results.append({
                    "code": code, 
                    "name": row['Name'], 
                    "score": score, 
                    "price": int(curr['Close'])
                })
            
            if len(results) >= MAX_CANDIDATES: break
        except Exception as e:
            print(f"[{code} {row['Name']}] 처리 오류: {type(e).__name__} / {e}")
            
    return {
        "market": {"kospi": round(market_change, 2)},
        "stats": {"final": len(results)},
        "candidates": results
    }
