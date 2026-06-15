import FinanceDataReader as fdr
import pandas as pd
import datetime, asyncio, time
import pytz

try:
    import FinanceDataReader as fdr
except ImportError:
    import finance_datareader as fdr

from scoring import calculate_score
from risk import get_market_risk
from database import save_candidate

MIN_PRICE = 2000
MIN_AMOUNT = 10_000_000_000
MAX_CANDIDATES = 10

def get_krx_retry(): 
    for i in range(3):
        try: 
            krx = fdr.StockListing("KRX")
            if 'ChagesRatio' in krx.columns:
                krx.rename(columns={'ChagesRatio': 'ChangesRatio'}, inplace=True)
            elif 'ChgRate' in krx.columns:
                krx.rename(columns={'ChgRate': 'ChangesRatio'}, inplace=True)
            return krx
        except: 
            time.sleep(5)
    raise Exception("KRX API 연결 3회 실패")

def remove_bad_targets(df):
    pattern = '스팩|ETF|ETN|우$|우[A-Z]$|제[0-9]+호'
    return df[~df['Name'].str.contains(pattern, regex=True, na=False)]

def calculate_candle_position(row):
    high_low = row['High'] - row['Low']
    return ((row['Close'] - row['Low']) / high_low * 100) if high_low > 0 else None

async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    start_date = (now - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    risk = get_market_risk(start_date)
    risk_level = risk["level"]
    min_score = 75 if risk_level == 0 else (80 if risk_level == 1 else 85)
    
    try:
        market_hist = fdr.DataReader("KS11", start_date)
        market_change = (market_hist['Close'].iloc[-1] / market_hist['Close'].iloc[-6] - 1) * 100
    except:
        market_change = 0.0

    market_info = {"mode": "정상" if risk_level == 0 else "🚨 위험 제한 모드", "kospi": round(market_change, 2)}
    
    krx = get_krx_retry()
    total_count = len(krx)
    krx['Amount'] = krx['Close'] * krx['Volume']
    krx = remove_bad_targets(krx)
    
    krx['Max_OC'] = krx[['Open','Close']].max(axis=1)
    krx['Upper_Shadow'] = (krx['High'] - krx['Max_OC']) / krx['Close'] * 100
    
    condition = (krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & \
                (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18) & \
                (krx['Upper_Shadow'] <= 5)
    
    candidates = krx[condition].sort_values('Amount', ascending=False).head(30)
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
            
            vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
            if vol_ma <= 0 or (row['Volume'] / vol_ma) < 1.3: continue
            
            rs = ((hist['Close'].iloc[-1] / hist['Close'].iloc[-6] - 1) * 100) - market_change
            score = calculate_score(row['Amount'], (row['Volume']/vol_ma), row['ChangesRatio'], row['Upper_Shadow'], ma_gap, calculate_candle_position(row), rs, 0, risk_level)
            
            if score < min_score: continue
            
            buy_p, target_1, target_2, stop_p = int(row['Close'] * 0.985), int(row['Close'] * 1.023), int(row['Close'] * 1.063), int(row['Close'] * 0.970)
            
            save_candidate(run_type, code, row['Name'], score, buy_p, target_1, target_2, stop_p)
            results.append({"code": code, "name": row['Name'], "score": score, "price": int(row['Close'])})
        except: continue
            
    return {"market": market_info, "stats": {"total": total_count, "final": len(results)}, "candidates": results}
