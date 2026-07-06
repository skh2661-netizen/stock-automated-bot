import math

def money_score(amount):
    if amount >= 100_000_000_000: return 25
    elif amount >= 50_000_000_000: return 20
    elif amount >= 30_000_000_000: return 15
    elif amount >= 10_000_000_000: return 10
    return 0

def volume_score(vr):
    if vr >= 3.0: return 20
    elif vr >= 2.0: return 15
    elif vr >= 1.5: return 10
    return 0

def momentum_score(c):
    if 7 <= c <= 12: return 15
    elif 3 <= c < 7: return 10
    elif 0 <= c < 3: return 5
    elif 12 < c <= 18: return 3
    return 0

def shadow_score(s_ratio):
    if s_ratio <= 0.3: return 10
    elif s_ratio <= 0.6: return 5
    return 0

def close_position_score(cp):
    if cp >= 80: return 10
    elif cp >= 50: return 5
    return 0

def rs_score(rs):
    if rs >= 10: return 10
    elif rs >= 5: return 5
    return 0

def get_conviction_score(rs, amount, vr, risk_level, ma_gap, cp):
    score = 0
    if risk_level >= 2 and rs >= 10: score += 5
    if rs >= 10: score += 10
    elif rs >= 7: score += 7
    elif rs >= 5: score += 5
    if amount >= 100_000_000_000: score += 10
    elif amount >= 50_000_000_000: score += 5
    if vr >= 5: score += 5
    if 3 <= ma_gap <= 12: score += 5
    if ma_gap >= 20: score -= 10
    if cp >= 80: score += 3
    
    normalized = int(max(score, 0) * 100 / 38)
    return min(normalized, 100)

# [수정] decision_engine과 정렬된 새로운 Prime Score (100점 만점)
def get_prime_score(rs20, conviction, amount, vr, ma_gap):
    score = 0
    
    # 1. RS20 (30%)
    if rs20 >= 20: score += 30
    elif rs20 >= 10: score += 20
    elif rs20 >= 5: score += 10
    elif rs20 >= 0: score += 5
    
    # 2. Conviction (25%)
    score += min(conviction * 0.25, 25)
    
    # 3. Amount (20%) - money_score(max 25) * 0.8 = 20
    score += min(money_score(amount) * 0.8, 20)
    
    # 4. VR (15%) - volume_score(max 20) * 0.75 = 15
    score += min(volume_score(vr) * 0.75, 15)
    
    # 5. MA Gap (10%) - 정배열 초입(밀집) 가점
    if 0 <= ma_gap <= 10: score += 10
    elif 10 < ma_gap <= 20: score += 5
    
    return min(max(int(score), 0), 100)

def calculate_preopen_score(amount, vr, c, s_ratio, cp, rs, risk_level):
    raw = (money_score(amount) * 1.5) + (rs_score(rs) * 1.5) + (momentum_score(c)) + close_position_score(cp)
    if risk_level == 1: raw -= 5
    elif risk_level == 2: raw -= 20
    return max(min(int(raw), 100), 0)

def calculate_breakout_score(amount, vr, c, rs, risk_level):
    vr_sc = min(vr * 10, 40)
    amt_sc = min(money_score(amount) * 1.2, 30)
    mom_sc = min(momentum_score(c) * 1.33, 20)
    rs_sc = min(rs_score(rs), 10)
    raw = vr_sc + amt_sc + mom_sc + rs_sc
    if risk_level == 1: raw -= 5
    elif risk_level == 2: raw -= 20
    return max(min(int(raw), 100), 0)

def calculate_close_score(amount, vr, c, s_ratio, g, cp, rs, risk_level, ma_gap):
    ma_sc = max(25 - max(ma_gap, 0), 0)
    stab_sc = min(shadow_score(s_ratio) * 2.5, 25)
    amt_sc = min(money_score(amount) * 0.8, 20)
    rs_sc = min(rs_score(rs) * 2, 20)
    cp_sc = min(close_position_score(cp), 10)
    raw = ma_sc + stab_sc + amt_sc + rs_sc + cp_sc
    if risk_level == 1: raw -= 5
    elif risk_level == 2: raw -= 20
    return max(min(int(raw), 100), 0)
