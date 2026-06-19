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
    return max(score, 0)

# [수정 1] Prime Rank 점수 체계 도입 (기준 완화 및 점수화)
def get_prime_score(rs1, rs5, rs20, amount_strength, defense_passed, vr):
    score = 0
    if rs1 >= 7: score += 20
    if rs5 >= 3: score += 20
    if rs20 >= 0: score += 15
    if amount_strength >= 1.2: score += 15
    if defense_passed: score += 15
    if vr >= 2: score += 15
    return score

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
    normalized = int(raw * 100 / 105)
    return max(min(normalized, 100), 0)
