import FinanceDataReader as fdr
import pytz
from datetime import datetime, timedelta
from database import get_all_holdings

def evaluate_corporate(sector, theme):
    score = 60
    if "반도체" in sector or "반도체" in theme: score += 30
    elif "바이오" in sector: score += 15
    elif "AI" in theme: score += 15
    return min(score, 100)

def evaluate_chart(hist, buy_price):
    if len(hist) < 25: return 0, 0, False, 0, False
    curr_price = hist['Close'].iloc[-1]
    ma20 = hist['Close'].rolling(20).mean().iloc[-1]
    pnl_pct = round((curr_price - buy_price) / buy_price * 100, 2)
    score = 50 + (20 if curr_price >= ma20 else -20)
    if pnl_pct <= -20: score -= 20
    elif pnl_pct <= -10: score -= 10
    
    down_days = sum(1 for i in range(-5, 0) if hist['Close'].iloc[i] < hist['Close'].iloc[i-1])
    is_vol_risk = (hist['Volume'].tail(5).mean() * 1.5 < hist['Volume'].tail(1).iloc[0] and hist['Close'].tail(1).iloc[0] < hist['Close'].shift(1).tail(1).iloc[0])
    if is_vol_risk: score -= 10
    return max(min(int(score), 100), 0), pnl_pct, (curr_price < ma20), down_days, is_vol_risk

def evaluate_exit(corp_score, chart_score, down_days, is_vol_risk, pnl_pct, is_below_ma20):
    exit_score = 0
    if corp_score < 70: exit_score += 3
    if down_days >= 4 or is_vol_risk: exit_score += 2
    if pnl_pct <= -20 or (is_below_ma20 and pnl_pct <= -10): exit_score += 3
    elif is_below_ma20: exit_score += 2
    if corp_score >= 80 and exit_score >= 6: exit_score = 5 
    return min(exit_score, 10)

def run_holding_engine():
    holdings = get_all_holdings()
    results = []
    for h in holdings:
        code, name, buy_p, qty, weight, b_date, sector, theme = h
        hist = fdr.DataReader(code, (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d"))
        if hist.empty: continue
        corp = evaluate_corporate(sector, theme)
        chart, pnl, is_ma, days, vol_r = evaluate_chart(hist, buy_p)
        exit = evaluate_exit(corp, chart, 0, pnl, is_ma, days, vol_r)
        results.append({"name": name, "buy_p": buy_p, "curr_p": int(hist['Close'].iloc[-1]), "pnl": pnl, "total": int(corp*0.4 + chart*0.4 + 20), "exit_score": exit, "judgment": "🟢 보유" if exit < 6 else "🔴 축소"})
    return results
