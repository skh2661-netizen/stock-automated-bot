import FinanceDataReader as fdr
import pandas as pd
import asyncio, datetime, pytz, time
from scoring import calculate_score
from risk import get_market_risk
from database import save_candidate

# [중략: get_krx_retry, remove_bad_targets, calculate_candle_position 동일]

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
    except: market_change = 0.0

    krx = get_krx_retry()
    krx['Amount'] = krx['Close'] * krx['Volume']
    krx = remove_bad_targets(krx)
    condition = (krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & \
                (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18) & \
                ((krx['High'] - krx[['Open','Close']].max(axis=1)) / krx['Close'] * 100 <= 5)
    
    candidates = krx[condition].sort_values('Amount', ascending=False).head(30)
    results = []

    for _, row in candidates.iterrows():
        code = str(row['Code']).zfill(6)
        await asyncio.sleep(0.15)
        try:
            hist = fdr.DataReader(code, start_date)
            if len(hist) < 25: continue
            
            ma_gap = (row['Close'] - hist['Close'].rolling(20).mean().iloc[-1]) / hist['Close'].rolling(20).mean().iloc[-1] * 100
            if ma_gap < 0: continue
            
            # [수정] 5일 상승률 실제값 계산
            five_change = (hist['Close'].iloc[-1] / hist['Close'].iloc[-6] - 1) * 100
            vol_ratio = row['Volume'] / hist['Volume'].rolling(20).mean().iloc[-1]
            if vol_ratio < 1.3: continue
            
            rs = five_change - market_change
            score = calculate_score(row['Amount'], vol_ratio, row['ChangesRatio'], 0, ma_gap, 0, rs, five_change, risk_level)
            if score < min_score: continue
            
            buy_p, t1, t2, stop = int(row['Close'] * 0.985), int(row['Close'] * 1.023), int(row['Close'] * 1.063), int(row['Close'] * 0.970)
            
            # [정합성] DB 인자 순서: run_type, code, name, score, buy_p, target1, target2, stop
            save_candidate(run_type, code, row['Name'], score, buy_p, t1, t2, stop)
            
            results.append({
                "code": code, "name": row['Name'], "score": score, "price": int(row['Close']),
                "buy_p": buy_p, "target1": t1, "target2": t2, "stop": stop,
                "rs": round(rs, 2), "ma_gap": round(ma_gap, 1), "vol_ratio": round(vol_ratio, 1)
            })
        except: continue
            
    return {"market": {"kospi": round(market_change, 2)}, "stats": {"final": len(results)}, "candidates": results}
