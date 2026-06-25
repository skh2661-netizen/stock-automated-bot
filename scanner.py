import FinanceDataReader as fdr
import pandas as pd
import asyncio, datetime, pytz, time, requests, sqlite3, os, traceback
from scoring import calculate_breakout_score, calculate_close_score, calculate_preopen_score, get_conviction_score, get_prime_score
from database import save_candidate, DB_PATH

MIN_PRICE, MIN_AMOUNT, MAX_CANDIDATES = 1000, 15_000_000_000, 15

def calculate_trade_plan(price, buy_p, score, ma_gap):
    if score >= 80 and ma_gap <= 10: target1, target2 = price * 1.10, price * 1.18
    elif ma_gap <= 5: target1, target2 = price * 1.08, price * 1.15
    elif ma_gap <= 15: target1, target2 = price * 1.05, price * 1.10
    else: target1, target2 = price * 1.03, price * 1.06
    return int(target1), int(target2), int(buy_p * 0.95)

def get_krx_retry():
    # 생략 없는 원본 로직 유지 (기존과 동일)
    # ... (get_krx_retry 로직 동일 적용)
    # [생략방지] get_krx_retry 전체 로직 포함
    for _ in range(2):
        try:
            krx = fdr.StockListing("KRX")
            if not krx.empty:
                if "Symbol" in krx.columns: krx.rename(columns={"Symbol": "Code"}, inplace=True)
                elif "ISU_CD" in krx.columns: krx.rename(columns={"ISU_CD": "Code"}, inplace=True)
                if "Code" in krx.columns:
                    krx.rename(columns={"ChagesRatio": "ChangesRatio", "ChgRate": "ChangesRatio"}, inplace=True)
                    krx = krx.loc[:, ~krx.columns.duplicated()].reset_index(drop=True)
                    krx["ChangesRatio"] = pd.to_numeric(krx["ChangesRatio"], errors="coerce").fillna(0)
                    return krx
        except Exception: time.sleep(1)
    return pd.DataFrame(columns=['Code', 'Name', 'Close', 'ChangesRatio', 'Amount', 'Volume'])

def remove_bad_targets(df):
    pattern = r'스팩|ETF|ETN|우$|우[A-Z]$|[0-9]+우[A-Z]?$|제[0-9]+호'
    return df[~df['Name'].str.contains(pattern, regex=True, na=False)]

def get_market_indices():
    try:
        kst = pytz.timezone("Asia/Seoul")
        start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=40)).strftime("%Y-%m-%d")
        kospi = fdr.DataReader("KS11", start_date)
        kosdaq = fdr.DataReader("KQ11", start_date)
        kp_1d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-2]) - 1) * 100
        kd_1d = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-2]) - 1) * 100
        return round(kp_1d, 2), round(kd_1d, 2)
    except: return 0.0, 0.0

