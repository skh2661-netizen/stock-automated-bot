import math

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

def get_prime_score(rs1, rs5, rs20, amount_strength, defense_passed, ma_gap=0):
    score = 0
    score += min(math.log1p(max(rs1, 0)) * 6.5, 20)
    score += min(math.log1p(max(rs5, 0)) * 6.5, 20)
    score += min(amount_strength * 15, 30)
    
    if defense_passed: score += 20
    if rs20 >= 0: score += 10
    
    # [V8.4.27] Prime Overheating Penalty 완화 (강세장 공격 후보 보존)
    if ma_gap > 40: score -= 20
    elif ma_gap > 30: score -= 10
    elif ma_gap > 20: score -= 5
        
    return min(max(int(score), 0), 100)

# [V8.4.27] 1. 돌파용 스코어 엔진 (거래량 40, 대금 30, 탄력 20, RS 10)
def calculate_breakout_score(amount, vr, c, rs, risk_level):
    vr_sc = min(vr * 10, 40)
    amt_sc = min(money_score(amount) * 1.2, 30)
    mom_sc = min(momentum_score(c) * 1.33, 20)
    rs_sc = min(rs_score(rs), 10)
    raw = vr_sc + amt_sc + mom_sc + rs_sc
    if risk_level == 1: raw -= 5
    elif risk_level == 2: raw -= 20
    return max(min(int(raw), 100), 0)

# [V8.4.27] 2. 종가베팅용 스코어 엔진 (MA위치 25, 안정성 25, 대금 20, RS 20, 캔들 10)
def calculate_close_score(amount, vr, c, s_ratio, g, cp, rs, risk_level, ma_gap):
    ma_sc = max(25 - max(ma_gap, 0), 0)
    stab_sc = min(shadow_score(s_ratio) * 2.5, 25)
    amt_sc = min(money_score(amount) * 0.8, 20)
    rs_sc = min(rs_score(rs) * 2, 20)
    cp_sc = min(close_position_score(cp), 10)
    raw = ma_sc + stab_sc + amt_sc + rs_sc + cp_sc
    
    # [V8.4.27] CLOSE_BET 전용 25~35 구간 패널티
    if ma_gap > 25: raw -= 10
        
    if risk_level == 1: raw -= 5
    elif risk_level == 2: raw -= 20
    return max(min(int(raw), 100), 0)

# [V8.4.27] 3. 장전용 스코어 엔진
def calculate_open_score(amount, vr, c, s_ratio, cp, rs, risk_level):
    raw = (money_score(amount) * 1.5) + (rs_score(rs) * 1.5) + (momentum_score(c)) + close_position_score(cp)
    if risk_level == 1: raw -= 5
    elif risk_level == 2: raw -= 20
    return max(min(int(raw), 100), 0)
