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

async def scan_market():
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    start_date = (now - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    # 런타임 타입 자동 판별 (08:50=OPEN, 15:00=CLOSE)
    run_type = "OPEN" if now.hour < 12 else "CLOSE"
    
    risk = get_market_risk(start_date)
    risk_level = risk["level"]
    min_score = 75 if risk_level == 0 else (80 if risk_level == 1 else 85)
    
    # [최적화] 시장 데이터는 루프 밖에서 1회 호출
    try:
        market_hist = fdr.DataReader("KS11", start_date)
        market_change = (market_hist['Close'].iloc[-1] / market_hist['Close'].iloc[-6] - 1) * 100
    except:
        market_change = 0.0

    market_info = {
        "mode": "정상" if risk_level == 0 else "🚨 위험 제한 모드",
        "kospi": round(market_change, 2),
        "risk_pct": risk.get("score", 20)
    }
    
    krx = get_krx_retry()
    total_count = len(krx)
    krx['Amount'] = krx['Close'] * krx['Volume']
    krx = remove_bad_targets(krx)
    
    krx['Max_OC'] = krx[['Open','Close']].max(axis=1)
    krx['Upper_Shadow'] = (krx['High'] - krx['Max_OC']) / krx['Close'] * 100
    
    # [최적화] 거래대금 중심 필터링
    condition = (krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & \
                (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18) & \
                (krx['Upper_Shadow'] <= 5)
    
    pass1_count = len(krx[condition])
    candidates = krx[condition].sort_values('Amount', ascending=False).head(30)
    
    results = []
    fail_stats = {"ma20": 0, "vol": 0, "score": 0, "etc": 0}

    for _, row in candidates.iterrows():
        code = str(row['Code']).zfill(6)
        await asyncio.sleep(0.15)
        
        try:
            hist = fdr.DataReader(code, start_date)
            if len(hist) < 25: 
                fail_stats["etc"] += 1; continue
            
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            ma_gap = (row['Close'] - ma20) / ma20 * 100
            if ma_gap < 0: 
                fail_stats["ma20"] += 1; continue
            
            five_change = (hist['Close'].iloc[-1] / hist['Close'].iloc[-6] - 1) * 100
            
            vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
            if vol_ma <= 0 or (row['Volume'] / vol_ma) < 1.3: 
                fail_stats["vol"] += 1; continue
            
            close_pos = calculate_candle_position(row)
            rs = five_change - market_change
            
            score = calculate_score(row['Amount'], (row['Volume']/vol_ma), row['ChangesRatio'], row['Upper_Shadow'], ma_gap, close_pos, rs, five_change, risk_level)
            
            if score < min_score: 
                fail_stats["score"] += 1; continue
            
            buy_p = int(row['Close'] * 0.985)
            target_1 = int(row['Close'] * 1.023)
            target_2 = int(row['Close'] * 1.063)
            stop_p = int(row['Close'] * 0.970)
            
            # DB 저장 (신규 스키마 준수)
            save_candidate(run_type, code, row['Name'], score, buy_p, target_1, target_2, stop_p)
            
            results.append({
                "code": code, "name": row['Name'], "score": score, "price": int(row['Close']),
                "chg": round(row['ChangesRatio'], 2), "ma_gap": round(ma_gap, 1),
                "buy_p": buy_p, "target_1": target_1, "target_2": target_2, "stop_p": stop_p,
                "c_vol": (row['Volume'] / vol_ma) >= 2.0, "c_rs": rs > 5.0, 
                "c_heat": ma_gap < 15.0, "c_amt": row['Amount'] >= 50_000_000_000, 
                "c_shadow": row['Upper_Shadow'] < 2.0, "cond_count": 0, "five_chg": round(five_change, 2),
                "kospi_chg": round(market_change, 2), "rs": round(rs, 2)
            })
        except Exception as e:
            fail_stats["etc"] += 1
            print(f"🚨 [{code}] 연산 실패: {e}")
            continue
            
    return {
        "market": market_info,
        "stats": {"total": total_count, "pass1": pass1_count, "final": len(results)},
        "fail_stats": fail_stats,
        "candidates": sorted(results, key=lambda x: x['score'], reverse=True)[:MAX_CANDIDATES]
    }
