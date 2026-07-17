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
    stats = {"krx_total": 0, "price_pass": 0, "amount_pass": 0, "change_pass": 0, "final_pool": 0}
    try:
        krx = fdr.StockListing('KRX')
        stats["krx_total"] = len(krx)
        
        # 👑 FDR 고질적 오타 버그 감지 및 강제 교정 (ChagesRatio -> ChangesRatio)
        if 'ChangesRatio' not in krx.columns and 'ChagesRatio' in krx.columns:
            krx.rename(columns={'ChagesRatio': 'ChangesRatio'}, inplace=True)
            
        if 'ChangesRatio' not in krx.columns:
            logging.error("[Scanner] CRITICAL: ChangesRatio column entirely missing from KRX.")
            return [], stats
        
        if 'Amount' not in krx.columns:
            krx['Amount'] = krx['Close'] * krx['Volume']
        else:
            krx['Amount'] = krx['Amount'].fillna(krx['Close'] * krx['Volume'])
            
        # 1. Price
        krx = krx[krx['Close'] >= 1000]
        stats["price_pass"] = len(krx)
        
        # 2. Amount
        krx = krx[krx['Amount'] >= 5000000000]
        stats["amount_pass"] = len(krx)
        
        # 3. Change
        krx = krx[(krx['ChangesRatio'] >= -2.0) & (krx['ChangesRatio'] <= 8.0)]
        stats["change_pass"] = len(krx)
        
        if krx.empty:
            logging.error("[Scanner] Filter decimated all stocks. Returning 0.")
            return [], stats
            
        pool_amt = krx.sort_values(by='Amount', ascending=False).head(150)
        pool_vol = krx.sort_values(by='Volume', ascending=False).head(150)
        pool_chg = krx.sort_values(by='ChangesRatio', ascending=False).head(150)
        
        combined = pd.concat([pool_amt, pool_vol, pool_chg]).drop_duplicates(subset=['Code'])
        combined['pre_score'] = (combined['Amount'].rank() * 0.4) + (combined['Volume'].rank() * 0.4) + (combined['ChangesRatio'].rank() * 0.2)
        final_pool = combined.sort_values(by='pre_score', ascending=False).head(100)
        
        stats["final_pool"] = len(final_pool)
        logging.info(f"Scanner Diagnostics: Total {stats['krx_total']} -> Price {stats['price_pass']} -> Amt {stats['amount_pass']} -> Chg {stats['change_pass']} -> Final {stats['final_pool']}")
        
        return final_pool.to_dict('records'), stats
    except Exception as e:
        logging.error(f"[Scanner] CRITICAL ERROR: {e}")
        return [], stats
