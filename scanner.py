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
            krx.rename(columns={"ChagesRatio": "ChangesRatio", "ChgRate": "ChangesRatio"}, inplace=True)
            krx = krx.loc[:, ~krx.columns.duplicated()].reset_index(drop=True)
            # 단위 보정: /1000 제거
            krx["ChangesRatio"] = pd.to_numeric(krx["ChangesRatio"], errors="coerce").fillna(0)
            return krx
        except: time.sleep(5)
    raise Exception("KRX 연결 실패")

async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    try:
        risk_level = get_market_risk(start_date).get("level", 1)
    except: risk_level = 1
    
    krx = get_krx_retry()
    krx['Close'] = pd.to_numeric(krx['Close'], errors='coerce')
    krx['Amount'] = (krx['Close'] * pd.to_numeric(krx['Volume'], errors='coerce')).fillna(0)
    
    candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & 
                     (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18)].sort_values("Amount", ascending=False).head(100)
    
    results = []
    for _, row in candidates.iterrows():
        changes = float(row['ChangesRatio'])
        if run_type != "TEST":
            if run_type == "PRE_OPEN" and not (0 <= changes <= 7): continue
            if run_type == "BREAKOUT_1" and not (3 <= changes <= 12): continue
            if run_type == "CLOSE_BET" and not (1 <= changes <= 5): continue

        code = str(row['Code']).zfill(6)
        hist = fdr.DataReader(code, start_date)
        if len(hist) < 25: continue
        
        curr, vol_ma = hist.iloc[-1], hist['Volume'].rolling(20).mean().iloc[-1]
        ma20 = hist['Close'].rolling(20).mean().iloc[-1]
        ma_gap = (curr['Close'] - ma20) / ma20 * 100
        score = min(int(calculate_score(row['Amount'], curr['Volume']/vol_ma, changes, 0, ma_gap, 0, 0, 0, risk_level)), 100)
        
        buy_p, t1, t2, stop = int(curr['Close']*0.985), int(curr['Close']*1.023), int(curr['Close']*1.063), int(curr['Close']*0.970)
        
        # [데이터 계약(인자 20개) 완벽 복구]
        save_candidate(run_type, code, row['Name'], score, buy_p, t1, t2, stop, 
                       int(curr['Close']), round(changes,2), round(ma_gap,2), 0, 0, 0, 0, 0, 0, 0, 0, 0)
        
        results.append({"code": code, "name": row['Name'], "score": score, "price": int(curr['Close']), "chg": round(changes, 2), "buy_p": buy_p, "target_1": t1, "target_2": t2, "stop_p": stop, "ma_gap": round(ma_gap, 2), "rs": 0})
        if len(results) >= MAX_CANDIDATES: break
            
    return {"candidates": results}
