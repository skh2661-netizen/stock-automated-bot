import FinanceDataReader as fdr
import asyncio, datetime, pytz, time
from scoring import calculate_score
from database import save_candidate

MIN_PRICE = 2000
MIN_AMOUNT = 10_000_000_000
MAX_CANDIDATES = 10

def get_krx_retry():
    for i in range(3):
        try:
            krx = fdr.StockListing("KRX")
            if "ChagesRatio" in krx.columns: krx.rename(columns={"ChagesRatio": "ChangesRatio"}, inplace=True)
            return krx
        except: time.sleep(5)
    raise Exception("KRX 데이터 연결 실패")

def remove_bad_targets(df):
    pattern = '스팩|ETF|ETN|우$|우[A-Z]$|제[0-9]+호'
    return df[~df['Name'].str.contains(pattern, regex=True, na=False)]

async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.datetime.now(kst)
    start_date = (now - datetime.timedelta(days=60)).strftime("%Y-%m-%d")

    try:
        market_hist = fdr.DataReader("KS11", start_date)
        market_change = (market_hist['Close'].iloc[-1] / market_hist['Close'].iloc[-6] - 1) * 100
    except: market_change = 0

    krx = get_krx_retry()
    krx['Amount'] = krx['Close'] * krx['Volume']
    krx = remove_bad_targets(krx)
    
    condition = (krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & \
                (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18)
    
    # 10개로 제한하여 실행 안정성 확보
    candidates = krx[condition].sort_values("Amount", ascending=False).head(MAX_CANDIDATES)
    results = []

    for _, row in candidates.iterrows():
        code = str(row['Code']).zfill(6)
        await asyncio.sleep(0.15)
        try:
            hist = fdr.DataReader(code, start_date)
            if len(hist) < 25: continue
            
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            five_change = (hist['Close'].iloc[-1] / hist['Close'].iloc[-6] - 1) * 100
            vol_ratio = row['Volume'] / hist['Volume'].rolling(20).mean().iloc[-1]
            
            score = calculate_score(row['Amount'], vol_ratio, row['ChangesRatio'], 0, 
                                   ((row['Close']-ma20)/ma20*100), 0, (five_change-market_change), five_change, 0)
            
            if score < 75: continue
            
            buy_p, t1, t2, stop = int(row['Close'] * 0.985), int(row['Close'] * 1.023), int(row['Close'] * 1.063), int(row['Close'] * 0.970)
            save_candidate(run_type, code, row['Name'], score, buy_p, t1, t2, stop)
            results.append({"code": code, "name": row['Name'], "score": score, "price": int(row['Close']), "buy_p": buy_p})
        except Exception as e: print(f"{code} 오류: {e}")
            
    return {"market": {"kospi": round(market_change, 2)}, "stats": {"final": len(results)}, "candidates": results}
