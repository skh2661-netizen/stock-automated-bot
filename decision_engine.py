def calculate_trade_plan(price, ma20_price, ma_gap, score):
    """
    타점 및 손절 전략 연산 (Scanner에서 이관됨)
    """
    if ma_gap > 20: buy_p = int(price * 0.92)
    elif ma_gap > 10: buy_p = int(price * 0.96)
    else: buy_p = int(price * 0.985)

    pullback_price = max(int(ma20_price), int(price * 0.95))

    if score >= 80 and ma_gap <= 10: target1, target2 = price * 1.10, price * 1.18
    elif ma_gap <= 5: target1, target2 = price * 1.08, price * 1.15
    elif ma_gap <= 15: target1, target2 = price * 1.05, price * 1.10
    else: target1, target2 = price * 1.03, price * 1.06
    
    stop_p = int(buy_p * 0.95)
    
    return {
        "buy_p": buy_p,
        "pullback_price": pullback_price,
        "target_1": int(target1),
        "target_2": int(target2),
        "stop_p": stop_p
    }

def evaluate_candidates(scanner_output):
    """
    Scanner가 생성한 팩트(Raw Data)를 바탕으로 매매 액션과 랭킹을 최종 판단
    """
    market = scanner_output.get("market", {})
    raw_candidates = scanner_output.get("raw_data", [])
    risk_level = market.get("risk_level", 1)
    
    evaluated_results = []
    
    for raw in raw_candidates:
        feats = raw["features"]
        scores = raw["scores"]
        
        # 1. 가격 전략 수립
        trade_plan = calculate_trade_plan(
            raw["price"], 
            feats["ma20_price"], 
            feats["ma_gap"], 
            scores["score"]
        )
        
        # 2. 상태(Reason) 및 액션(Action) 판단
        action = "OBSERVE"
        reason = []
        rank_bonus = 0
        
        if feats["is_overheated"]:
            action = "WAIT_PULLBACK"
            reason.append("가격 확장 상태 (신규 진입 효율 감소)")
            rank_bonus -= 10
        elif feats["ma_gap"] > 15:
            action = "WAIT_PULLBACK"
            reason.append("20일선 상방 이격 부담")
        elif feats["ma_gap"] < -10:
            action = "RECOVERY"
            reason.append("20일선 하방 이격 (낙폭 과대)")
        elif risk_level == 3 and feats["rs_20d"] > 20:
            action = "STRONG_SELECTION"
            reason.append("시장 급락 속 주도력 유지")
            rank_bonus += 20
        elif scores["prime_score"] >= 75 and -10 <= feats["ma_gap"] <= 15:
            action = "STRONG_SELECTION"
            reason.append("시장 대비 강한 수급 (분할 접근)")
            rank_bonus += 20
        elif scores["score"] >= 55 and -10 <= feats["ma_gap"] <= 15:
            action = "ENTRY_CANDIDATE"
            reason.append("진입 조건 충족")
            rank_bonus += 5
        else:
            reason.append("수급 및 위치 확인 단계")
            
        if feats["conviction"] < 40:
            reason.append("단기 확신 형성 중")
            
        # 3. Decision 랭킹 스코어 계산
        rank_score = scores["prime_final"] + rank_bonus
        
        evaluated_results.append({
            "code": raw["code"],
            "name": raw["name"],
            "price": raw["price"],
            "chg": raw["chg"],
            "features": feats,
            "scores": scores,
            "trade_plan": trade_plan,
            "decision": {
                "action": action,
                "reason": reason,
                "rank_score": rank_score,
                "is_prime_leader": False
            }
        })
        
    # 4. 판단 랭킹 기준 내림차순 정렬 및 Prime Leader 선출
    evaluated_results.sort(key=lambda x: x["decision"]["rank_score"], reverse=True)
    
    if evaluated_results:
        evaluated_results[0]["decision"]["is_prime_leader"] = True
        
    return {
        "market": market,
        "stats": scanner_output.get("stats", {}),
        "candidates": evaluated_results
    }
