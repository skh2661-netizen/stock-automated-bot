from datetime import datetime
import pytz
from database import save_candidate_history, get_signal_persistence, register_signal_outcome, get_signal_quality, get_top10_stability, save_top10_tracking, debug_history, debug_top10

def detect_market_regime(kospi, kosdaq):
    if kospi >= 1.0 and kosdaq >= 1.0: return "BULL", 0, "🟢 위험선호 증가 (초강세장)", "85점 / 100점"
    elif kospi >= 1.0: return "BULL", 0, "🟢 대형주 주도 강세", "70점 / 100점"
    elif kosdaq >= 2.0: return "ROTATION", 1, "🔵 특정 섹터 쏠림 (순환매)", "60점 / 100점"
    elif kospi <= -3.0: return "CRASH", 3, "🔴 위험회피 (폭락장)", "10점 / 100점"
    elif kospi <= -1.0: return "WARNING", 2, "🟡 보수적 관망 (조정장)", "20점 / 100점"
    elif abs(kospi) < 1.0 and kosdaq >= 1.0: return "ROTATION", 1, "🔵 섹터 순환매 (차별화)", "60점 / 100점"
    else: return "SIDEWAYS", 1, "⚪ 박스권 횡보 (방향성 탐색)", "40점 / 100점"

def get_level_comment(level_key, next_conds=None):
    if next_conds is None: next_conds = []
    comments = {
        "LEVEL 0": {
            "title": "🔴 매수 금지",
            "meaning": "추세 또는 시장 환경이 좋지 않아 신규 진입 위험",
            "action": "관망 유지 및 현금 확보"
        },
        "LEVEL 1": {
            "title": "⚪ 관찰 단계",
            "meaning": "가능성은 있으나 매수 조건 부족",
            "action": "추세 변화 및 수급 유입 확인"
        },
        "LEVEL 2": {
            "title": "🟡 관심 구간",
            "meaning": "우량 후보지만 아직 확실한 매수 타이밍 부족",
            "action": "조건 충족 대기 (관심종목 편입)"
        },
        "LEVEL 3": {
            "title": "🟢 분할 매수 구간",
            "meaning": "상승 조건과 수급 흐름 확인, 단계적 진입 가능",
            "action": "1차 분할 접근 (30~40%) 검토"
        },
        "LEVEL 4": {
            "title": "🚀 적극 매수 구간",
            "meaning": "강한 추세와 수급이 동시에 확인된 확률적 우위 상태",
            "action": "적극 편입 검토"
        }
    }
    res = comments.get(level_key, {}).copy()
    res["level"] = level_key
    res["conditions"] = next_conds
    return res

def calculate_buy_readiness(c, regime_str, top10, mem, stats):
    rs = c["features"]["rs_20d"]
    conv = c["features"]["conviction"]
    t10_count = top10["top10_count"]
    recent_days = top10["days"]
    
    if regime_str == "CRASH" or rs < -10:
        return get_level_comment("LEVEL 0", ["✔ 추세 복구(RS20D -10% 이상) 및 시장 하락 진정"])
        
    next_conds = []
    is_fast_track = False
    
    if rs >= 35 and conv >= 65:
        is_fast_track = True
    elif t10_count < 2 and recent_days < 1:
        next_conds.append("✔ 장중 TOP10 2회 이상 또는 최근 2일 출현 필요")
            
    if rs < 10: next_conds.append("✔ 상대강도(RS20D) +10% 이상 돌파 필요")
    if conv < 50: next_conds.append("✔ 수급확신도 50 이상 달성 필요")
    
    if rs >= 50 and conv >= 80:
        return get_level_comment("LEVEL 4", [])
        
    if not next_conds or is_fast_track:
        if regime_str == "BULL" and rs >= 25 and conv >= 70 and (t10_count >= 3 or recent_days >= 2) and stats.get("win_rate", 0) >= 60:
            return get_level_comment("LEVEL 4", [])
        elif (regime_str in ["BULL", "ROTATION", "SIDEWAYS", "NORMAL"] and rs >= 20 and conv >= 60 and (t10_count >= 2 or recent_days >= 2)) or is_fast_track:
            return get_level_comment("LEVEL 3", [])
        elif rs >= 10 and conv >= 50:
            return get_level_comment("LEVEL 2", ["✔ TOP10 지속성 2회 이상 달성 시 LEVEL 3 진입"])
            
    return get_level_comment("LEVEL 1", next_conds)

# [신규] 실전 매매 계획 자동 산출
def calculate_trade_plan(price, ma_gap, risk_level):
    if risk_level >= 3:
        buy_p = int(price * 0.85)
        stop_p = int(buy_p * 0.90)
    elif ma_gap > 20:
        buy_p = int(price * 0.90)
        stop_p = int(buy_p * 0.92)
    elif ma_gap > 10:
        buy_p = int(price * 0.95)
        stop_p = int(buy_p * 0.95)
    else:
        buy_p = int(price * 0.98)
        stop_p = int(buy_p * 0.95)
        
    return {
        "entry": f"현재가 기준 {round((price-buy_p)/price*100, 1)}% 조정 시 (약 {buy_p}원)",
        "stop_loss": f"진입가 대비 {round((buy_p-stop_p)/buy_p*100, 1)}% 하락 시 (약 {stop_p}원)",
        "target1": f"진입가 대비 +10% (약 {int(buy_p * 1.10)}원)",
        "target2": f"진입가 대비 +20% (약 {int(buy_p * 1.20)}원)"
    }

