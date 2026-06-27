from datetime import datetime
import pytz
from database import save_candidate_history, get_signal_persistence, register_signal_outcome, get_signal_quality, get_top10_stability, save_top10_tracking

def calculate_trade_plan(price, ma20_price, ma_gap, score):
    buy_p = int(price * 0.92) if ma_gap > 20 else (int(price * 0.96) if ma_gap > 10 else int(price * 0.985))
    return {"buy_p": buy_p, "pullback_price": max(int(ma20_price), int(price * 0.95)), "target_1": int(price*1.05), "target_2": int(price*1.10), "stop_p": int(buy_p * 0.95)}

def evaluate_candidates(scanner_output):
    market = scanner_output.get("market", {})
    raw_candidates = scanner_output.get("raw_data", [])
    run_type = market.get("mode", "OPEN_SCAN")
    risk_level = market.get("risk_level", 1)
    
    # [수정] 모듈 참조 오류 해결 (정상적인 시간 객체 생성)
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
            if rank_idx <= 10:
