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

# [교정] Conviction 실질 최대치(38점) 기준 100점 만점 정규화 적용 (가중치 왜곡 해결)
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
    
    # 이론상 최대 누적점 38점 기반 정규화 수학식 이식
    normalized = int(max(score, 0) * 100 / 38)
    return min(normalized, 100)

# [교정] 형님의 전술 제안 반영: RS 비중 하향(40%), 수급지속성(30%), 방어력(20%), 장기생존(10%) 재분배
def get_prime_score(rs1, rs5, rs20, amount_strength, defense_passed):
    score = 0
    
    # 1. 상대강도 부문 (최대 40점 캡핑)
    score += min(math.log1p(max(rs1, 0)) * 6.5, 20)
    score += min(math.log1p(max(rs5, 0)) * 6.5, 20)
    
    # 2. 거래대금 지속성 부문 (최대 30점 캡핑) - 강도 2.0배 이상일 시 만점
    score += min(amount_strength * 15, 30)
    
    # 3. 보유자 가격 방어력 부문 (최대 20점)
    if defense_passed: score += 20
        
    # 4. 20일 시계열 생존 부문 (최대 10점)
    if rs20 >= 0: score += 10
    
    return min(int(score), 100)

def calculate_score(amount, vr, c, s_ratio, g, cp, rs, risk_level):
    raw = (money_score(amount) +
           volume_score(vr) +
           momentum_score(c) +
           shadow_score(s_ratio) +
           trend_score(g) +
           close_position_score(cp) +
           rs_score(rs))
    if risk_level == 1: raw -= 5
    elif risk_level == 2: raw -= 20
    return max(min(int(raw), 100), 0)
