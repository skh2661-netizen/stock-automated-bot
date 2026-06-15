import datetime, pytz
import FinanceDataReader as fdr

def is_market_open():
    kst = pytz.timezone("Asia/Seoul")
    today = datetime.datetime.now(kst)
    if today.weekday() >= 5: return False
    try:
        df = fdr.DataReader("KS11", today.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
        return not df.empty
    except Exception: return False
