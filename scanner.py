import FinanceDataReader as fdr
import pandas as pd
import datetime, asyncio, time
import sys
import pytz

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
    raise Exception("KRX 데이터 연결 3회 실패")

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
    
    risk = get_market_risk(start_date)
    risk_level = risk["level"]
    
    try:
        kospi_df = fdr.DataReader("KS11", (now - datetime.timedelta(days=5)).strftime("%Y-%m-%d"))
        kospi_chg = (kospi_df['Close'].iloc[-1] / kospi_df['Close'].iloc[-2] - 1) * 100
    except:
        kospi_chg = 0.0

    try:
        kosdaq_df = fdr.DataReader("KQ11", (now - datetime.timedelta(days=5)).strftime("%Y-%m-%d"))
        kosdaq_chg = (kosdaq_df['Close'].iloc[-1] / kosdaq_df['Close'].iloc[-2] - 1) * 100
    except:
        kosdaq_chg = 0.0

    market_info = {
        "mode": "정상" if risk_level == 0 else "🚨 위험 제한 모드",
        "kospi": round(kospi_chg, 2),
        "kosdaq": round(kosdaq_chg, 2),
        "risk_pct": risk.get("score", 20)
    }
    
    krx = get_krx_retry()
    total_count = len(krx)
    krx['Amount'] = krx['Close'] * krx['Volume']
    krx = remove_bad_targets(krx)
    
    krx['Max_OC'] = krx[['Open','Close']].max(axis=1)
    krx['Upper_Shadow'] = (krx['High'] - krx['Max_OC']) / krx['Close'] * 100
    
    condition = (krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & \
                (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18) & \
                (krx['Upper_Shadow'] <= 5) & (krx['Volume'] >= 300000)
    
    pass1_count = len(krx[condition])
    candidates = krx[condition].sort_values('Amount', ascending=False).head(30)
    results = []

    for _, row in candidates.iterrows():
        code = str(row['Code']).zfill(6)
        await asyncio.sleep(0.15)
        
        try:
            hist = fdr.DataReader(code, start_date)
            if len(hist) < 25: continue
            
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            ma_gap = (row['Close'] - ma20) / ma20 * 100
            if ma_gap < 0: continue
            
            five_change = (hist['Close'].iloc[-1] / hist['Close'].iloc[-6] - 1) * 100
            if five_change > 30: continue
            
            high20 = hist['High'].rolling(20).max().iloc[-2]
            if row['Close'] < high20 * 0.85: continue
            
            vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
            if vol_ma <= 0 or (row['Volume'] / vol_ma) < 1.3: continue
            
            close_pos = calculate_candle_position(row)
            if close_pos is None: continue
            
            market = fdr.DataReader("KS11", start_date)
            market_change = (market['Close'].iloc[-1] / market['Close'].iloc[-6] - 1) * 100
            rs = five_change - market_change
            
            score = calculate_score(row['Amount'], (row['Volume']/vol_ma), row['ChangesRatio'], row['Upper_Shadow'], ma_gap, close_pos, rs, five_change, risk_level)
            if score < 75: continue
            
            amount_100m = int(row['Amount'] / 100000000)
            buy_p = int(row['Close'] * 0.985)
            target_1 = int(row['Close'] * 1.023)
            target_2 = int(row['Close'] * 1.063)
            stop_p = int(row['Close'] * 0.970)

            c_vol = (row['Volume'] / vol_ma) >= 2.0
            c_rs = rs > 5.0
            c_heat = ma_gap < 15.0
            c_amt = amount_100m >= 500
            c_shadow = row['Upper_Shadow'] < 2.0
            
            cond_count = sum([c_vol, c_rs, c_heat, c_amt, c_shadow])
            sig_type = "🔥 공격형 (모멘텀 극대화)" if ma_gap >= 15 else "🛡️ 정석형 (안정적 밸런스)"
            
            save_candidate(code, row['Name'], score, int(row['Close']), risk_level, round(rs, 2), round(ma_gap, 1), buy_p, target_1, stop_p)
            
            # 🚨 오류 해결: c_amt, c_shadow 파라미터 패키징 추가
            results.append({
                "code": code, "name": row['Name'], "score": score, "price": int(row['Close']),
                "amount": amount_100m, "chg": round(row['ChangesRatio'], 2),
                "vol_ratio": round(row['Volume'] / vol_ma, 1), "ma_gap": round(ma_gap, 1),
                "five_chg": round(five_change, 2), "kospi_chg": round(market_change, 2), "rs": round(rs, 2),
                "buy_p": buy_p, "target_1": target_1, "target_2": target_2, "stop_p": stop_p,
                "sig_type": sig_type, "cond_count": cond_count, 
                "c_vol": c_vol, "c_rs": c_rs, "c_heat": c_heat, "c_amt": c_amt, "c_shadow": c_shadow
            })
        except Exception as e:
            continue
            
    final_results = sorted(results, key=lambda x: x['score'], reverse=True)[:MAX_CANDIDATES]
    return {
        "market": market_info,
        "stats": {"total": total_count, "pass1": pass1_count, "final": len(final_results)},
        "candidates": final_results
    }
