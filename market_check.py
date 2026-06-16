import datetime, pytz
import FinanceDataReader as fdr

def is_market_open():
    kst = pytz.timezone("Asia/Seoul")
    today = datetime.datetime.now(kst)
    
    # 1. 주말 체크 (토/일은 무조건 휴장)
    if today.weekday() >= 5: return False
    
    # 2. 장 마감 후라면 데이터로 확인 가능
    if today.hour >= 16:
        try:
            start = today - datetime.timedelta(days=5)
            df = fdr.DataReader("KS11", start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
            if df.empty: return False
            return df.index[-1].date() == today.date()
        except Exception: return False
        
    # 3. [핵심 수정] 장중(오전 9시 ~ 오후 3시 30분)에는 평일이면 무조건 개장으로 간주
    return True
