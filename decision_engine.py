from datetime import datetime
import pytz
from database import save_candidate_history, get_signal_persistence, register_signal_outcome, get_signal_quality, get_top10_stability, save_top10_tracking, debug_history, debug_top10

def detect_market_regime(kospi, kosdaq):
    if kospi >= 1.0 and kosdaq >= 1.0: return "BULL", 0, "🟢 위험선호 증가 (초강세장)", "85%"
    elif kospi >= 1.0: return "BULL", 0, "🟢 대형주 주도 강세", "70%"
    elif kosdaq >= 2.0: return "ROTATION", 1, "🔵 특정 섹터 쏠림 (순환매)", "60%"
    elif kospi <= -3.0: return "CRASH", 3, "🔴 위험회피 (폭락장)", "10% 미만"
    elif kospi <= -1.0: return "WARNING", 2, "🟡 보수적 관망 (조정장)", "20%"
    elif abs(kospi) < 1.0 and kosdaq >= 1.0: return "ROTATION", 1, "🔵 섹터 순환매 (차별화)", "60%"
    else: return "SIDEWAYS", 1, "⚪ 박스권 횡보 (방향성 탐색)", "40%"

def calculate_buy_readiness(c, regime_str, top10, mem, stats):
    rs = c["features"]["rs_20d"]
    conv = c["features"]["conviction"]
    t10_count = top10["top10_count"]
    recent_days = top10["days"]
    
    if regime_str == "CRASH" or rs < -10:
        return "❌ LEVEL 0: 매수 금지 (시장/추세 붕괴)", ["✔ 추세 복구(RS20D -10% 이상) 및 시장 안정 필요"]
        
    next_conds = []
    
    is_fast_track = False
    if rs >= 35 and conv >= 65:
        is_fast_track = True
    elif t10_count < 2 and recent_days < 1:
        next_conds.append("✔ 장중 TOP10 2회 이상 또는 최근 2일 출현 필요")
            
    if rs < 10: next_conds.append("✔ 상대강도(RS20D) +10% 이상 돌파 필요")
    if conv < 50: next_conds.append("✔ Conviction 50 이상 수급 유입 필요")
    
    if rs >= 50 and conv >= 80:
        return "🚀 LEVEL 4: 적극 매수 구간 (초강력 수급 돌파)", []
        
    if not next_conds or is_fast_track:
        if regime_str == "BULL" and rs >= 25 and conv >= 70 and (t10_count >= 3 or recent_days >= 2) and stats.get("win_rate", 0) >= 60:
            return "🚀 LEVEL 4: 적극 매수 구간 (확률 우위)", []
        elif (regime_str in ["BULL", "ROTATION", "SIDEWAYS", "NORMAL"] and rs >= 20 and conv >= 60 and (t10_count >= 2 or recent_days >= 2)) or is_fast_track:
            return "🟢 LEVEL 3: 분할 매수 가능", []
        elif rs >= 10 and conv >= 50:
            return "🟡 LEVEL 2: 관심 편입", ["✔ TOP10 지속성 2회 이상 달성 시 LEVEL 3 진입"]
            
    return "👀 LEVEL 1: 관찰", next_conds

