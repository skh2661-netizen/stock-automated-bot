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

# [교정] 수급확신도(Conviction)의 입력 변수 임계치 구간 세분화 및 현실화
def get_conviction_score(rs, amount, vr, risk_level, ma_gap, cp):
    score = 0
    
    # 1. 당일 지수 대비 상대강도 (최대 15점)
    if risk_level >= 2 and rs >= 10: score += 5
    if rs >= 10: score += 10
    elif rs >= 7: score += 7
    elif rs >= 5: score += 5
    elif rs >= 2: score += 2  # 미세 주도 세션 보정
    
    # 2. 당일 거래대금 체급 (최대 10점)
    if amount >= 100_000_000_000: score += 10
    elif amount >= 50_000_000_000: score += 7
    elif amount >= 15_000_000_000: score += 4  # 최소 금액 충족선 가점
    
    # 3. 거래량 폭발 강도 (VR 구간화 - 최대 5점)
    if vr >= 4.0: score += 5
    elif vr >= 2.5: score += 4
    elif vr >= 1.5: score += 3  # 평소 대비 1.5배 이상 유의미한 거래 증가 포용
    elif vr >= 1.0: score += 1
    
    # 4. 이격 안정성 및 매수 영역 정렬 (최대 5점)
    if 0 <= ma_gap <= 12: score += 5
    elif 12 < ma_gap <= 18: score += 2
    elif ma_gap >= 25: score -= 10  # 과열권 패널티 유지
    
    # 5. 종가 마감 위치 우위성 (CP 구간화 - 최대 3점)
    if cp >= 75: score += 3
    elif cp >= 55: score += 2  # 박스권 중간값 상단 안착 인정
    elif cp >= 40: score += 1
    
    # 정규화 연산 (분모 38점 기준 백분율 정렬 유지)
    normalized = int(max(score, 0) * 100 / 38)
    return min(normalized, 100)

def get_prime_score(rs1, rs5, rs20, amount_strength, defense_passed):
    score = 0
    if rs1 > 0: score += min(rs1 * 3, 20)
    if rs5 > 0: score += min(rs5 * 2, 15)
    
    if rs20 >= 20: score += 30
    elif rs20 >= 10: score += 20
    elif rs20 >= 5: score += 10
    elif rs20 >= 0: score += 5
    
    score += min(amount_strength * 20, 25)
    if defense_passed: score += 10
    
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
