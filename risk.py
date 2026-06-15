import FinanceDataReader as fdr
def get_market_risk(start_date):
    try:
        kospi = fdr.DataReader("KS11", start_date)
        if len(kospi) < 6: return {"level":0, "change":0}
        c = (kospi["Close"].iloc[-1] / kospi["Close"].iloc[-6] - 1) * 100
        if c <= -3: return {"level":2, "change":c, "message":"🚨 폭락 위험"}
        elif c <= -1.5: return {"level":1, "change":c, "message":"⚠️ 시장 주의"}
        return {"level":0, "change":c, "message":"✅ 정상"}
    except: return {"level":0, "change":0, "message":"데이터 오류"}
