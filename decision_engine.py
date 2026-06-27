import datetime
import pytz
from database import save_candidate_history, get_signal_persistence, register_signal_outcome, get_signal_quality, get_top10_stability, save_top10_tracking

def evaluate_candidates(scanner_output):
    market = scanner_output.get("market", {})
    raw_candidates = scanner_output.get("raw_data", [])
    run_type = market.get("mode", "OPEN_SCAN")
    risk_level = market.get("risk_level", 1)
    scan_datetime = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
    
    evaluated_results = []
    
    for raw in raw_candidates:
        feats = raw["features"]
        scores = raw["scores"]
        action, rank_bonus, reason = "👀 관망", 0, []
        
        if risk_level == 3:
            if feats["rs_20d"] > 20 and feats["conviction"] >= 60:
                action, rank_bonus = "🔥 폭락장 상대강도 리더", 20
                reason.append("폭락장 생존 및 강력한 수급 동반")
            elif feats["rs_20d"] > 20:
                action, rank_bonus = "🛡 생존 감시 대상", 5
                reason.append("상대강도 우위 (방어 후보)")
        elif not feats["is_overheated"] and feats["ma_gap"] < 15:
            if scores["prime_score"] >= 75:
                action, rank_bonus = "🔥 최우선 관찰", 20
                reason.append("시장 대비 강한 수급")
            elif scores["score"] >= 55:
                action, rank_bonus = "🟢 진입 후보", 5
                reason.append("진입 조건 충족")
        
        pattern_stats = get_signal_quality(risk_level, feats["rs_20d"], feats["conviction"])
        evaluated_results.append({
            "code": raw["code"], "name": raw["name"], "price": raw["price"], "chg": raw["chg"],
            "features": feats, "scores": scores, "pattern_stats": pattern_stats,
            "decision": {"action": action, "reason": reason, "rank_score": scores["prime_final"] + rank_bonus, "is_prime_leader": False}
        })
        
    evaluated_results.sort(key=lambda x: x["decision"]["rank_score"], reverse=True)
    
    for c in evaluated_results:
        mem = get_signal_persistence(c["code"])
        top10 = get_top10_stability(c["code"])
        stats = c["pattern_stats"]
        feats = c["features"]
        
        win_rate = stats.get("win_rate", 0.0) / 100.0
        confidence = win_rate * min(stats.get("match_count", 0) / 20.0, 1.0)
        memory_score = min((mem["five_days_days"] * 0.25) + (confidence * 0.65 * 100) + (mem["leader_count"] * 0.10 * 100), 25)
        
        if risk_level == 3:
            c["decision"]["_leader_score"] = (feats["rs_20d"] * 1.5) + (feats["conviction"] * 0.5) + (c["scores"]["prime_final"] * 0.3) + memory_score
        else:
            c["decision"]["_leader_score"] = c["scores"]["prime_final"] + memory_score
            
        # [신규] 4단계 BUY READINESS ENGINE
        readiness = "👀 LEVEL 0: 관찰 (조건 부족)"
        if risk_level == 3:
            readiness = "❌ 신규 진입 금지 (시장 반등 확인 필수)"
        else:
            if stats.get("win_rate", 0) >= 65 and stats.get("match_count", 0) >= 20 and feats["rs_20d"] > 25 and feats["conviction"] > 80 and risk_level == 1 and top10["top10_count"] >= 5:
                readiness = "🔥 LEVEL 3: 실전 매수 가능"
            elif top10["top10_count"] >= 5 and feats["rs_20d"] > 20 and feats["conviction"] > 70 and risk_level <= 2 and feats["ma_gap"] <= 10:
                readiness = "🟢 LEVEL 2: 분할 매수 준비"
            elif top10["top10_count"] >= 3 and feats["rs_20d"] > 15 and feats["conviction"] > 60:
                readiness = "🟡 LEVEL 1: 관심 단계"

        c["decision"]["buy_readiness"] = readiness
        c["decision"]["top10_stability"] = top10
            
    if evaluated_results:
        prime_leader = max(evaluated_results, key=lambda x: x["decision"]["_leader_score"])
        prime_leader["decision"]["is_prime_leader"] = True
        
    for rank_idx, i in enumerate(evaluated_results, 1):
        try:
            # TOP10 기록 저장
            if rank_idx <= 10:
                save_top10_tracking(scan_datetime, i['code'], i['name'], rank_idx, i['scores']['prime_final'], risk_level)
                
            actual_history_id = save_candidate_history(scan_datetime, run_type, i['code'], i['name'], rank_idx, i['price'], i['chg'], i['scores']['prime_final'], i['scores']['prime_score'], i['features']['conviction'], i['features']['rs_1d'], i['features']['rs_5d'], i['features']['rs_20d'], i['features']['ma_gap'], i['features']['amount'], i['features']['amount_strength'], risk_level, (1 if i["decision"].get("is_prime_leader") else 0))
            
            action_type = i["decision"]["action"]
            if "리더" in action_type or "최우선" in action_type or "진입" in action_type:
                register_signal_outcome(actual_history_id, i['code'], i['name'], i['price'], risk_level)
                
        except Exception: pass
            
    return {"market": market, "stats": scanner_output.get("stats", {}), "candidates": evaluated_results}
