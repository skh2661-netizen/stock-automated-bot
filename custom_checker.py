import FinanceDataReader as fdr
import pandas as pd
import datetime, pytz
from scoring import calculate_score

def analyze_single_stock(code, stock_name="지정종목"):
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.datetime.now(kst)
    start_date = (now - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    try:
        # 시장 데이터 (상대강도 RS 계산용)
        market_hist = fdr.DataReader("KS11", start_date)
        market_change = (market_hist['Close'].iloc[-1] / market_hist['Close'].iloc[-6] - 1) * 100 if len(market_hist) >= 6 else 0
    except:
        market_change = 0

    try:
        hist = fdr.DataReader(code, start_date)
        if len(hist) < 25: return f"⚠️ {stock_name}({code}): 데이터 부족"
        
        curr = hist.iloc[-1]
        vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
        ma20 = hist['Close'].rolling(20).mean().iloc[-1]
        
        if pd.isna(vol_ma) or vol_ma <= 0 or pd.isna(ma20) or ma20 <= 0:
            return f"⚠️ {stock_name}({code}): 계산 불가"

        ma_gap = (curr['Close'] - ma20) / ma20 * 100
        vol_ratio = curr['Volume'] / vol_ma if vol_ma else 0
        upper_shadow = ((curr['High'] - max(curr['Open'], curr['Close'])) / curr['High'] * 100)
        candle_pos = ((curr['Close'] - curr['Low']) / (curr['High'] - curr['Low']) * 100) if (curr['High'] > curr['Low']) else 0
        
        p6 = hist['Close'].iloc[-6]
        five_change = (curr['Close'] / p6 - 1) * 100 if p6 > 0 else 0
        amount = curr['Close'] * curr['Volume']
        changes_ratio = (curr['Close'] / hist['Close'].iloc[-2] - 1) * 100
        
        rs = five_change - market_change
        
        # scoring.py 호출하여 V8.4.5 공식 점수 도출
        score = calculate_score(amount, vol_ratio, changes_ratio, upper_shadow, ma_gap, candle_pos, rs, five_change, 0)
        
        msg = f"🔎 [개별 종목 정밀 진단]\n"
        msg += f"🏢 종목: {stock_name} ({code})\n"
        msg += f"📊 V8.4.5 퀀트 점수: {score} / 100\n\n"
        msg += f"📌 상태 요약\n"
        msg += f" • 현재가: {int(curr['Close']):,}원 ({round(changes_ratio, 2)}%)\n"
        msg += f" • MA20 이격도: {round(ma_gap, 2)}% ({'🟢 안정' if ma_gap < 15 else '🚨 과열'})\n"
        msg += f" • 상대강도(RS): {round(rs, 2)}%\n\n"
        
        if score >= 85 and ma_gap < 15: msg += "👑 판정: S급 (물타기 / 신규진입 유효 구간)\n"
        elif score >= 75: msg += "✅ 판정: B급 (보유 관망)\n"
        else: msg += "⚠️ 판정: 기준 미달 (신규 진입 금지 / 반등 시 비중 축소 권장)\n"
        
        return msg
    except Exception as e:
        return f"⚠️ {stock_name} 분석 오류: {e}"
