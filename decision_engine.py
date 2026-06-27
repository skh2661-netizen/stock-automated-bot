import datetime
import pytz
from database import save_candidate, save_candidate_history, get_signal_persistence, get_top10_stability, register_signal_outcome, get_signal_quality

def calculate_trade_plan(price, ma20_price, ma_gap, score):
    buy_p = int(price * 0.92) if ma_gap > 20 else (int(price * 0.96) if ma_gap > 10 else int(price * 0.985))
    return {"buy_p": buy_p, "pullback_price": max(int(ma20_price), int(price * 0.95)), "target_1": int(price*1.05), "target_2": int(price*1.10), "stop_p": int(buy_p * 0.95)}

def evaluate_candidates(scanner_output):
    market = scanner_output.get("market", {})
    raw_candidates = scanner_output.get("raw_data", [])
    run_type = market.get("mode", "OPEN_SCAN")
    risk_level = market.get("risk_level", 1)
    scan_datetime = datetime.datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
    
    evaluated_results = []
    
    for raw in raw_candidates:
        feats, scores = raw["features"], raw["scores"]
        trade_plan = calculate_trade_plan(raw["price"], feats["ma20_price"], feats["ma_gap"], scores["score"])
        action, rank_bonus, reason = "👀 관망", 0, []
        
        if risk_level == 3:
            if feats["rs_20d"] > 20 and feats["conviction"] >= 60:
                action, rank_bonus = "🔥 폭락장 상대강도 리더", 20
                reason.append("폭락장 생존 및 수급 동반")
                trade_plan["buy_p"] = 0 
            elif feats["rs_20d"] > 20:
                action, rank_bonus = "🛡 생존 감시 대상", 5
                reason.append("상대강도 우위 (방어 후보)")
                trade_plan["buy_p"] = 0
        elif not feats["is_overheated"] and feats["ma_gap"] < 15:
            if scores["prime_score"] >= 75: action, rank_bonus = "🔥 최우선 관찰", 20
            elif scores["score"] >= 55: action, rank_bonus = "🟢 진입 후보", 5
        
        evaluated_results.append({
            "code": raw["code"], "name": raw["name"], "price": raw["price"], "chg": raw["chg"],
            "features": feats, "scores": scores, "trade_plan": trade_plan, 
            "pattern_stats": get_signal_quality(risk_level, feats["rs_20d"], feats["conviction"]),
            "decision": {"action": action, "reason": reason, "rank_score": scores["prime_final"] + rank_bonus, "is_prime_leader": False}
        })
        
    evaluated_results.sort(key=lambda x: x["decision"]["rank_score"], reverse=True)
    
    for c in evaluated_results:
        mem = get_signal_persistence(c["code"])
        top10 = get_top10_stability(c["code"])
        stats = c["pattern_stats"]
        feats = c["features"]
        
        # Memory Score
        win_rate = stats.get("win_rate", 0.0) / 100.0
        confidence = win_rate * min(stats.get("match_count", 0) / 20.0, 1.0)
        memory_score = min((mem["five_days_days"] * 0.25) + (confidence * 0.65 * 100) + (mem["leader_count"] * 0.10 * 100), 25)
        
        # [신규] 폭락장 특화 PRIME WATCH 선출 로직
        if risk_level == 3:
            c["decision"]["_leader_score"] = (feats["rs_20d"] * 1.5) + (feats["conviction"] * 0.5) + (c["scores"]["prime_final"] * 0.3) + memory_score
        else:
            c["decision"]["_leader_score"] = c["scores"]["prime_final"] + memory_score
            
        # [신규] 4단계 매수 준비도(Buy Readiness) 산출 엔진
        readiness = "👀 LEVEL 0: 관찰"
        if risk_level == 3:
            readiness = "❌ 신규 진입 금지 (시장 반등 확인 필수)"
        else:
            if stats.get("win_rate", 0) > 60 and stats.get("match_count", 0) >= 20 and feats["rs_20d"] > 25 and feats["conviction"] > 80 and risk_level == 1:
                readiness = "🔥 LEVEL 3: 적극 매수 후보"
            elif top10["top10_count"] >= 5 and feats["rs_20d"] > 20 and feats["conviction"] > 70 and risk_level <= 2:
                readiness = "🟢 LEVEL 2: 분할 매수 가능"
            elif top10["top10_count"] >= 3 and feats["rs_20d"] > 15 and feats["conviction"] > 60 and feats["ma_gap"] < 10:
                readiness = "🟡 LEVEL 1: 매수 준비"

        c["decision"]["buy_readiness"] = readiness
        c["decision"]["top10_stability"] = top10
            
    if evaluated_results:
        prime_leader = max(evaluated_results, key=lambda x: x["decision"]["_leader_score"])
        prime_leader["decision"]["is_prime_leader"] = True
        
    for rank_idx, i in enumerate(evaluated_results, 1):
        try:
            save_candidate(run_type, i['code'], i['name'], i['scores']['score'], i['trade_plan']['buy_p'], i['trade_plan']['target_1'], i['trade_plan']['target_2'], i['trade_plan']['stop_p'], i['price'], i['chg'], i['features']['ma_gap'], i['scores']['prime_score'], i['scores']['prime_final'], i['features']['conviction'], i['features']['amount_strength'], i['features']['rs_1d'], i['features']['rs_5d'], i['features']['rs_20d'], (1 if i["decision"].get("is_prime_leader") else 0), risk_level)
            
            actual_history_id = save_candidate_history(scan_datetime, run_type, i['code'], i['name'], rank_idx, i['price'], i['chg'], i['scores']['prime_final'], i['scores']['prime_score'], i['features']['conviction'], i['features']['rs_1d'], i['features']['rs_5d'], i['features']['rs_20d'], i['features']['ma_gap'], i['features']['amount'], i['features']['amount_strength'], risk_level, (1 if i["decision"].get("is_prime_leader") else 0))
            
            if "리더" in i["decision"]["action"] or "최우선" in i["decision"]["action"] or "진입" in i["decision"]["action"]:
                register_signal_outcome(actual_history_id, i['code'], i['name'], i['price'], risk_level)
                
        except Exception: pass
            
    return {"market": market, "stats": scanner_output.get("stats", {}), "candidates": evaluated_results}
