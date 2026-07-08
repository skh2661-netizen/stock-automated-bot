import FinanceDataReader as fdr
import pandas as pd
import datetime, pytz, time, traceback
from concurrent.futures import ThreadPoolExecutor

MIN_PRICE, MIN_AMOUNT = 1000, 15_000_000_000

def get_krx_retry():
    """✅ [필수 수정] FDR 버전 파편화 대비 컬럼명 호환성 완벽 방어"""
    for _ in range(2):
        try:
            krx = fdr.StockListing("KRX")
            if not krx.empty:
                if "Symbol" in krx.columns: krx.rename(columns={"Symbol": "Code"}, inplace=True)
                elif "ISU_CD" in krx.columns: krx.rename(columns={"ISU_CD": "Code"}, inplace=True)
                
                if "Change" in krx.columns: krx.rename(columns={"Change": "ChangesRatio"}, inplace=True)
                elif "ChgRate" in krx.columns: krx.rename(columns={"ChgRate": "ChangesRatio"}, inplace=True)
                elif "ChagesRatio" in krx.columns: krx.rename(columns={"ChagesRatio": "ChangesRatio"}, inplace=True)
                
                if "Code" in krx.columns:
                    krx = krx.loc[:, ~krx.columns.duplicated()].reset_index(drop=True)
                    krx["ChangesRatio"] = pd.to_numeric(krx["ChangesRatio"], errors="coerce").fillna(0)
                    return krx
        except Exception: time.sleep(1)
    return pd.DataFrame()

def remove_bad_targets(df):
    if df.empty or "Name" not in df.columns: return df
    pattern = r'스팩|ETF|ETN|우$|우[A-Z]$|[0-9]+우[A-Z]?$|제[0-9]+호'
    return df[~df['Name'].astype(str).str.contains(pattern, regex=True, na=False)]

def fetch_history(code, start_date):
    for _ in range(3):
        try:
            df = fdr.DataReader(code, start_date)
            if not df.empty: return code, df
        except: time.sleep(1)
    return code, None

def fetch_raw_candidates():
    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=180)).strftime("%Y-%m-%d")
    
    krx = remove_bad_targets(get_krx_retry())
    if krx.empty: return []
    
    krx['Close'] = pd.to_numeric(krx['Close'], errors='coerce')
    krx['Volume'] = pd.to_numeric(krx['Volume'], errors='coerce')
    krx['Amount'] = (krx['Close'] * krx['Volume']).fillna(0)
    
    candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & (krx['ChangesRatio'] >= 1)].sort_values("Amount", ascending=False).head(100)
    
    codes = candidates['Code'].apply(lambda x: str(x).zfill(6)).tolist()
    with ThreadPoolExecutor(max_workers=5) as ex: histories = dict(ex.map(lambda c: fetch_history(c, start_date), codes))
    
    raw_data = []
    for _, row in candidates.iterrows():
        code = str(row['Code']).zfill(6)
        hist = histories.get(code)
        if hist is not None and len(hist) >= 120:
            raw_data.append({"code": code, "name": row['Name'], "chg": float(row['ChangesRatio']), "hist": hist})
            
    return raw_data
