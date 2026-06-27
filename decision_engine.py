import datetime
import pytz
from database import save_candidate, save_candidate_history, get_signal_persistence, register_signal_outcome, get_signal_quality

def calculate_trade_plan(price, ma20_price, ma_gap, score):
    if ma_gap > 20: buy_p = int(price * 0.92)
    elif ma_gap > 10: buy_p = int(price * 0.96)
    else: buy_p = int(price * 0.985)

    pullback_price = max(int(ma20_price), int(price * 0.95))

    if score >= 80 and ma_gap <= 10: target1, target2 = price * 1.10, price * 1.18
    elif ma_gap <= 5: target1, target2 = price * 1.08, price * 1.15
    elif ma_gap <= 15: target1, target2 = price * 1.05, price * 1.10
    else: target1, target2 = price * 1.03, price * 1.06
    
    stop_p = int(buy_p * 0.95)
    return {"buy_p": buy_p, "pullback_price": pullback_price, "target_1": int(target1), "target_2": int(target2), "stop_p": stop_p}

def evaluate_candidates(scanner_output):
    market = scanner_output.get("market", {})
    raw_candidates = scanner_output.get("raw_data", [])
    run_type = market.get("mode", "OPEN_SCAN")
    risk_level = market.get("risk_level", 1)
    
    kst = pytz.timezone("Asia/Seoul")
    scan_datetime = datetime.datetime.now(kst).strftime("%Y-%m-%d %H:%M")
    
    evaluated_results = []
    
    for raw in raw_candidates:
        feats = raw["features"]
        scores = raw["scores"]
        
        trade_plan = calculate_trade_plan(raw["price"], feats["ma20_price"], feats["ma_gap"], scores["score"])
        
        action = "👀 관망"
        reason = []
        rank_bonus = 0
        
        # 폭락장 셧다운 및 생존 리더 판단 로직
        if risk_level == 3:
            if feats["rs_20d"] > 20 and feats["conviction"] >= 60:
                action = "🔥 폭락장 상대강도 리더"
                reason.append("폭락장 생존 및 강력한 수급 동반 (신규 진입 금지)")
                rank_bonus += 20
                trade_plan["buy_p"] = 0
            elif feats["rs_20d"] > 20:
                action = "🛡 생존 감시 대상"
                reason.append("상대강도 우위 (방어 후보)")
                rank_bonus += 5
                trade_plan["buy_p"] = 0
        elif not feats["is_overheated"] and feats["ma_gap"] < 15:
            if scores["prime_score"] >= 75:
                action = "🔥 최우선 관찰"
                reason.append("시장 대비 강한 수급")
                rank_bonus += 20
            elif scores["score"] >= 55:
                action = "🟢 진입 후보"
                reason.append("진입 조건 충족")
                rank_bonus += 5
        
        pattern_stats = get_signal_quality(risk_level, feats["rs_20d"], feats["conviction"])
        
        evaluated_results.append({
            "code": raw["code"], "name": raw["name"], "price": raw["price"], "chg": raw["chg"],
            "features": feats, "scores": scores, "trade_plan": trade_plan, "pattern_stats": pattern_stats,
            "decision": {"action": action, "reason": reason, "rank_score": scores["prime_final"] + rank_bonus, "is_prime_leader": False}
        })
        
    evaluated_results.sort(key=lambda x: x["decision"]["rank_score"], reverse=True)
    
    if evaluated_results:
        for c in evaluated_results:
            mem = get_signal_persistence(c["code"])
            stats = c["pattern_stats"]
            
            win_rate = stats.get("win_rate", 0.0) / 100.0
            confidence = win_rate * min(stats.get("match_count", 0) / 20.0, 1.0)
            
            persistence = mem["five_days_days"] * 0.25
            quality = confidence * 0.65
            leader_bonus = mem["leader_count"] * 0.10
            
            memory_score = min(persistence + quality + leader_bonus, 25)
            c["decision"]["_leader_score"] = c['scores']['prime_final'] + memory_score
            
        prime_leader = max(evaluated_results, key=lambda x: x["decision"]["_leader_score"])
        prime_leader["decision"]["is_prime_leader"] = True
        
    # [수정 5] 루프 인덱스(rank_idx) 복구하여 실제 랭킹 저장 무결성 확보
    for rank_idx, i in enumerate(evaluated_results, 1):
        try:
            save_candidate(run_type, i['code'], i['name'], i['scores']['score'], i['trade_plan']['buy_p'], i['trade_plan']['target_1'], i['trade_plan']['target_2'], i['trade_plan']['stop_p'], i['price'], i['chg'], i['features']['ma_gap'], i['scores']['prime_score'], i['scores']['prime_final'], i['features']['conviction'], i['features']['amount_strength'], i['features']['rs_1d'], i['features']['rs_5d'], i['features']['rs_20d'], (1 if i["decision"].get("is_prime_leader") else 0), risk_level)
            
            actual_history_id = save_candidate_history(
                scan_datetime=scan_datetime, run_type=run_type, code=i['code'], name=i['name'], rank_position=rank_idx,
                price=i['price'], chg=i['chg'], prime_final=i['scores']['prime_final'], prime_score=i['scores']['prime_score'],
                conviction=i['features']['conviction'], rs_1d=i['features']['rs_1d'], rs_5d=i['features']['rs_5d'], rs_20d=i['features']['rs_20d'],
                ma_gap=i['features']['ma_gap'], amount=i['features']['amount'], amount_strength=i['features']['amount_strength'],
                risk_level=risk_level, is_leader=(1 if i["decision"].get("is_prime_leader") else 0)
            )
            
            action_type = i["decision"]["action"]
            if "리더" in action_type or "최우선" in action_type or "진입" in action_type or "감시" in action_type:
                register_signal_outcome(actual_history_id, i['code'], i['name'], i['price'], risk_level)
                
        except Exception:
            import traceback
            traceback.print_exc()
            
    # [수정 4] 텔레그램 모듈이 요구하는 원본 Return Dictionary 구조 복구
    return {
        "market": market,
        "stats": scanner_output.get("stats", {}),
        "candidates": evaluated_results
    }
