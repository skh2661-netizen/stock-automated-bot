import FinanceDataReader as fdr
import pandas as pd
import pytz
from datetime import datetime, timedelta
from database import get_all_holdings

def evaluate_corporate(sector, theme):
    score = 60
    if "반도체" in sector or "반도체" in theme:
        score += 20
        if "장비" in theme or "HBM" in theme: score += 10
    elif "바이오" in sector: score += 15
    elif "AI" in theme: score += 15
    return min(score, 100)

def evaluate_chart(hist, buy_price):
    if len(hist) < 25: return 0, 0, False, 0
    
    curr = hist.iloc[-1]
    curr_price = curr['Close']
    ma20 = hist['Close'].rolling(20).mean().iloc[-1]
    
    score = 50
    is_below_ma20 = curr_price < ma20
    if is_below_ma20: score -= 20
    else: score += 20
        
    pnl_pct = round((curr_price - buy_price) / buy_price * 100, 2)
    if pnl_pct <= -20: score -= 20
    elif pnl_pct <= -10: score -= 10
        
    down_days = sum(1 for i in range(-5, 0) if hist['Close'].iloc[i] < hist['Close'].iloc[i-1])
    if down_days >= 3: score -= 10
        
    return max(min(int(score), 100), 0), pnl_pct, is_below_ma20, down_days

def evaluate_market(kp_1d, kd_1d):
    score = 50
    if kp_1d > 0.5 and kd_1d > 0.5: score = 80
    elif kp_1d < -1.0 or kd_1d < -1.0: score = 30
    return score

def evaluate_exit(corp_score, chart_score, mkt_score, pnl_pct, is_below_ma20, down_days):
    exit_score = 0
    if corp_score < 60: exit_score += 3
    elif corp_score < 75: exit_score += 1
        
    if mkt_score < 40: exit_score += 2
    elif mkt_score < 60: exit_score += 1
        
    if down_days >= 4: exit_score += 2
    elif down_days >= 2: exit_score += 1
        
    if pnl_pct <= -20 or (is_below_ma20 and pnl_pct <= -10): exit_score += 3
    elif is_below_ma20: exit_score += 2
    
    # [V8.7 자체 방어] 우량주 골파기 방어 (Grace Period 적용)
    if corp_score >= 80 and exit_score >= 6:
        exit_score = 5 
        
    return min(exit_score, 10)

def run_holding_engine(kp_1d, kd_1d):
    holdings = get_all_holdings()
    if not holdings: return []
    
    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.now(kst) - timedelta(days=60)).strftime("%Y-%m-%d")
    results = []
    
    for h in holdings:
        code, name, buy_p, qty, weight, b_date, sector, theme = h
        hist = fdr.DataReader(code, start_date)
        if hist.empty: continue
        
        curr_p = int(hist['Close'].iloc[-1])
        corp_score = evaluate_corporate(sector, theme)
        chart_score, pnl_pct, is_below_ma20, down_days = evaluate_chart(hist, buy_p)
        mkt_score = evaluate_market(kp_1d, kd_1d)
        
        total_score = int((corp_score * 0.3) + (chart_score * 0.5) + (mkt_score * 0.2))
        exit_score = evaluate_exit(corp_score, chart_score, mkt_score, pnl_pct, is_below_ma20, down_days)
        
        if exit_score >= 6: judgment = "🔴 비중 축소 요망"
        elif total_score >= 60: judgment = "🟢 홀딩 가능"
        else: judgment = "🟡 관망 (추매 금지)"
            
        results.append({
            "name": name, "buy_p": buy_p, "curr_p": curr_p, "pnl": pnl_pct,
            "total": total_score, "exit_score": exit_score, "judgment": judgment
        })
    return results
