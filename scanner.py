import FinanceDataReader as fdr
import pandas as pd
import datetime, asyncio, time
import sys

# [V8.4.2 안전 임포트]
try:
    import FinanceDataReader as fdr
except ImportError:
    import finance_datareader as fdr

from scoring import calculate_score, grade
from risk import get_market_risk
from database import save_candidate

MIN_PRICE = 2000
MIN_AMOUNT = 10_000_000_000
MAX_CANDIDATES = 10

def get_krx_retry(): 
    """KRX 데이터 수집 및 외부 라이브러리 오타 방어 패치"""
    for i in range(3):
        try: 
            krx = fdr.StockListing("KRX")
            # 🚨 FDR 라이브러리 개발자의 치명적 오타(ChagesRatio) 자동 교정
            if 'ChagesRatio' in krx.columns:
                krx.rename(columns={'ChagesRatio': 'ChangesRatio'}, inplace=True)
            elif 'ChgRate' in krx.columns:
                krx.rename(columns={'ChgRate': 'ChangesRatio'}, inplace=True)
            return krx
        except: 
            time.sleep(5)
    raise Exception("KRX 데이터 연결 3회 실패")

def remove_bad_targets(df):
    """스팩, ETF, 우선주 등 제외"""
    pattern = '스팩|ETF|ETN|우$|우[A-Z]$|제[0-9]+호'
    return df[~df['Name'].str.contains(pattern, regex=True, na=False)]

def calculate_candle_position(row):
    high_low = row['High'] - row['Low']
    return ((row['Close'] - row['Low']) / high_low * 100) if high_low > 0 else None

async def scan_market():
    now = datetime.datetime.now()
    start_date = (now - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    # 시장 위험 지수 연산
    risk = get_market_risk(start_date)
    risk_level = risk["level"]
    
    # 데이터 수집
    krx = get_krx_retry()
    krx['Amount'] = krx['Close'] * krx['Volume']
    krx = remove_bad_targets(krx)
    
    krx['Max_OC'] = krx[['Open','Close']].max(axis=1)
    krx['Upper_Shadow'] = (krx['High'] - krx['Max_OC']) / krx['Close'] * 100
    
    # 1차 필터
    condition = (krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & \
                (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18) & \
                (krx['Upper_Shadow'] <= 5) & (krx['Volume'] >= 300000)
    
    candidates = krx[condition].sort_values('Amount', ascending=False).head(30)
    results = []

    for _, row in candidates.iterrows():
        code = str(row['Code']).zfill(6)
        await asyncio.sleep(0.15)
        
        try:
            hist = fdr.DataReader(code, start_date)
            if len(hist) < 25: continue
            
            # MA20 위치 검증
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            ma_gap = (row['Close'] - ma20) / ma20 * 100
            if ma_gap < 0: continue
            
            # 모멘텀 검증
            five_change = (hist['Close'].iloc[-1] / hist['Close'].iloc[-6] - 1) * 100
            if five_change > 30: continue
            
            # 20일 고점 기준 눌림목 확인
            high20 = hist['High'].rolling(20).max().iloc[-2]
            if row['Close'] < high20 * 0.85: continue
            
            # 거래량 증가율 검증
            vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
            if vol_ma <= 0 or (row['Volume'] / vol_ma) < 1.3: continue
            
            # 종가 위치 확인
            close_pos = calculate_candle_position(row)
            if close_pos is None: continue
            
            # RS 지수 계산
            market = fdr.DataReader("KS11", start_date)
            market_change = (market['Close'].iloc[-1] / market['Close'].iloc[-6] - 1) * 100
            rs = five_change - market_change
            
            # 스코어 계산
            score = calculate_score(row['Amount'], (row['Volume']/vol_ma), row['ChangesRatio'], row['Upper_Shadow'], ma_gap, close_pos, rs, five_change, risk_level)
            if score < 75: continue
            
            # 데이터베이스 적재 및 결과 리스트 추가
            save_candidate(code, row['Name'], score, int(row['Close']), risk_level)
            results.append({"code":code, "name":row['Name'], "score":score, "grade":grade(score), "price":int(row['Close'])})
        except Exception as e:
            print(f"Error scanning {row['Name']}: {e}")
            continue
        
    return sorted(results, key=lambda x: x['score'], reverse=True)[:MAX_CANDIDATES]
