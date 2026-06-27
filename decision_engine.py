import datetime
from database import save_candidate, save_candidate_history, get_signal_persistence, register_signal_outcome, get_signal_quality

def evaluate_candidates(scanner_output):
    market = scanner_output.get("market", {})
    raw_candidates = scanner_output.get("raw_data", [])
    risk_level = market.get("risk_level", 1)
    evaluated_results = []
    
    for raw in raw_candidates:
        feats, scores = raw["features"], raw["scores"]
        action, rank_bonus = "👀 관망", 0
        if risk_level == 3:
            if feats["rs_20d"] > 20 and feats["conviction"] >= 60: action, rank_bonus = "🔥 시장 생존 리더", 20
            elif feats["rs_20d"] > 20: action, rank_bonus = "🟡 방어 후보", 5
        elif not feats["is_overheated"] and feats["ma_gap"] < 15:
            if scores["prime_score"] >= 75: action, rank_bonus = "🔥 최우선 관찰", 20
            elif scores["score"] >= 55: action, rank_bonus = "🟢 진입 후보", 5
        
        evaluated_results.append({"code": raw["code"], "name": raw["name"], "price": raw["price"], "chg": raw["chg"], "features": feats, "scores": scores, "decision": {"action": action, "rank_score": scores["prime_final"] + rank_bonus}})
        
    evaluated_results.sort(key=lambda x: x["decision"]["rank_score"], reverse=True)
    for c in evaluated_results:
        mem, stats = get_signal_persistence(c["code"]), get_signal_quality(risk_level, c["features"]["rs_20d"], c["features"]["conviction"])
        mem_score = min((mem["five_days_days"] * 0.25) + ((stats.get("win_rate", 0)/100.0) * 0.65 * 100) + (min(stats.get("match_count", 0), 20) * 0.1), 25)
        c["decision"]["_leader_score"] = c['scores']['prime_final'] + mem_score
            
    prime_leader = max(evaluated_results, key=lambda x: x["decision"]["_leader_score"])
    prime_leader["decision"]["is_prime_leader"] = True
        
    for i in evaluated_results:
        hid = save_candidate_history(datetime.now().strftime("%Y-%m-%d %H:%M"), "OPEN_SCAN", i['code'], i['name'], 1, i['price'], i['chg'], 0, 0, 0, 0, 0, 0, 0, 0, 0, risk_level, (1 if i["decision"].get("is_prime_leader") else 0))
        if "리더" in i["decision"]["action"] or "최우선" in i["decision"]["action"]:
            register_signal_outcome(hid, i['code'], i['name'], i['price'], risk_level)
    return {"candidates": evaluated_results}
