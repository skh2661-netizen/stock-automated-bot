import FinanceDataReader as fdr
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

def remove_bad_targets(df):
    pattern = '스팩|ETF|ETN|우$|우[A-Z]$|제[0-9]+호'
    return df[~df['Name'].str.contains(pattern, regex=True, na=False)]

async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.datetime.now(kst)
    start_date = (now - datetime.timedelta(days=60)).strftime("%Y-%m-%d")

    # [1] 시장 위험도 복구
    risk = get_market_risk(start_date)
    risk_level = risk["level"]
    min_score = 75 if risk_level == 0 else (80 if risk_level == 1 else 85)

    # [2] 시장 RS 복구
    try:
        market_hist = fdr.DataReader("KS11", start_date)
        market_change = (market_hist['Close'].iloc[-1] / market_hist['Close'].iloc[-6] - 1) * 100
    except: market_change = 0

    krx = get_krx_retry()
    krx['Amount'] = krx['Close'] * krx['Volume']
    krx = remove_bad_targets(krx)
    
    # [3] 후보군 확대 (30 -> 100)
    condition = (krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & \
                (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18)
    
    candidates = krx[condition].sort_values("Amount", ascending=False).head(100)
    results = []

    for _, row in candidates.iterrows():
        code = str(row['Code']).zfill(6)
        await asyncio.sleep(0.15)
        try:
            hist = fdr.DataReader(code, start_date)
            if len(hist) < 25: continue
            
            curr = hist.iloc[-1]
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            ma_gap = (curr['Close'] - ma20) / ma20 * 100
            
            vol_ratio = row['Volume'] / hist['Volume'].rolling(20).mean().iloc[-1]
            upper_shadow = ((curr['High'] - max(curr['Open'], curr['Close'])) / curr['Close'] * 100)
            candle_pos = ((curr['Close'] - curr['Low']) / (curr['High'] - curr['Low']) * 100) if (curr['High'] != curr['Low']) else 0
            
            # 필터 적용
            if ma_gap < 0 or vol_ratio < 1.3 or upper_shadow > 5: continue
            
            five_change = (curr['Close'] / hist['Close'].iloc[-6] - 1) * 100
            # [4] RS(종목 상승률 - 시장 상승률) 계산 적용
            rs = five_change - market_change
            
            score = calculate_score(row['Amount'], vol_ratio, row['ChangesRatio'], upper_shadow, 
                                   ma_gap, candle_pos, rs, five_change, risk_level)
            
            if score < min_score: continue
            
            buy_p, t1, t2, stop = int(curr['Close'] * 0.985), int(curr['Close'] * 1.023), int(curr['Close'] * 1.063), int(curr['Close'] * 0.970)
            
            save_candidate(run_type, code, row['Name'], score, buy_p, t1, t2, stop)
            results.append({"code": code, "name": row['Name'], "score": score, "price": int(curr['Close']), "buy_p": buy_p})
            
            if len(results) >= MAX_CANDIDATES: break
        except Exception as e: print(f"{code} 오류: {e}")
            
    return {
        "market": {"kospi": round(market_change, 2)},
        "stats": {"final": len(results)},
        "candidates": results
    }
