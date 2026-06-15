def money_score(amount):
    if amount >= 100_000_000_000: return 25
    elif amount >= 50_000_000_000: return 20
    elif amount >= 20_000_000_000: return 15
    elif amount >= 10_000_000_000: return 10
    return 0

def volume_score(vr):
    if vr >= 5: return 20
    elif vr >= 3: return 15
    elif vr >= 2: return 10
    elif vr >= 1.3: return 5
    return 0

def momentum_score(c):
    if 8 <= c <= 15: return 15
    elif 5 <= c < 8: return 12
    elif 3 <= c < 5: return 8
    elif c > 15: return 5
    return 0

def shadow_score(s):
    if s <= 1: return 15
    elif s <= 3: return 10
    elif s <= 5: return 5
    return -5

def trend_score(g):
    if g >= 10: return 15
    elif g >= 5: return 12
    elif g >= 0: return 8
    return 0

def close_position_score(p):
    if p >= 90: return 10
    elif p >= 70: return 7
    elif p >= 50: return 4
    return 0

def rs_score(rs, stock_change):
    if stock_change < 3: return 0
    if rs >= 10: return 10
    elif rs >= 5: return 5
    return 0

# [추가] 3일 보유 수익률 가중치 로직 (백테스트 결과 반영)
def holding_period_bonus(days_held):
    # 백테스트상 3일 보유 시 수익률 4.2%로 최적화됨
    if 2 <= days_held <= 4:
        return 15  # 최적 구간 가중치 부여
    return 0

def calculate_score(amount, vr, c, s, g, cp, rs, sc, risk=0, days_held=0):
    # 기본 점수 합산
    score = (money_score(amount) + volume_score(vr) + momentum_score(c) + 
             shadow_score(s) + trend_score(g) + close_position_score(cp) + 
             rs_score(rs, sc) + holding_period_bonus(days_held))
    
    # [안전장치] 하락장 시 리스크 페널티 강화
    if risk == 1: score -= 5
    elif risk == 2: score -= 20  # 강한 하락장 페널티 상향 조정
    
    return score

def grade(s):
    # [전략 수정] 하락장 방어 위해 A 등급 커트라인 85점으로 상향
    if s >= 95: return "A+"
    elif s >= 85: return "A"
    elif s >= 75: return "B"
    return "C"
