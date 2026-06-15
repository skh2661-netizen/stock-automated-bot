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
            return krx
        except: time.sleep(5)
    raise Exception("KRX 데이터 연결 실패")

async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.datetime.now(kst)
    start_date = (now - datetime.timedelta(days=60)).strftime("%Y-%m-%d")

    risk = get_market_risk(start_date)
    risk_level = risk["level"]
    min_score = 75 if risk_level == 0 else (80 if risk_level == 1 else 85)

    try:
        market_hist = fdr.DataReader("KS11", start_date)
        market_change = (market_hist['Close'].iloc[-1] / market_hist['Close'].iloc[-6] - 1) * 100
    except: market_change = 0

    krx = get_krx_retry()
    krx['Amount'] = krx['Close'] * krx['Volume']
    # 윗꼬리 필터 계산
    krx['Upper_Shadow'] = (krx['High'] - krx[['Open','Close']].max(axis=1)) / krx['Close'] * 100
    
    condition = (krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & \
                (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18) & (krx['Upper_Shadow'] <= 5)
    
    candidates = krx[condition].sort_values("Amount", ascending=False).head(MAX_CANDIDATES)
    results = []

    for _, row in candidates.iterrows():
        code = str(row['Code']).zfill(6)
        await asyncio.sleep(0.15)
        try:
            hist = fdr.DataReader(code, start_date)
            if len(hist) < 25: continue
            
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            ma_gap = (row['Close'] - ma20) / ma20 * 100
            if ma_gap < 0: continue
            
            vol_ratio = row['Volume'] / hist['Volume'].rolling(20).mean().iloc[-1]
            if vol_ratio < 1.3: continue # 거래량 필터 복구
            
            five_change = (hist['Close'].iloc[-1] / hist['Close'].iloc[-6] - 1) * 100
            score = calculate_score(row['Amount'], vol_ratio, row['ChangesRatio'], row['Upper_Shadow'], 
                                   ma_gap, 0, (five_change - market_change), five_change, risk_level)
            
            if score < min_score: continue
            
            buy_p, t1, t2, stop = int(row['Close'] * 0.985), int(row['Close'] * 1.023), int(row['Close'] * 1.063), int(row['Close'] * 0.970)
            save_candidate(run_type, code, row['Name'], score, buy_p, t1, t2, stop)
            results.append({"code": code, "name": row['Name'], "score": score, "price": int(row['Close'])})
        except Exception as e: print(f"{code} 오류: {e}")
            
    return {
        "market": {"kospi": round(market_change, 2)},
        "stats": {"final": len(results)},
        "candidates": results
    }