def evaluate_candidates(scanner_output):
    market = scanner_output.get("market", {})
    raw_candidates = scanner_output.get("raw_data", [])
    run_type = market.get("mode", "OPEN_SCAN")
    kospi_1d, kosdaq_1d = market.get("kospi", 0.0), market.get("kosdaq", 0.0)
    
    regime_str, risk_level, market_direction, buy_tolerance = detect_market_regime(kospi_1d, kosdaq_1d)
    
    # [교정] 저장 및 조회용 마스터 시계열 포맷 강제 통일 (초 단위까지 완전 일치)
    scan_datetime = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
    
    pass1_results = []
    
    for raw in raw_candidates:
        feats, scores = raw["features"], raw["scores"]
        
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
            
        pass1_results.append({
            "code": str(raw["code"]).zfill(6), "name": raw["name"], "price": raw["price"], "chg": raw["chg"],
            "features": feats, "scores": scores, "base_score": scores["prime_final"] + rank_bonus,
            "decision": {"action": action, "is_prime_leader": False}
        })
        
    pass1_results.sort(key=lambda x: x["base_score"], reverse=True)
    
    for rank_idx, c in enumerate(pass1_results, 1):
        try:
            if rank_idx <= 10: save_top10_tracking(scan_datetime, c['code'], c['name'], rank_idx, c['base_score'], risk_level)
            c["history_id"] = save_candidate_history(scan_datetime, run_type, c['code'], c['name'], rank_idx, c['price'], c['chg'], c['scores']['prime_final'], c['scores']['prime_score'], c['features']['conviction'], c['features']['rs_1d'], c['features']['rs_5d'], c['features']['rs_20d'], c['features']['ma_gap'], c['features']['amount'], c['features']['amount_strength'], risk_level, 0)
        except Exception: pass

    final_results = []
    for c in pass1_results:
        # [신규] TOP10 강제 디버그 출력
        debug_top10(c["code"])
        
        mem = get_signal_persistence(c["code"])
        top10 = get_top10_stability(c["code"])
        stats = get_signal_quality(regime_str, c["features"]["rs_20d"], c["features"]["conviction"])
        feats = c["features"]
        
        t10_count = top10["top10_count"]
        t10_bonus = 15 if t10_count >= 6 else (10 if t10_count >= 4 else (5 if t10_count >= 2 else 0))
        
        win_rate = stats.get("win_rate", 0.0) / 100.0
        confidence = win_rate * min(stats.get("match_count", 0) / 20.0, 1.0)
        memory_score = min((mem["five_days_days"] * 0.25) + (confidence * 0.65 * 100) + t10_bonus, 25)
        
        if regime_str == "CRASH": leader_score = (feats["rs_20d"] * 1.5) + (feats["conviction"] * 0.5)
        elif regime_str == "BULL": leader_score = (c["scores"]["prime_final"] * 0.8) + (feats["rs_20d"] * 0.7)
        else: leader_score = c["scores"]["prime_final"]
            
        final_score = c["base_score"] + memory_score
        readiness, next_conds = calculate_buy_readiness(c, regime_str, top10, mem, stats)
        
        c["decision"]["final_score"] = final_score
        c["decision"]["leader_score"] = leader_score
        c["decision"]["buy_readiness"] = readiness
        c["decision"]["next_conditions"] = next_conds
        c["decision"]["top10_stability"] = {"top10_count": t10_count, "recent_days": top10["days"], "avg_rank": top10["avg_rank"]}
        
        final_results.append(c)
        
    final_results.sort(key=lambda x: x["decision"]["final_score"], reverse=True)
    
    max_lvl, max_lvl_code, recommended_action = "LEVEL 0", "없음", "관망 및 현금 대기"
    if final_results:
        prime_leader = max(final_results, key=lambda x: x["decision"]["leader_score"])
        for c in final_results:
            if c["code"] == prime_leader["code"]:
                c["decision"]["is_prime_leader"] = True
                break
                
        for c in final_results:
            lvl = c["decision"]["buy_readiness"]
            if "LEVEL 4" in lvl: max_lvl, max_lvl_code, recommended_action = "LEVEL 4", c["name"], "조건부 적극 편입 검토"; break
            elif "LEVEL 3" in lvl and max_lvl not in ["LEVEL 4"]: max_lvl, max_lvl_code, recommended_action = "LEVEL 3", c["name"], "핵심 후보 분할 매수 접근"
            elif "LEVEL 2" in lvl and max_lvl not in ["LEVEL 4", "LEVEL 3"]: max_lvl, max_lvl_code, recommended_action = "LEVEL 2", c["name"], "관심 종목군 편입"
            elif "LEVEL 1" in lvl and max_lvl not in ["LEVEL 4", "LEVEL 3", "LEVEL 2"]: max_lvl, max_lvl_code = "LEVEL 1", c["name"]
            
            if "LEVEL 3" in lvl or "LEVEL 4" in lvl:
                try: register_signal_outcome(c.get("history_id"), c['code'], c['name'], c['price'], regime_str)
                except Exception: pass
                
    market.update({"regime": regime_str, "direction": market_direction, "buy_tolerance": buy_tolerance, "max_level": max_lvl, "max_level_code": max_lvl_code, "recommended_action": recommended_action})
    return {"market": market, "stats": scanner_output.get("stats", {}), "candidates": final_results}
