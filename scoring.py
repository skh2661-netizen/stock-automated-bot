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
    if 7 <= c <= 12: return 15
    elif 3 <= c < 7: return 10
    elif 0 <= c < 3: return 5
    elif 12 < c <= 18: return 3
    return 0

def shadow_score(s_ratio):
    # [수정] 100점 만점을 맞추기 위해 10점으로 하향
    if s_ratio <= 0.3: return 10
    elif s_ratio <= 0.6: return 5
    return 0

def trend_score(g):
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
    # [수정] 100점 만점을 맞추기 위해 5점으로 하향 및 RS 기준 강화
    if rs >= 8: return 5
    elif rs >= 4: return 3
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
    
    # [수정] 억지 스케일링 제거. Raw 총합이 이미 100점이므로 상위권 점수 압축 소멸
    return max(min(int(raw), 100), 0)
