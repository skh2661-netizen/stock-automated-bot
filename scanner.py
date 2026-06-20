import FinanceDataReader as fdr
import pandas as pd
import asyncio, datetime, pytz, time, math
import requests
import sqlite3
import os
from scoring import calculate_score, get_conviction_score, get_prime_score
from risk import get_market_risk
from database import save_candidate, DB_PATH

MIN_PRICE, MIN_AMOUNT, MAX_CANDIDATES = 2000, 15_000_000_000, 10

def safe_json_decode(res, channel_name):
    try:
        text_stripped = res.text.strip()
        if text_stripped.startswith("<") or "text/html" in res.headers.get("Content-Type", "").lower():
            print(f"🚨 [{channel_name}] HTML 점검 페이지 반환 감지. 우회합니다.")
            return None
        return res.json()
    except Exception as e:
        print(f"🚨 [{channel_name}] JSON 디코딩 실패: {e}")
        return None

def get_krx_retry():
    for i in range(2):
        try:
            krx = fdr.StockListing("KRX")
            if not krx.empty and "Symbol" in krx.columns:
                krx.rename(columns={"ChagesRatio": "ChangesRatio", "ChgRate": "ChangesRatio"}, inplace=True)
                krx = krx.loc[:, ~krx.columns.duplicated()].reset_index(drop=True)
                krx["ChangesRatio"] = pd.to_numeric(krx["ChangesRatio"], errors="coerce").fillna(0)
                return krx
        except Exception as e:
            print(f"⚠️ FDR KRX 수집 지연: {e}")
            time.sleep(1)

    print("🔄 [폴백 2] 네이버 API 우회")
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        df_list = []
        for market in ["KOSPI", "KOSDAQ"]:
            url = f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page=1&pageSize=2500"
            res = requests.get(url, headers=headers, timeout=5)
            data = safe_json_decode(res, f"네이버-{market}")
            if not data: continue
            
            stocks = data.get('stocks', [])
            if not stocks: continue
            
            df = pd.DataFrame(stocks)
            df.rename(columns={'itemCode': 'Code', 'stockName': 'Name', 'closePrice': 'Close', 'fluctuationsRatio': 'ChangesRatio', 'accumulatedTradingVolume': 'Volume'}, inplace=True)
            for col in ['Close', 'Volume']:
                df[col] = df[col].astype(str).str.replace(',', '')
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            df['ChangesRatio'] = pd.to_numeric(df['ChangesRatio'], errors='coerce').fillna(0)
            df_list.append(df)
            
        if df_list: return pd.concat(df_list, ignore_index=True)
    except Exception as e:
        print(f"🚨 네이버 우회 실패: {e}")

    print("🔄 [폴백 3] 로컬 SQLite 캐시 복원")
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            cache_df = pd.read_sql_query("SELECT code AS Code, name AS Name, price AS Close, chg AS ChangesRatio FROM candidates WHERE date = (SELECT max(date) FROM candidates)", conn)
            conn.close()
            if not cache_df.empty: return cache_df
        except Exception as e:
            print(f"🚨 캐시 로드 실패: {e}")

    print("❌ [최종 장애] 빈 데이터 프레임 반환")
    return pd.DataFrame(columns=['Code', 'Name', 'Close', 'ChangesRatio', 'Amount', 'Volume'])

def remove_bad_targets(df):
    if "Name" not in df.columns: return df
    pattern = r'스팩|ETF|ETN|우$|우[A-Z]$|[0-9]+우[A-Z]?$|제[0-9]+호'
    return df[~df['Name'].str.contains(pattern, regex=True, na=False)]

def get_market_indices():
    try:
        kst = pytz.timezone("Asia/Seoul")
        start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=40)).strftime("%Y-%m-%d")
        kospi = fdr.DataReader("KS11", start_date)
        kosdaq = fdr.DataReader("KQ11", start_date)
        kp_1d = ((kospi['Close'].iloc[-1] / kospi
