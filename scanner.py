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
            rename_map = {"ChagesRatio": "ChangesRatio", "ChgRate": "ChangesRatio", "ChangeRate": "ChangesRatio", "Changes": "ChangesRatio"}
            for old, new in rename_map.items():
                if old in krx.columns: krx.rename(columns={old: new}, inplace=True)
            if "ChangesRatio" not in krx.columns: raise Exception("등락률 컬럼 없음")
            krx = krx.loc[:, ~krx.columns.duplicated()].reset_index(drop=True)
            krx["ChangesRatio"] = pd.to_numeric(krx["ChangesRatio"], errors="coerce").fillna(0) / 1000
            return krx
        except: time.sleep(5)
    raise Exception("KRX 연결 실패")

async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.datetime.now(kst)
    start_date = (now - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    # 리스크 및 시장 데이터 로딩
    try:
        risk_data = get_market_risk(start_date)
        risk_level = risk_data.get("level", 1)
    except: risk_level = 1
    
    krx = get_krx_retry()
    krx['Close'] = pd.to_numeric(krx['Close'], errors='coerce')
    krx['Volume'] = pd.to_numeric(krx['Volume'], errors='coerce')
    krx['Amount'] = (krx['Close'] * krx['Volume']).fillna(0)
    
    candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & 
                     (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18)].head(100)
    
    results = []
    for _, row in candidates.iterrows():
        # [V8.5 전술 필터 레이어]
        changes = float(row['ChangesRatio'])
        if run_type == "PRE_OPEN" and not (0 <= changes <= 7): continue
        if run_type == "BREAKOUT_1" and not (3 <= changes <= 12): continue
        if run_type == "CLOSE_BET" and not (1 <= changes <= 5): continue

        code = str(row['Code']).zfill(6)
        hist = fdr.DataReader(code, start_date)
        if len(hist) < 25: continue
        
        curr = hist.iloc[-1]
        vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
        ma20 = hist['Close'].rolling(20).mean().iloc[-1]
        ma_gap = (curr['Close'] - ma20) / ma20 * 100
        vol_ratio = curr['Volume'] / vol_ma
        
        # [점수 산출 및 무결성 수정 (이 부분이 핵심)]
        score = int(calculate_score(row['Amount'], vol_ratio, changes, 0, ma_gap, 0, 0, 0, risk_level))
        score = min(score, 100) # <- 무결성 수정 코드
        
        save_candidate(run_type, code, row['Name'], score, 0, 0, 0, 0)
        results.append({"code": code, "name": row['Name'], "score": score})
        if len(results) >= MAX_CANDIDATES: break
            
    return {"market": {"kospi": 0}, "stats": {"final": len(results)}, "candidates": results}
