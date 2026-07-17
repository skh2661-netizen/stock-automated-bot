import FinanceDataReader as fdr
import pandas as pd
import logging
import datetime
import pytz

def fetch_history(code: str, days: int = 100):
    try:
        kst = pytz.timezone("Asia/Seoul")
        start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        return fdr.DataReader(code, start_date)
    except Exception as e:
        logging.error(f"History Fetch Failed ({code}): {e}")
        return None

def fetch_raw_candidates():
    try:
        krx = fdr.StockListing('KRX')
        
        # 1. Base Filter (최소 요건)
        krx = krx[(krx['Close'] >= 1000) & (krx['ChangesRatio'] >= -2.0) & (krx['ChangesRatio'] <= 8.0) & (krx['Amount'] >= 5000000000)]
        
        # 👑 2. Multi-Pool 다중 결합 (편향성 완전 제거)
        pool_a = krx.sort_values(by='Amount', ascending=False).head(150)           # 유동성 (기관/외인 Proxy)
        pool_b = krx.sort_values(by='Volume', ascending=False).head(150)           # 단기 거래량 폭증
        pool_c = krx.sort_values(by='ChangesRatio', ascending=False).head(150)     # 모멘텀
        pool_d = krx.sort_values(by='Marcap', ascending=False).head(150)           # 시총 상위 우량주
        
        combined = pd.concat([pool_a, pool_b, pool_c, pool_d]).drop_duplicates(subset=['Code'])
        
        # 3. Pre-Score 산출 (정규화된 다중 요소 결합)
        combined['rank_amt'] = combined['Amount'].rank()
        combined['rank_vol'] = combined['Volume'].rank()
        combined['rank_chg'] = combined['ChangesRatio'].rank()
        
        # 거래대금(40) + 거래량(30) + 모멘텀(30)
        combined['pre_score'] = (combined['rank_amt'] * 0.4) + (combined['rank_vol'] * 0.3) + (combined['rank_chg'] * 0.3)
        final_pool = combined.sort_values(by='pre_score', ascending=False).head(100)
        
        return final_pool.to_dict('records')
    except Exception as e:
        logging.error(f"Scanner fetch failed: {e}")
        return []