async def scan_market(run_type="OPEN_SCAN"):
    try:
        kst = pytz.timezone("Asia/Seoul")
        start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
        kp_1d, kd_1d = get_market_indices()
        krx = remove_bad_targets(get_krx_retry())
        
        krx['Close'] = pd.to_numeric(krx['Close'], errors='coerce')
        krx['Volume'] = pd.to_numeric(krx['Volume'], errors='coerce')
        krx['Amount'] = (krx['Close'] * krx['Volume']).fillna(0)
        krx['ChangesRatio'] = pd.to_numeric(krx['ChangesRatio'], errors='coerce').fillna(0)
        
        # [수정] stats에 data_error 복구
        stats = {"total": len(krx), "final": 0, "pass1": 0, "fail_heat": 0, "fail_score": 0, "data_error": False}
        
        # [수정] TEST 모드 필터 원본 복구
        if run_type == "TEST": candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT)]
        else: candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & (krx['ChangesRatio'] >= 1) & (krx['ChangesRatio'] <= 18)].sort_values("Amount", ascending=False).head(100)
        
        results = []
        for _, row in candidates.iterrows():
            stats["pass1"] += 1
            code = str(row['Code']).zfill(6)
            try: hist = fdr.DataReader(code, start_date)
            except Exception: continue
            if len(hist) < 25: continue
            
            # [수정] Amt 계산 위치 OHLCV 직후 이동
            hist = hist.copy()
            hist['Amt'] = hist['Close'] * hist['Volume']
            
            curr, ma20 = hist.iloc[-1], hist['Close'].rolling(20).mean().iloc[-1]
            vr = curr['Volume'] / (hist['Volume'].rolling(20).mean().iloc[-1] + 1)
            ma_gap = (curr['Close'] - ma20) / ma20 * 100
            shadow_ratio = (curr['High'] - curr['Close']) / (curr['High'] - curr['Low'] + 0.0001)
            cp_val = (curr['Close'] - curr['Low']) / (curr['High'] - curr['Low'] + 0.0001) * 100
            
            # [수정] CLOSE_BET 히트 조건 및 rs_5d, 20d 계산
            heat_limit = 35 if (run_type == "CLOSE_BET" and row['Amount'] >= 100_000_000_000 and cp_val >= 70) else (35 if row['Amount'] >= 100_000_000_000 else 25)
            is_overheated = ma_gap > heat_limit
            
            rs_1d = float(row['ChangesRatio']) - kp_1d
            rs_5d = ((hist['Close'].iloc[-1] / hist['Close'].iloc[-6]) - 1) * 100 - (kp_1d * 5)
            rs_20d = ((hist['Close'].iloc[-1] / hist['Close'].iloc[-21]) - 1) * 100 - (kp_1d * 20)
            
            amt_p20 = hist['Amt'].iloc[-21:-1].mean()
            amt_s = min(round(((hist['Amt'].tail(6).iloc[:-1].mean() if not pd.isna(hist['Amt'].tail(6).iloc[:-1].mean()) else 0) / (amt_p20 + 1)), 2), 5.0) if (not pd.isna(amt_p20) and amt_p20 > 0) else 0
            
            ps = get_prime_score(rs_1d, rs_5d, rs_20d, amt_s, True)
            if is_overheated and ps < 70: stats["fail_heat"] += 1; continue
            
            # [수정] Score Engine 복구
            if run_type == "PRE_OPEN": score = calculate_preopen_score(row['Amount'], vr, float(row['ChangesRatio']), shadow_ratio, cp_val, rs_1d, risk_level)
            elif "BREAKOUT" in run_type: score = calculate_breakout_score(row['Amount'], vr, float(row['ChangesRatio']), rs_1d, risk_level)
            else: score = calculate_close_score(row['Amount'], vr, float(row['ChangesRatio']), shadow_ratio, 0, cp_val, rs_1d, risk_level, ma_gap)
            if score < 55: stats["fail_score"] += 1; continue
            
            # [수정] candidate_type 원본 로직 복구
            if is_overheated: candidate_type = "WATCH"
            elif score >= 55 and ma_gap <= 15: candidate_type = "ENTRY"
            elif ps >= 75: candidate_type = "LEADER" if ma_gap <= 15 else "WATCH"
            elif score >= 55 and ma_gap > 15: candidate_type = "WATCH"
            else: candidate_type = "WATCH"

            t1, t2, stop = calculate_trade_plan(curr['Close'], curr['Close']*0.98, score, ma_gap)
            results.append({"code": code, "name": row['Name'], "score": score, "price": int(curr['Close']), "chg": round(float(row['ChangesRatio']), 2), "buy_p": int(curr['Close']*0.98), "ma_gap": round(ma_gap, 2), "rs_1d": round(rs_1d, 2), "rs_5d": round(rs_5d, 2), "rs_20d": round(rs_20d, 2), "amount": int(row['Amount']), "conviction": get_conviction_score(rs_1d, row['Amount'], vr, risk_level, ma_gap, cp_val), "prime_score": ps, "prime_final": round((ps*0.5 + score*0.3 + max(0, 100-max(ma_gap,0))*0.2), 1), "target_1": t1, "target_2": t2, "stop_p": stop, "amount_strength": amt_s, "pullback_price": int(curr['Close'] * 0.95), "vr": round(vr, 2), "is_prime_leader": False, "is_overheated": is_overheated, "type": candidate_type})
        
        results = list({x["code"]: x for x in results}.values())
        results.sort(key=lambda x: ({"ENTRY": 3, "LEADER": 2, "WATCH": 1}.get(x['type'], 0), x['prime_final']), reverse=True)
        results = results[:MAX_CANDIDATES]
        if results: max(results, key=lambda x: x['prime_final'])['is_prime_leader'] = True
        
        for item in results:
            save_candidate(run_type, item['code'], item['name'], item['score'], item['buy_p'], item['target_1'], item['target_2'], item['stop_p'], item['price'], item['chg'], item['ma_gap'], item['prime_score'], item['prime_final'], item['conviction'], item['amount_strength'], item['rs_1d'], item['rs_5d'], item['rs_20d'], 1 if item['is_prime_leader'] else 0, risk_level)
        stats["final"] = len(results)
        return {"market": {"mode": run_type}, "stats": stats, "candidates": results}
    except Exception:
        traceback.print_exc()
        return {"stats": {"total": 0, "final": 0, "data_error": True}, "candidates": []}
