from datetime import datetime
import pytz
from database import save_candidate_history, get_signal_persistence, register_signal_outcome, get_signal_quality, get_top10_stability, save_top10_tracking

def detect_market_regime(kospi_change):
    if kospi_change >= 1.5: return "BULL", 0
    elif abs(kospi_change) < 1.0: return "SIDEWAYS", 1
    elif kospi_change <= -5.0: return "CRASH", 3
    elif kospi_change <= -2.0: return "WARNING", 2
    else: return "NORMAL", 1

def calculate_trade_plan(price, ma20_price, ma_gap, score):
    buy_p = int(price * 0.92) if ma_gap > 20 else (int(price * 0.96) if ma_gap > 10 else int(price * 0.985))
    return {"buy_p": buy_p, "pullback_price": max(int(ma20_price), int(price * 0.95)), "target_1": int(price*1.05), "target_2": int(price*1.10), "stop_p": int(buy_p * 0.95)}

def evaluate_candidates(scanner_output):
    market = scanner_output.get("market", {})
    raw_candidates = scanner_output.get("raw_data", [])
    run_type = market.get("mode", "OPEN_SCAN")
    kospi_1d = market.get("kospi", 0.0)
    
    # [신규] 5국면 시장 판단기 가동
    regime_str, risk_level = detect_market_regime(kospi_1d)
    scan_datetime = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
    evaluated_results = []
    
    for raw in raw_candidates:
        feats = raw["features"]
        scores = raw["scores"]
        action, rank_bonus = "👀 관망", 0
        
        # 국면별 타겟팅 로직 분기
        if regime_str == "CRASH":
            if feats["rs_20d"] > 20 and feats["conviction"] >= 60: action, rank_bonus = "🔥 폭락장 상대강도 리더", 20
            elif feats["rs_20d"] > 20: action, rank_bonus = "🛡 생존 감시 대상", 5
        elif regime_str == "BULL":
            if scores["prime_score"] >= 80 and feats["rs_20d"] > 10: action, rank_bonus = "🔥 상승 추세 리더", 25
            elif scores["score"] >= 60: action, rank_bonus = "🟢 적극 진입 후보", 10
        elif regime_str == "SIDEWAYS":
            if feats["rs_1d"] > 5 and feats["conviction"] > 50: action, rank_bonus = "🟡 순환매 주도주", 15
        else: # NORMAL / WARNING
            if scores["prime_score"] >= 75 and feats["ma_gap"] < 15: action, rank_bonus = "🔥 최우선 관찰", 20
            elif scores["score"] >= 55: action, rank_bonus = "🟢 진입 후보", 5
        
        pattern_stats = get_signal_quality(regime_str, feats["rs_20d"], feats["conviction"])
        evaluated_results.append({
            "code": raw["code"], "name": raw["name"], "price": raw["price"], "chg": raw["chg"],
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
        
        # [교정] 국면별 PRIME WATCH 공식 차등 적용
        if regime_str == "CRASH":
            c["decision"]["_leader_score"] = (feats["rs_20d"] * 1.5) + (feats["conviction"] * 0.5) + (c["scores"]["prime_final"] * 0.3) + memory_score
        else:
            c["decision"]["_leader_score"] = c["scores"]["prime_final"] + memory_score
            
        # [신규] 5단계 매수 준비도 (LEVEL 0 ~ LEVEL 4)
        readiness = "👀 LEVEL 0: 관찰 (조건 부족)"
        if regime_str == "CRASH":
            readiness = "❌ 신규 진입 금지 (시장 반등 확인 필수)"
        else:
            if stats.get("win_rate", 0) >= 70 and stats.get("match_count", 0) >= 20 and regime_str in ["BULL", "NORMAL"]:
                readiness = "🚀 LEVEL 4: 강한 매수 (승률 70% 이상 패턴)"
            elif stats.get("win_rate", 0) >= 60 and feats["rs_20d"] > 30 and regime_str == "BULL":
                readiness = "🔥 LEVEL 3: 적극 매수 후보 (추세 돌파)"
            elif top10["top10_count"] >= 5 and feats["conviction"] > 70 and regime_str in ["NORMAL", "SIDEWAYS"]:
                readiness = "🟢 LEVEL 2: 분할 진입 준비 (TOP10 유지력)"
            elif top10["top10_count"] >= 3 and feats["rs_20d"] > 20:
                readiness = "🟡 LEVEL 1: 생존 확인 (관심 진입)"

        c["decision"]["buy_readiness"] = readiness
        
        # [교정] DB에서 추출한 지속성 데이터를 텔레그램 출력용 딕셔너리에 매핑
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
            if rank_idx <= 10:
                save_top10_tracking(scan_datetime, i['code'], i['name'], rank_idx, i['scores']['prime_final'], risk_level)
                
            actual_history_id = save_candidate_history(scan_datetime, run_type, i['code'], i['name'], rank_idx, i['price'], i['chg'], i['scores']['prime_final'], i['scores']['prime_score'], i['features']['conviction'], i['features']['rs_1d'], i['features']['rs_5d'], i['features']['rs_20d'], i['features']['ma_gap'], i['features']['amount'], i['features']['amount_strength'], risk_level, (1 if i["decision"].get("is_prime_leader") else 0))
            
            action_type = i["decision"]["action"]
            if "리더" in action_type or "최우선" in action_type or "진입" in action_type:
                register_signal_outcome(actual_history_id, i['code'], i['name'], i['price'], regime_str)
                
        except Exception: pass
            
    market["regime"] = regime_str
    return {"market": market, "stats": scanner_output.get("stats", {}), "candidates": evaluated_results}
