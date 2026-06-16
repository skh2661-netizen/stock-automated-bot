def calculate_score(amount, vol_ratio, changes_ratio, upper_shadow, ma_gap, close_pos, rs, five_change, risk_level):
    score = 0
    # 형님의 원본 로직을 유지하면서, scanner.py의 9개 인자를 모두 처리하도록 구성
    if amount >= 1000_000_000_000: score += 30
    elif amount >= 100_000_000_000: score += 20
    else: score += 10
        
    if vol_ratio >= 3.0: score += 20
    elif vol_ratio >= 2.0: score += 15
    else: score += 10
        
    score += (changes_ratio * 1.5)
    
    # 전달받은 인자 중 0으로 들어오는 값들은 계산에 영향 없도록 처리
    return min(100, max(0, int(score)))
