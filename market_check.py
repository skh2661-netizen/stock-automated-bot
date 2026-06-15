import datetime, pytz
import FinanceDataReader as fdr

def is_market_open():
    kst = pytz.timezone("Asia/Seoul")
    today = datetime.datetime.now(kst)
    # 주말 차단
    if today.weekday() >= 5: return False
    try:
        # 최근 5일 데이터 범위를 조회하여 휴장 여부 판단
        start = today - datetime.timedelta(days=5)
        df = fdr.DataReader("KS11", start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
        return not df.empty
    except Exception: return False
