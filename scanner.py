import FinanceDataReader as fdr
import asyncio, datetime, pytz, time
from scoring import calculate_score
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

def remove_bad_targets(df):
    pattern = '스팩|ETF|ETN|우$|우[A-Z]$|제[0-9]+호'
    return df[~df['Name'].str.contains(pattern, regex=True, na=False)]

async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.datetime.now(kst)
    start_date = (now - datetime.timedelta(days=60)).strftime("%Y-%m-%d")

    # 1. 1차 필터링 (KRX 리스트 기준)
    krx = get_krx_retry()
    krx['Amount'] = krx['Close'] * krx['Volume']
    krx = remove_bad_targets(krx)
    condition = (krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & \
                (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18)
    candidates = krx[condition].sort_values("Amount", ascending=False).head(30)
    
    results = []
    for _, row in candidates.iterrows():
        code = str(row['Code']).zfill(6)
        await asyncio.sleep(0.15)
        try:
            hist = fdr.DataReader(code, start_date)
            if len(hist) < 25: continue
            
            # 2. 상세 지표 계산 (hist 데이터 기준)
            curr = hist.iloc[-1]
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            ma_gap = (curr['Close'] - ma20) / ma20 * 100
            
            vol_ratio = row['Volume'] / hist['Volume'].rolling(20).mean().iloc[-1]
            upper_shadow = ((curr['High'] - max(curr['Open'], curr['Close'])) / curr['Close'] * 100)
            candle_pos = ((curr['Close'] - curr['Low']) / (curr['High'] - curr['Low']) * 100) if (curr['High'] != curr['Low']) else 0
            
            # 필터 적용
            if ma_gap < 0 or vol_ratio < 1.3 or upper_shadow > 5: continue
            
            five_change = (curr['Close'] / hist['Close'].iloc[-6] - 1) * 100
            score = calculate_score(row['Amount'], vol_ratio, row['ChangesRatio'], upper_shadow, 
                                   ma_gap, candle_pos, (five_change - 0), five_change, 0)
            
            if score < 75: continue
            
            buy_p, t1, t2, stop = int(curr['Close'] * 0.985), int(curr['Close'] * 1.023), int(curr['Close'] * 1.063), int(curr['Close'] * 0.970)
            save_candidate(run_type, code, row['Name'], score, buy_p, t1, t2, stop)
            results.append({"code": code, "name": row['Name'], "score": score, "price": int(curr['Close'])})
            
            if len(results) >= MAX_CANDIDATES: break
        except: continue
            
    return {"stats": {"final": len(results)}, "candidates": results}
