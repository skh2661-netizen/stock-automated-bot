import datetime, pytz
import FinanceDataReader as fdr

def is_market_open():
    kst = pytz.timezone("Asia/Seoul")
    today = datetime.datetime.now(kst)
    if today.weekday() >= 5: return False
    try:
        start = today - datetime.timedelta(days=5)
        df = fdr.DataReader("KS11", start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
        if df.empty: return False
        return df.index[-1].date() == today.date()
    except Exception: return False