def evaluate_candidates(scanner_output):
    import traceback
    try:
        market = scanner_output.get("market", {})
        raw_candidates = scanner_output.get("raw_data", [])
        run_type = market.get("mode", "OPEN_SCAN")
        kospi_1d, kosdaq_1d = market.get("kospi", 0.0), market.get("kosdaq", 0.0)
        
        regime_str, risk_level, market_direction, buy_tolerance = detect_market_regime(kospi_1d, kosdaq_1d)
        scan_datetime = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
        
        pass1_results = []
        for raw in raw_candidates:
            feats, scores = raw["features"], raw["scores"]
            if scores["prime_score"] < 50 or feats["conviction"] < 40: continue
            if risk_level < 3 and feats["rs_20d"] < -5: continue
            
            action, rank_bonus = "👀 관망", 0
            if regime_str == "CRASH":
                if feats["rs_20d"] > 15 and feats["conviction"] >= 60: action, rank_bonus = "🔥 폭락장 방어 리더", 20
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
                "decision": {"action": action, "is_trade_leader": False}
            })
            
        pass1_results.sort(key=lambda x: x["base_score"], reverse=True)
        
        for rank_idx, c in enumerate(pass1_results, 1):
            try:
                if rank_idx <= 10: save_top10_tracking(scan_datetime, c['code'], c['name'], rank_idx, c['base_score'], risk_level)
                c["history_id"] = save_candidate_history(scan_datetime, run_type, c['code'], c['name'], rank_idx, c['price'], c['chg'], c['scores']['prime_final'], c['scores']['prime_score'], c['features']['conviction'], c['features']['rs_1d'], c['features']['rs_5d'], c['features']['rs_20d'], c['features']['ma_gap'], c['features']['amount'], c['features']['amount_strength'], risk_level, 0)
            except Exception: pass

        final_results = []
        for c in pass1_results:
            mem = get_signal_persistence(c["code"])
            top10 = get_top10_stability(c["code"])
            stats = get_signal_quality(regime_str, c["features"]["rs_20d"], c["features"]["conviction"])
            feats = c["features"]
            
            t10_count = top10["top10_count"]
            t10_bonus = 15 if t10_count >= 6 else (10 if t10_count >= 4 else (5 if t10_count >= 2 else 0))
            
            ready_obj = calculate_buy_readiness(c, regime_str, top10, mem, stats)
            
            # [교정] Trade Score 입체화: 단순 LEVEL 절대주의 타파 (모멘텀과 수급 비중 상승)
            lvl_num = int(ready_obj["level"].replace("LEVEL ", ""))
            momentum_score = feats["rs_20d"] * 2.5
            quality_score = c["scores"]["prime_score"] * 0.5
            trade_score = (lvl_num * 100) + momentum_score + feats["conviction"] + quality_score + (t10_count * 10)
            
            trade_plan = calculate_trade_plan(c["price"], feats["ma_gap"], risk_level)
                
            c["decision"]["trade_score"] = trade_score
            c["decision"]["momentum_score"] = momentum_score
            c["decision"]["quality_score"] = quality_score
            c["decision"]["buy_readiness"] = ready_obj
            c["decision"]["trade_plan"] = trade_plan
            c["decision"]["top10_stability"] = {"top10_count": t10_count, "recent_days": top10["days"], "avg_rank": top10["avg_rank"]}
            
            final_results.append(c)
            
        final_results.sort(key=lambda x: (x["decision"]["trade_score"], x["decision"]["momentum_score"]), reverse=True)
        
        max_lvl_obj = {"level": "LEVEL 0", "title": "🔴 매수 금지", "action": "관망 유지", "meaning": "현재 장세 진입 불가"}
        max_lvl_code = "없음"
        
        if final_results:
            final_results[0]["decision"]["is_trade_leader"] = True
            
            for c in final_results:
                # [교정] 구버전 문자열 참조 오류(TypeError) 원천 차단
                lvl_val = c["decision"]["buy_readiness"].get("level", "LEVEL 0")
                if "LEVEL 4" in lvl_val: max_lvl_obj = c["decision"]["buy_readiness"]; max_lvl_code = c["name"]; break
                elif "LEVEL 3" in lvl_val and max_lvl_obj["level"] not in ["LEVEL 4"]: max_lvl_obj = c["decision"]["buy_readiness"]; max_lvl_code = c["name"]
                elif "LEVEL 2" in lvl_val and max_lvl_obj["level"] not in ["LEVEL 4", "LEVEL 3"]: max_lvl_obj = c["decision"]["buy_readiness"]; max_lvl_code = c["name"]
                elif "LEVEL 1" in lvl_val and max_lvl_obj["level"] not in ["LEVEL 4", "LEVEL 3", "LEVEL 2"]: max_lvl_obj = c["decision"]["buy_readiness"]; max_lvl_code = c["name"]
                
                if "LEVEL 3" in lvl_val or "LEVEL 4" in lvl_val:
                    try: register_signal_outcome(c.get("history_id"), c['code'], c['name'], c['price'], regime_str)
                    except Exception: pass
                    
        market.update({"regime": regime_str, "direction": market_direction, "buy_tolerance": buy_tolerance, "max_level_obj": max_lvl_obj, "max_level_code": max_lvl_code})
        return {"market": market, "stats": scanner_output.get("stats", {}), "candidates": final_results}
    except Exception as e:
        print(f"🚨 [DECISION ENGINE INTERNAL ERROR] {e}")
        traceback.print_exc()
        return {"stats": {"data_error": True}}
