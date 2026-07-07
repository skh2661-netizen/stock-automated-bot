from datetime import datetime
import pytz
import traceback
from database import (
    save_candidate_history, get_signal_persistence, register_signal_outcome,
    get_signal_quality, get_top10_stability, save_top10_tracking,
    debug_history, debug_top10
)

def detect_market_regime(kospi, kosdaq):
    if kospi >= 1.5 and kosdaq >= 1.5: return "BULL", 0, "🟢 위험선호 증가 (초강세장)", "85점 / 100점"
    elif kospi >= 0.5 and kosdaq >= 0.5: return "BULL", 0, "🟢 대형/중소형주 동반 강세", "70점 / 100점"
    elif kospi >= 0.3 or kosdaq >= 0.3: return "ROTATION", 1, "🔵 특정 섹터 쏠림 (순환매)", "60점 / 100점"
    elif kospi <= -3.0: return "CRASH", 3, "🔴 위험회피 (폭락장)", "10점 / 100점"
    elif kospi <= -1.5: return "WARNING", 2, "🟡 보수적 관망 (조정장)", "20점 / 100점"
    elif abs(kospi) < 0.3 and kosdaq >= 0.0: return "ROTATION", 1, "🔵 개별 종목 장세 (차별화)", "50점 / 100점"
    else: return "SIDEWAYS", 1, "⚪ 박스권 횡보 (방향성 탐색)", "40점 / 100점"

