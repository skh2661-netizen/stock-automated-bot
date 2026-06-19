def money_score(amount):
    if amount >= 100_000_000_000: return 25
    elif amount >= 50_000_000_000: return 20
    elif amount >= 30_000_000_000: return 15
    elif amount >= 10_000_000_000: return 10
    return 0

def volume_score(vr):
    if vr >= 3: return 20
    elif vr >= 2: return 15
    elif vr >= 1.5: return 10
    return 0

def momentum_score(c):
    # [수정] PRE_OPEN 갭 상승(0~3%) 종목도 점수를 받도록 구간 세분화
    if 7 <= c <= 12: return 15
    elif 3 <= c < 7: return 10
    elif 0 <= c < 3: return 5
    elif 12 < c <= 18: return 3
    return 0

def shadow_score(s_ratio):
    if s_ratio <= 0.3: return 15
    elif s_ratio <= 0.6: return 10
    return 0

def trend_score(g):
    # 과열 패널티 유지
    if 5 <= g <= 12: return 15
    elif 0 <= g < 5: return 10
    elif 12 < g <= 20: return 5
    elif g > 20: return -10
    return 0

def close_position_score(cp):
    if cp >= 80: return 10
    elif cp >= 50: return 5
    return 0

def rs_score(rs, sc=0):
    if rs >= 5: return 10
    elif rs >= 2: return 5
    return 0

def calculate_score(amount, vr, c, s_ratio, g, cp, rs, sc, risk_level):
    raw = (money_score(amount) +
           volume_score(vr) +
           momentum_score(c) +
           shadow_score(s_ratio) +
           trend_score(g) +
           close_position_score(cp) +
           rs_score(rs, sc))
    
    if risk_level == 1: raw -= 5
    elif risk_level == 2: raw -= 20
    
    # [수정] 실제 만점(110점) 기준으로 스케일링하여 점수 왜곡 방지
    normalized = int(raw * 100 / 110)
    return max(min(normalized, 100), 0)
