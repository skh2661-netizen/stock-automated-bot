import FinanceDataReader as fdr
import pandas as pd
import logging

def fetch_raw_candidates():
    try:
        krx = fdr.StockListing('KRX')
        initial_count = len(krx)
        
        krx = krx[(krx['Close'] >= 1000) & (krx['ChangesRatio'] >= -2.0) & (krx['ChangesRatio'] <= 8.0) & (krx['Amount'] >= 10000000000)]
        filtered_count = len(krx)
        
        # 유동성(Amount)과 초기추세(Volume) 다중 풀 결합
        pool_a = krx.sort_values(by='Amount', ascending=False).head(150)
        pool_b = krx.sort_values(by='Volume', ascending=False).head(150)
        
        combined = pd.concat([pool_a, pool_b]).drop_duplicates(subset=['Code'])
        pool_count = len(combined)
        
        # Pre-Filter: Liquidity(40%) + Volume Ratio Proxy(40%) + Momentum(20%)
        combined['amount_rank'] = combined['Amount'].rank(ascending=True)
        combined['volume_rank'] = combined['Volume'].rank(ascending=True)
        combined['chg_rank'] = combined['ChangesRatio'].rank(ascending=True)
        
        combined['pre_score'] = (combined['amount_rank'] * 0.4) + (combined['volume_rank'] * 0.4) + (combined['chg_rank'] * 0.2)
        final_pool = combined.sort_values(by='pre_score', ascending=False).head(100)
        
        logging.info(f"Scanner Pipeline: KRX {initial_count} -> Base Filter {filtered_count} -> Multi-Pool {pool_count} -> PreScore {len(final_pool)}")
        return final_pool.to_dict('records')
    except Exception as e:
        logging.error(f"Scanner fetch failed: {e}")
        return []