def get_level_comment(level_key, next_conds=None):
    if next_conds is None: next_conds = []
    comments = {
        "LEVEL 0": {"title": "🔴 매수 금지", "meaning": "추세 붕괴 및 폭락장 셧다운", "action": "조건 충족 전 관망 유지"},
        "LEVEL 1": {"title": "⚪ 관찰 단계", "meaning": "조건 대폭 미달", "action": "조건 충족 전 추세 변화 관찰"},
        "LEVEL 2": {"title": "🟡 관심 구간", "meaning": "폭락장 예외 주도주 또는 타이밍 대기", "action": "조건 충족 전 관심 유지"},
        "LEVEL 3": {"title": "🟢 분할 매수 구간", "meaning": "진입 가능", "action": "1차 분할 접근 (30~40%) 검토"},
        "LEVEL 4": {"title": "🚀 적극 매수 구간", "meaning": "확률적 우위", "action": "적극 편입 검토"}
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
    
    if regime_str == "CRASH":
        if rs >= 60 and conv >= 85:
            return get_level_comment("LEVEL 4", [])
        elif rs >= 30 and conv >= 70:
            return get_level_comment("LEVEL 3", ["✔ 폭락장 리더 종목"])
        elif rs >= 10 or conv >= 75:
            return get_level_comment("LEVEL 2", ["✔ 폭락장 예외 관찰 대상"])
        else:
            return get_level_comment("LEVEL 0", ["✔ 시장 하락 진정 및 개별 종목 추세 복구 대기"])
        
    if rs < -10:
        return get_level_comment("LEVEL 0", ["✔ 추세 복구(RS20D -10% 이상)"])
        
    next_conds = []
    is_fast_track = False
    
    if rs >= 20 and conv >= 60:
        is_fast_track = True
            
    if rs < 5: next_conds.append("✔ 상대강도(RS20D) +5% 이상 복구 필요")
    if conv < 45: next_conds.append("✔ 수급확신도 45점 이상 유입 필요")
    
    if rs >= 40 and conv >= 75: return get_level_comment("LEVEL 4", [])
        
    if not next_conds or is_fast_track:
        if regime_str == "BULL" and rs >= 20 and conv >= 65 and stats.get("win_rate", 0) >= 50:
            return get_level_comment("LEVEL 4", [])
        elif (regime_str in ["BULL", "ROTATION", "SIDEWAYS", "NORMAL"] and rs >= 10 and conv >= 55) or is_fast_track:
            return get_level_comment("LEVEL 3", [])
        elif rs >= 5 and conv >= 45:
            return get_level_comment("LEVEL 2", ["✔ 장중 수급 연속성 및 추가 모멘텀 확인"])
            
    return get_level_comment("LEVEL 1", next_conds)

def calculate_trade_plan(price, ma_gap, risk_level):
    if risk_level >= 3: buy_p = int(price * 0.85); stop_p = int(buy_p * 0.90)
    elif ma_gap > 20: buy_p = int(price * 0.90); stop_p = int(buy_p * 0.92)
    elif ma_gap > 10: buy_p = int(price * 0.95); stop_p = int(buy_p * 0.95)
    else: buy_p = int(price * 0.98); stop_p = int(buy_p * 0.95)
        
    return {
        "entry": f"현재가 기준 {round((price-buy_p)/price*100, 1)}% 조정 시 (약 {buy_p}원)",
        "stop_loss": f"진입가 대비 {round((buy_p-stop_p)/buy_p*100, 1)}% 하락 시 (약 {stop_p}원)",
        "target1": f"진입가 대비 +10% (약 {int(buy_p * 1.10)}원)",
        "target2": f"진입가 대비 +20% (약 {int(buy_p * 1.20)}원)"
    }

def should_send_alert(c):
    ready = c["decision"]["buy_readiness"]
    lvl = ready.get("level", "LEVEL 0")
    regime = c.get("market_regime", "")
    
    if regime == "CRASH":
        return lvl in ["LEVEL 2", "LEVEL 3", "LEVEL 4"]
    
    return lvl in ["LEVEL 3", "LEVEL 4"]

def evaluate_candidates(scanner_output):
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
            
            pass1_results.append({
                "code": str(raw["code"]).zfill(6), 
                "name": raw["name"], 
                "price": raw["price"], 
                "chg": raw["chg"],
                "features": feats, 
                "scores": scores, 
                "base_score": scores["prime_final"],
                "market_regime": regime_str,
                "decision": {"action": "관망", "is_trade_leader": False}
            })
            
        pass1_results.sort(key=lambda x: x["base_score"], reverse=True)
        
        for rank_idx, c in enumerate(pass1_results, 1):
            try:
                if rank_idx <= 10: 
                    save_top10_tracking(
                        scan_datetime, c['code'], c['name'], 
                        rank_idx, c['base_score'], risk_level
                    )
                c["history_id"] = save_candidate_history(
                    scan_datetime, run_type, c['code'], c['name'], rank_idx, 
                    c['price'], c['chg'], c['scores']['prime_final'], 
                    c['scores']['prime_score'], c['features']['conviction'], 
                    c['features']['rs_1d'], c['features']['rs_5d'], 
                    c['features']['rs_20d'], c['features']['ma_gap'], 
                    c['features']['amount'], c['features']['amount_strength'], 
                    risk_level, 0
                )
            except Exception: 
                pass

        final_results = []
        for c in pass1_results:
            mem = get_signal_persistence(c["code"])
            top10 = get_top10_stability(c["code"])
            stats = get_signal_quality(regime_str, c["features"]["rs_20d"], c["features"]["conviction"])
            feats = c["features"]
            
            t10_count = top10["top10_count"]
            ready_obj = calculate_buy_readiness(c, regime_str, top10, mem, stats)
            
            lvl_num = int(ready_obj["level"].replace("LEVEL ", ""))
            
            # 긴 줄바꿈 처리
            w_level = (lvl_num / 4.0) * 400
            w_conv = min(feats["conviction"], 100) * 2.5
            w_mom = min(max(feats["rs_20d"], 0), 100) * 2.0
            w_qual = min(c["scores"]["prime_score"], 100) * 1.0
            w_pers = min(t10_count, 10) * 5.0
            trade_score = w_level + w_conv + w_mom + w_qual + w_pers
                
            c["decision"]["trade_score"] = trade_score
            c["decision"]["buy_readiness"] = ready_obj
            c["decision"]["trade_plan"] = calculate_trade_plan(c["price"], feats["ma_gap"], risk_level)
            c["decision"]["top10_stability"] = {"top10_count": t10_count, "recent_days": top10["days"], "avg_rank": top10["avg_rank"]}
            
            final_results.append(c)
            
        final_results.sort(key=lambda x: x["decision"]["trade_score"], reverse=True)
        alert_candidates = [c for c in final_results if should_send_alert(c)]
        
        max_lvl_obj = {"level": "LEVEL 0", "title": "🔴 매수 금지", "action": "관망 유지"}
        max_lvl_code = "없음"
        max_lvl_reason = "조건을 충족하는 유효 후보군 없음"
        
        if final_results:
            final_results[0]["decision"]["is_trade_leader"] = True
            max_lvl_obj = final_results[0]["decision"]["buy_readiness"]
            max_lvl_code = final_results[0]["name"]
            max_lvl_reason = "전체 후보군 중 종합 점수 1위"
                    
        market.update({
            "regime": regime_str, 
            "direction": market_direction, 
            "buy_tolerance": buy_tolerance, 
            "max_level_obj": max_lvl_obj, 
            "max_level_code": max_lvl_code, 
            "max_lvl_reason": max_lvl_reason
        })
        
        return {
            "market": market, 
            "stats": scanner_output.get("stats", {}), 
            "candidates": final_results, 
            "alert_candidates": alert_candidates
        }
    
    except Exception as e:
        print(f"🚨 [DECISION ENGINE ERROR] {e}")
        traceback.print_exc()
        return {"stats": {"data_error": True}}
