from datetime import datetime
import pytz
from database import save_candidate_history, get_signal_persistence, register_signal_outcome, get_signal_quality, get_top10_stability, save_top10_tracking

def detect_market_regime(kospi, kosdaq):
    if kospi >= 1.0 or kosdaq >= 2.0: return "BULL", 0, "🟢 위험선호 증가 (강세장)"
    elif kospi <= -3.0: return "CRASH", 3, "🔴 위험회피 (폭락장)"
    elif kospi <= -1.0: return "WARNING", 2, "🟡 보수적 관망 (조정장)"
    elif abs(kospi) < 1.0 and kosdaq >= 1.0: return "ROTATION", 1, "🔵 섹터 순환매 (차별화)"
    else: return "SIDEWAYS", 1, "⚪ 박스권 횡보 (방향성 탐색)"

def calculate_buy_readiness(c, regime_str, top10, stats):
    rs = c["features"]["rs_20d"]
    conv = c["features"]["conviction"]
    prime = c["scores"]["prime_score"]
    t10_count = top10["top10_count"]
    win_rate = stats.get("win_rate", 0)
    samples = stats.get("match_count", 0)
    
    if regime_str == "CRASH":
        return "❌ LEVEL 0: 신규진입 금지 (시장 반등 대기)"
        
    if regime_str == "WARNING":
        if rs > 20 and conv > 70 and t10_count >= 2:
            return "🟡 LEVEL 1: 생존 리더 관심 유지"
        return "👀 LEVEL 0: 관망 (조건 부족)"
        
    if regime_str in ["BULL", "ROTATION", "SIDEWAYS"]:
        if rs > 25 and conv > 70 and t10_count >= 3 and win_rate > 60 and samples >= 20:
            return "🚀 LEVEL 4: 적극 매수 구간 (조건 완전 충족)"
        elif rs > 15 and conv > 60 and t10_count >= 2:
            return "🟢 LEVEL 3: 분할 매수 가능"
        elif rs > 10 and conv > 50:
            return "🟡 LEVEL 2: 반등 준비 후보"
        else:
            return "👀 LEVEL 1: 관찰"
            
    return "👀 LEVEL 0: 조건 미달"

def evaluate_candidates(scanner_output):
    market = scanner_output.get("market", {})
    raw_candidates = scanner_output.get("raw_data", [])
    run_type = market.get("mode", "OPEN_SCAN")
    kospi_1d = market.get("kospi", 0.0)
    kosdaq_1d = market.get("kosdaq", 0.0)
    
    regime_str, risk_level, market_direction = detect_market_regime(kospi_1d, kosdaq_1d)
    scan_datetime = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
    
    evaluated_results = []
    
    for raw in raw_candidates:
        feats = raw["features"]
        scores = raw["scores"]
        
        # FINAL FILTER: 쓰레기 데이터 원천 차단
        if scores["prime_score"] < 50 or feats["conviction"] < 40: continue
        if risk_level < 3 and feats["rs_20d"] < -5: continue
        
        action, rank_bonus = "👀 관망", 0
        
        if regime_str == "CRASH":
            if feats["rs_20d"] > 15 and feats["conviction"] >= 60: action, rank_bonus = "🔥 폭락장 상대강도 리더", 20
            elif feats["rs_20d"] > 10: action, rank_bonus = "🛡 생존 감시 대상", 5
        elif regime_str == "BULL":
            if scores["prime_score"] >= 80 and feats["rs_20d"] > 10: action, rank_bonus = "🔥 상승 추세 리더", 25
            elif scores["score"] >= 60: action, rank_bonus = "🟢 적극 진입 후보", 10
        elif regime_str == "ROTATION":
            if feats["rs_20d"] > 5 and feats["conviction"] >= 60: action, rank_bonus = "🟡 순환매 주도주", 15
            else: action, rank_bonus = "👀 순환매 관심주", 5
        else:
            if scores["prime_score"] >= 75 and feats["ma_gap"] < 15: action, rank_bonus = "🔥 최우선 관찰", 20
            elif scores["score"] >= 55: action, rank_bonus = "🟢 진입 후보", 5
            
        pattern_stats = get_signal_quality(regime_str, feats["rs_20d"], feats["conviction"])
        evaluated_results.append({
            "code": str(raw["code"]).zfill(6), "name": raw["name"], "price": raw["price"], "chg": raw["chg"],
            "features": feats, "scores": scores, "pattern_stats": pattern_stats,
            "decision": {"action": action, "rank_score": scores["prime_final"] + rank_bonus, "is_prime_leader": False}
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
        
        # 국면별 PRIME WATCH 산출 가중치 분리
        if regime_str == "CRASH":
            c["decision"]["_leader_score"] = (feats["rs_20d"] * 1.5) + (feats["conviction"] * 0.5) + (c["scores"]["prime_final"] * 0.3) + memory_score
        elif regime_str == "BULL":
            c["decision"]["_leader_score"] = (c["scores"]["prime_final"] * 0.8) + (feats["rs_20d"] * 0.7) + memory_score
        else:
            c["decision"]["_leader_score"] = c["scores"]["prime_final"] + memory_score
            
        c["decision"]["buy_readiness"] = calculate_buy_readiness(c, regime_str, top10, stats)
        c["decision"]["top10_stability"] = {
            "top10_count": mem["today_count"],
            "recent_days": mem["five_days_days"],
            "avg_rank": mem["avg_rank"]
        }
            
    if evaluated_results:
        prime_leader = max(evaluated_results, key=lambda x: x["decision"]["_leader_score"])
        prime_leader["decision"]["is_prime_leader"] = True
        
    for rank_idx, i in enumerate(evaluated_results, 1):
        try:
            if rank_idx <= 10: save_top10_tracking(scan_datetime, i['code'], i['name'], rank_idx, i['scores']['prime_final'], risk_level)
            actual_history_id = save_candidate_history(scan_datetime, run_type, i['code'], i['name'], rank_idx, i['price'], i['chg'], i['scores']['prime_final'], i['scores']['prime_score'], i['features']['conviction'], i['features']['rs_1d'], i['features']['rs_5d'], i['features']['rs_20d'], i['features']['ma_gap'], i['features']['amount'], i['features']['amount_strength'], risk_level, (1 if i["decision"].get("is_prime_leader") else 0))
            
            action_type = i["decision"]["action"]
            if "리더" in action_type or "최우선" in action_type or "진입" in action_type or "주도" in action_type:
                register_signal_outcome(actual_history_id, i['code'], i['name'], i['price'], regime_str)
        except Exception: pass
            
    market["regime"] = regime_str
    market["direction"] = market_direction
    return {"market": market, "stats": scanner_output.get("stats", {}), "candidates": evaluated_results}
