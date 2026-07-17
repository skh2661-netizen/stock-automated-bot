import FinanceDataReader as fdr
import pandas as pd
import logging
import datetime
import pytz

def fetch_history(code: str, days: int = 120):
    try:
        kst = pytz.timezone("Asia/Seoul")
        start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        return fdr.DataReader(code, start_date)
    except Exception as e:
        logging.error(f"[Scanner] History Fetch Failed ({code}): {e}")
        return None

def fetch_raw_candidates():
    stats = {"krx_total": 0, "base_filter": 0, "multi_pool": 0, "final_pool": 0}
    try:
        krx = fdr.StockListing('KRX')
        stats["krx_total"] = len(krx)
        logging.info(f"[Scanner] 1. KRX Loaded: {len(krx)}")
        
        # Base Filter: ETF, 우선주 등 제외 및 최소 요건 (동전주, 하한가 제외)
        krx = krx[(krx['Close'] >= 1000) & (krx['ChangesRatio'] >= -3.0) & (krx['ChangesRatio'] <= 12.0) & (krx['Amount'] >= 3000000000)]
        stats["base_filter"] = len(krx)
        logging.info(f"[Scanner] 2. Base Filter Passed: {len(krx)}")
        
        if krx.empty:
            return [], stats
            
        # 👑 Multi-Pool 결합
        pool_amt = krx.sort_values(by='Amount', ascending=False).head(100)       # 유동성 우위
        pool_vol = krx.sort_values(by='Volume', ascending=False).head(100)       # 거래량 우위
        pool_chg = krx.sort_values(by='ChangesRatio', ascending=False).head(100) # 모멘텀 우위
        
        combined = pd.concat([pool_amt, pool_vol, pool_chg]).drop_duplicates(subset=['Code'])
        stats["multi_pool"] = len(combined)
        logging.info(f"[Scanner] 3. Multi-Pool Merged: {len(combined)}")
        
        # Pre-Score 정규화 및 상위 추출
        combined['rank_amt'] = combined['Amount'].rank()
        combined['rank_vol'] = combined['Volume'].rank()
        combined['pre_score'] = combined['rank_amt'] + combined['rank_vol']
        
        final_pool = combined.sort_values(by='pre_score', ascending=False).head(80)
        stats["final_pool"] = len(final_pool)
        logging.info(f"[Scanner] 4. Final Pool Ready: {len(final_pool)}")
        
        return final_pool.to_dict('records'), stats
    except Exception as e:
        logging.error(f"[Scanner] Fetch CRITICAL ERROR: {e}")
        return [], stats
