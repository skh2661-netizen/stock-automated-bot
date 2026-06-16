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
            rename_map = {
                "ChagesRatio": "ChangesRatio",
                "ChgRate": "ChangesRatio",
                "ChangeRate": "ChangesRatio",
                "Changes": "ChangesRatio"
            }
            for old, new in rename_map.items():
                if old in krx.columns and new not in krx.columns:
                    krx.rename(columns={old: new}, inplace=True)
            
            krx = krx.loc[:, ~krx.columns.duplicated()]
            if "ChangesRatio" not in krx.columns: raise Exception("등락률 컬럼 없음")
            return krx
        except Exception as e:
            print(f"KRX 연결 오류 {i+1}/3 : {e}")
            time.sleep(5)
    raise Exception("KRX 데이터 연결 실패")

def remove_bad_targets(df):
    if "Name" not in df.columns: return df
    pattern = '스팩|ETF|ETN|우$|우[A-Z]$|제[0-9]+호'
    return df[~df['Name'].str.contains(pattern, regex=True, na=False)]

def is_market_crash(market_change):
    return market_change <= -1.5

async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.datetime.now(kst)
    start_date = (now - datetime.timedelta(days=60)).strftime("%Y-%m-%d")

    try:
        risk = get_market_risk(start_date)
        risk_level = risk["level"]
    except:
        risk_level = 1
        
    if risk_level >= 2 and run_type == "CLOSE_SCAN":
        return {"market": {"kospi": 0, "kosdaq": 0, "risk_pct": 100, "mode": "🚨 하락장 종가베팅 차단"}, "stats": {"total": 0, "pass1": 0, "final": 0, "drop_ma20":0, "drop_vol":0, "drop_score":0, "drop_etc":0}, "candidates": []}
    
    min_score = 75 if risk_level == 0 else (80 if risk_level == 1 else 85)

    # 지수 1일 변화율 정확도 100% 동기화
    try:
        market_hist = fdr.DataReader("KS11", start_date)
        market_change = (market_hist['Close'].iloc[-1] / market_hist['Close'].iloc[-2] - 1) * 100 if len(market_hist) >= 2 else 0
    except: market_change = 0

    try:
        kq_hist = fdr.DataReader("KQ11", start_date)
        kosdaq_change = (kq_hist['Close'].iloc[-1] / kq_hist['Close'].iloc[-2] - 1) * 100 if len(kq_hist) >= 2 else 0
    except: kosdaq_change = 0

    if is_market_crash(market_change):
        return {
            "market": {"kospi": round(market_change, 2), "kosdaq": round(kosdaq_change, 2), "risk_pct": 100, "mode": "🚨 코스피 -1.5% 급락 (스캔 강제 정지)"},
            "stats": {"total": 0, "pass1": 0, "final": 0, "drop_ma20":0, "drop_vol":0, "drop_score":0, "drop_etc":0},
            "candidates": []
        }

    krx = remove_bad_targets(get_krx_retry())
    krx['Amount'] = krx['Close'] * krx['Volume']
    krx = krx.loc[~krx.index.duplicated(keep='first')]
    
    # 1차 필터링 및 통계 분리
    pass1_df = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & 
                         (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18)]
    pass1_count = len(pass1_df)

    candidates = pass1_df.sort_values("Amount", ascending=False).head(100)
    
    results = []
    drop_ma20 = drop_vol = drop_score = drop_etc = 0

    for _, row in candidates.iterrows():
        code = str(row['Code']).zfill(6)
        await asyncio.sleep(0.15)
        try:
            hist = fdr.DataReader(code, start_date)
            if len(hist) < 25:
                drop_etc += 1
                continue
            
            curr = hist.iloc[-1]
            
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            if pd.isna(ma20) or ma20 <= 0:
                drop_ma20 += 1
                continue
            ma_gap = (curr['Close'] - ma20) / ma20 * 100
            if ma_gap < 0:
                drop_ma20 += 1
                continue
                
            vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
            if pd.isna(vol_ma) or vol_ma <= 0 or curr['High'] <= 0:
                drop_vol += 1
                continue
            vol_ratio = curr['Volume'] / vol_ma  
            if vol_ratio < 1.3:
                drop_vol += 1
                continue
                
            upper_shadow = ((curr['High'] - max(curr['Open'], curr['Close'])) / curr['High'] * 100)
            candle_pos = ((curr['Close'] - curr['Low']) / (curr['High'] - curr['Low']) * 100) if (curr['High'] > curr['Low']) else 0
            
            if upper_shadow > 5:
                drop_score += 1
                continue
            
            p6 = hist['Close'].iloc[-6]
            if p6 <= 0:
                drop_etc += 1
                continue
            five_change = (curr['Close'] / p6 - 1) * 100
            
            score = calculate_score(row['Amount'], vol_ratio, row['ChangesRatio'], upper_shadow, 
                                   ma_gap, candle_pos, (five_change - market_change), five_change, risk_level)
            
            if score < min_score:
                drop_score += 1
                continue
            
            buy_p = int(curr['Close'] * 0.985)
            t1 = int(curr['Close'] * 1.023)
            t2 = int(curr['Close'] * 1.063)
            stop = int(curr['Close'] * 0.970)
            
            if save_candidate(run_type, code, row['Name'], score, buy_p, t1, t2, stop):
                results.append({
                    "code": code, "name": row['Name'], "score": score, "price": int(curr['Close']),
                    "buy_p": buy_p, "target_1": t1, "target_2": t2, "stop_p": stop,
                    "chg": round(row['ChangesRatio'], 2), "rs": round((five_change - market_change), 2),
                    "five_chg": round(five_change, 2), "kospi_chg": round(market_change, 2),
                    "ma_gap": round(ma_gap, 2), "c_vol": vol_ratio >= 2.0,
                    "c_rs": (five_change - market_change) > 0, "c_heat": ma_gap < 15,
                    "c_amt": row['Amount'] >= 50_000_000_000, "c_shadow": upper_shadow <= 3,
                    "cond_count": sum([vol_ratio >= 2.0, (five_change - market_change) > 0, ma_gap < 15, row['Amount'] >= 50_000_000_000, upper_shadow <= 3])
                })
            
            if len(results) >= MAX_CANDIDATES: break
        except Exception as e:
            drop_etc += 1
            print(f"[{code} {row['Name']}] 처리 오류: {type(e).__name__} / {e}")
            
    # 통계 보정: 1차 필터 통과자(pass1) 중 상위 100개만 연산하므로, 나머지 버려진 수치를 기타(etc)로 흡수
    drop_etc += max(0, pass1_count - (drop_ma20 + drop_vol + drop_score + drop_etc + len(results)))

    mode_str = "🟢 정상 작동" if risk_level < 2 else "🚨 위험장 (보수적 접근)"
    return {
        "market": {
            "kospi": round(market_change, 2),
            "kosdaq": round(kosdaq_change, 2), 
            "risk_pct": risk_level * 50,
            "mode": mode_str
        },
        "stats": {
            "total": len(krx), 
            "pass1": pass1_count, 
            "final": len(results),
            "drop_ma20": drop_ma20,
            "drop_vol": drop_vol,
            "drop_score": drop_score,
            "drop_etc": drop_etc
        },
        "candidates": results
    }
