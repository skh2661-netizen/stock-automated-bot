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
        return None

def fetch_raw_candidates():
    stats = {"krx_total": 0, "filter_pass": 0, "pool_pass": 0}
    try:
        krx = fdr.StockListing('KRX')
        stats["krx_total"] = len(krx)
        
        if 'ChangesRatio' not in krx.columns and 'ChagesRatio' in krx.columns:
            krx.rename(columns={'ChagesRatio': 'ChangesRatio'}, inplace=True)
            
        if 'Amount' not in krx.columns: krx['Amount'] = krx['Close'] * krx['Volume']
        else: krx['Amount'] = krx['Amount'].fillna(krx['Close'] * krx['Volume'])
            
        # Base Filter
        krx = krx[(krx['Close'] >= 1000) & (krx['Amount'] >= 5000000000) & (krx['ChangesRatio'] >= -2.0) & (krx['ChangesRatio'] <= 8.0)]
        stats["filter_pass"] = len(krx)
        
        if krx.empty: return [], stats
            
        # Multi-Pool
        pool_amt = krx.sort_values(by='Amount', ascending=False).head(150)
        pool_vol = krx.sort_values(by='Volume', ascending=False).head(150)
        pool_chg = krx.sort_values(by='ChangesRatio', ascending=False).head(150)
        
        combined = pd.concat([pool_amt, pool_vol, pool_chg]).drop_duplicates(subset=['Code'])
        combined['pre_score'] = (combined['Amount'].rank() * 0.4) + (combined['Volume'].rank() * 0.4) + (combined['ChangesRatio'].rank() * 0.2)
        final_pool = combined.sort_values(by='pre_score', ascending=False).head(100)
        
        stats["pool_pass"] = len(final_pool)
        return final_pool.to_dict('records'), stats
    except Exception as e:
        logging.error(f"[Scanner] CRITICAL ERROR: {e}")
        return [], stats
