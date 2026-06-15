import FinanceDataReader as fdr
import pandas as pd
import asyncio
import datetime
import pytz
import time
from scoring import calculate_score
from risk import get_market_risk
from database import save_candidate

# 설정 상수
MIN_PRICE = 2000
MIN_AMOUNT = 10_000_000_000
MAX_CANDIDATES = 10

def get_krx_retry():
    """KRX 데이터 수신 재시도 로직"""
    for i in range(3):
        try:
            krx = fdr.StockListing("KRX")
            if "ChagesRatio" in krx.columns: krx.rename(columns={"ChagesRatio": "ChangesRatio"}, inplace=True)
            elif "ChgRate" in krx.columns: krx.rename(columns={"ChgRate": "ChangesRatio"}, inplace=True)
            return krx
        except Exception as e:
            print(f"KRX 연결 실패 {i+1}/3 : {e}")
            time.sleep(5)
    raise Exception("KRX 데이터 연결 실패")

def remove_bad_targets(df):
    """스팩/ETF/우선주 제거"""
    pattern = '스팩|ETF|ETN|우$|우[A-Z]$|제[0-9]+호'
    return df[~df['Name'].str.contains(pattern, regex=True, na=False)]

def calculate_candle_position(row):
    high_low = row['High'] - row['Low']
    if high_low <= 0: return 0
    return ((row['Close'] - row['Low']) / high_low * 100)

def calculate_upper_shadow(row):
    max_oc = max(row['Open'], row['Close'])
    if row['Close'] <= 0: return 0
    return ((row['High'] - max_oc) / row['Close'] * 100)

async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.datetime.now(kst)
    start_date = (now - datetime.timedelta(days=60)).strftime("%Y-%m-%d")

    # 시장 위험도 및 점수 컷오프
    risk = get_market_risk(start_date)
    risk_level = risk["level"]
    min_score = 75 if risk_level == 0 else (80 if risk_level == 1 else 85)

    # 코스피 RS 기준값 (외부 호출)
    try:
        market_hist = fdr.DataReader("KS11", start_date)
        market_change = (market_hist['Close'].iloc[-1] / market_hist['Close'].iloc[-6] - 1) * 100
    except: market_change = 0

    krx = get_krx_retry()
    krx['Amount'] = krx['Close'] * krx['Volume']
    krx = remove_bad_targets(krx)
    krx['Upper_Shadow'] = krx.apply(calculate_upper_shadow, axis=1)

    # 1차 필터
    condition = (krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & \
                (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18) & \
                (krx['Upper_Shadow'] <= 5)
    
    candidates = krx[condition].sort_values("Amount", ascending=False).head(30)
    results = []

    for _, row in candidates.iterrows():
        code = str(row['Code']).zfill(6)
        await asyncio.sleep(0.15)
        try:
            hist = fdr.DataReader(code, start_date)
            if len(hist) < 25: continue
            
            # 지표 계산
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            ma_gap = (row['Close'] - ma20) / ma20 * 100
            if ma_gap < 0: continue
            
            five_change = (hist['Close'].iloc[-1] / hist['Close'].iloc[-6] - 1) * 100
            vol_ratio = row['Volume'] / hist['Volume'].rolling(20).mean().iloc[-1]
            if vol_ratio < 1.3: continue
            
            # 점수 계산 (복구 완료)
            score = calculate_score(
                row['Amount'], vol_ratio, row['ChangesRatio'], 
                row['Upper_Shadow'], ma_gap, calculate_candle_position(row), 
                (five_change - market_change), five_change, risk_level
            )
            
            if score < min_score: continue
            
            # 가격 계산
            buy_p, t1, t2, stop = int(row['Close'] * 0.985), int(row['Close'] * 1.023), int(row['Close'] * 1.063), int(row['Close'] * 0.970)
            
            # DB 저장 (인자 8개 정합성 확인 완료)
            save_candidate(run_type, code, row['Name'], score, buy_p, t1, t2, stop)
            
            results.append({
                "code": code, "name": row['Name'], "score": score, "price": int(row['Close']),
                "buy_p": buy_p, "target1": t1, "target2": t2, "stop": stop,
                "rs": round(five_change - market_change, 2), "ma_gap": round(ma_gap, 2), "vol_ratio": round(vol_ratio, 2)
            })
        except Exception as e:
            print(f"[{code}] 로직 수행 오류: {e}")
            continue
            
    return {"market": {"kospi": round(market_change, 2)}, "stats": {"final": len(results)}, "candidates": results}
