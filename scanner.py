import pandas as pd
import datetime, asyncio, time
import pytz
try:
    import FinanceDataReader as fdr
except ImportError:
    import finance_datareader as fdr

from scoring import calculate_score
from risk import get_market_risk
from database import save_candidate

MIN_PRICE = 2000
MIN_AMOUNT = 10_000_000_000
MAX_CANDIDATES = 10
MIN_SCORE = 70
VOL_THRESHOLD = 1.1

def get_krx_retry(): 
    # [V9.1 우회 전략] 직접적인 KRX 리스팅 호출 대신 우회 방식 시도
    for i in range(3):
        try: 
            # 시장별 리스트를 합치는 방식으로 차단 회피
            stocks = fdr.StockListing('KOSPI')
            stocks_kosdaq = fdr.StockListing('KOSDAQ')
            krx = pd.concat([stocks, stocks_kosdaq])
            
            rename_map = {"ChagesRatio": "ChangesRatio", "ChgRate": "ChangesRatio", "ChangeRate": "ChangesRatio", "Changes": "ChangesRatio"}
            for old, new in rename_map.items():
                if old in krx.columns and new not in krx.columns:
                    krx.rename(columns={old: new}, inplace=True)
            
            krx = krx.loc[:, ~krx.columns.duplicated()]
            if "ChangesRatio" not in krx.columns:
                krx['ChangesRatio'] = 0.0 # 예외처리
            return krx
        except Exception: 
            time.sleep(10) # 차단 방지를 위해 대기 시간 상향
    raise Exception("데이터 소스 연결 3회 실패: 거래소 접근 차단됨")

# ... (이하 remove_bad_targets, calculate_candle_position 동일)
# ... (scan_market 내 get_krx_retry() 호출부 동일)
