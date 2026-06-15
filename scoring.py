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

# [추가] 3일 보유 수익률 가중치 로직 (기본값 0으로 스캐너 에러 원천 차단)
def holding_period_bonus(days_held=0):
    if 2 <= days_held <= 4:
        return 15  
    return 0

def calculate_score(amount, vr, c, s, g, cp, rs, sc, risk=0, days_held=0):
    score = (money_score(amount) + volume_score(vr) + momentum_score(c) + 
             shadow_score(s) + trend_score(g) + close_position_score(cp) + 
             rs_score(rs, sc) + holding_period_bonus(days_held))
    
    # [수정] 하락장 페널티 강화 (옵션 B 모드)
    if risk == 1: score -= 5
    elif risk == 2: score -= 20 
    
    return score

def grade(s):
    if s >= 95: return "A+"
    elif s >= 85: return "A"
    elif s >= 75: return "B"
    return "C"

# [V8.4.5 신규 방어 로직: 2회 연속 손절 시 익일 비중 50% 축소]
loss_count = 0 

def adjust_position(results, current_loss_flag):
    global loss_count
    if current_loss_flag:
        loss_count += 1
    else:
        loss_count = 0
    
    if loss_count >= 2:
        return "⚠️ 경고: 최근 2회 연속 손절로 인해 익일 진입 비중 50%로 자동 제한"
    return "✅ 정상 비중 진입"
