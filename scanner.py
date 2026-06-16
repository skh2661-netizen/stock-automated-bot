import FinanceDataReader as fdr
import pandas as pd
import datetime, asyncio, time, sys, pytz
from scoring import calculate_score
from risk import get_market_risk
from database import save_candidate

MIN_PRICE, MIN_AMOUNT, MAX_CANDIDATES = 2000, 10_000_000_000, 10

def get_krx_retry(): 
    for i in range(3):
        try: 
            krx = fdr.StockListing("KRX")
            rename_map = {"ChagesRatio": "ChangesRatio", "ChgRate": "ChangesRatio", "ChangeRate": "ChangesRatio", "Changes": "ChangesRatio"}
            for old, new in rename_map.items():
                if old in krx.columns and new not in krx.columns:
                    krx.rename(columns={old: new}, inplace=True)
            return krx.loc[:, ~krx.columns.duplicated()]
        except: time.sleep(5)
    raise Exception("KRX 연결 실패")

def remove_bad_targets(df):
    pattern = '스팩|ETF|ETN|우$|우[A-Z]$|제[0-9]+호'
    return df[~df['Name'].str.contains(pattern, regex=True, na=False)]

async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    start_date = (now - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    risk = get_market_risk(start_date)
    
    krx = remove_bad_targets(get_krx_retry())
    krx['Amount'] = krx['Close'] * krx['Volume']
    krx = krx.loc[~krx.index.duplicated(keep='first')]
    krx['Upper_Shadow'] = (krx['High'] - krx[['Open','Close']].max(axis=1)) / krx['Close'] * 100
    
    condition = (krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & (krx['ChangesRatio'] >= 3)
    candidates = krx[condition].sort_values('Amount', ascending=False).head(100)
    
    results = []
    for _, row in candidates.iterrows():
        try:
            hist = fdr.DataReader(str(row['Code']).zfill(6), start_date)
            if len(hist) < 25: continue
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            if (row['Close'] - ma20) / ma20 * 100 < 0: continue
            vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
            if (row['Volume'] / vol_ma) < 1.3: continue
            
            # 인자 9개 정확히 매칭
            score = calculate_score(row['Amount'], (row['Volume']/vol_ma), row['ChangesRatio'], row['Upper_Shadow'], 0, 0, 0, 0, 0)
            if score < 75: continue
            
            save_candidate(str(row['Code']).zfill(6), row['Name'], score, int(row['Close']), 0, 0, 0, 0, 0, 0)
            results.append({"code": str(row['Code']).zfill(6), "name": row['Name'], "score": score})
        except: continue
    return {"market": {"kospi": 0, "kosdaq": 0, "mode": "🟢 V8.4.2 정상"}, "stats": {"total": len(krx), "final": len(results)}, "candidates": sorted(results, key=lambda x: x['score'], reverse=True)}
