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
            "action": "조건 충족 전 관망 유지"
        },
        "LEVEL 1": {
            "title": "⚪ 관찰 단계",
            "meaning": "가능성은 있으나 매수 조건 부족",
            "action": "조건 충족 전 추세 변화 관찰"
        },
        "LEVEL 2": {
            "title": "🟡 관심 구간",
            "meaning": "우량 후보지만 아직 확실한 매수 타이밍 부족",
            "action": "조건 충족 전 관심 유지"
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
        next_conds.extend([
            "✔ 장중 TOP10 지속성 2회 이상 유지",
            "✔ 수급확신도 60점 이상 확보",
            "✔ 현재 상승 모멘텀 유지"
        ])
            
    if rs < 10 and "✔ 현재 상승 모멘텀 유지" not in next_conds: 
        next_conds.append("✔ 상대강도(RS20D) +10% 이상 돌파 필요")
    if conv < 50 and "✔ 수급확신도 60점 이상 확보" not in next_conds: 
        next_conds.append("✔ 수급확신도 50 이상 달성 필요")
    
    if rs >= 50 and conv >= 80:
        return get_level_comment("LEVEL 4", [])
        
    if not next_conds or is_fast_track:
        if regime_str == "BULL" and rs >= 25 and conv >= 70 and (t10_count >= 3 or recent_days >= 2) and stats.get("win_rate", 0) >= 60:
            return get_level_comment("LEVEL 4", [])
        elif (regime_str in ["BULL", "ROTATION", "SIDEWAYS", "NORMAL"] and rs >= 20 and conv >= 60 and (t10_count >= 2 or recent_days >= 2)) or is_fast_track:
            return get_level_comment("LEVEL 3", [])
        elif rs >= 10 and conv >= 50:
            return get_level_comment("LEVEL 2", [
                "✔ TOP10 지속성 2회 이상 유지",
                "✔ 수급확신도 60점 이상 확보",
                "✔ 현재 상승 모멘텀 유지"
            ])
            
    return get_level_comment("LEVEL 1", next_conds)

def calculate_trade_plan(price, ma_gap, risk_level):
    if risk_level >= 3:
        buy_p = int(price * 0.85); stop_p = int(buy_p * 0.90)
    elif ma_gap > 20:
        buy_p = int(price * 0.90); stop_p = int(buy_p * 0.92)
    elif ma_gap > 10:
        buy_p = int(price * 0.95); stop_p = int(buy_p * 0.95)
    else:
        buy_p = int(price * 0.98); stop_p = int(buy_p * 0.95)
        
    return {
        "entry": f"현재가 기준 {round((price-buy_p)/price*100, 1)}% 조정 시 (약 {buy_p}원)",
        "stop_loss": f"진입가 대비 {round((buy_p-stop_p)/buy_p*100, 1)}% 하락 시 (약 {stop_p}원)",
        "target1": f"진입가 대비 +10% (약 {int(buy_p * 1.10)}원)",
        "target2": f"진입가 대비 +20% (약 {int(buy_p * 1.20)}원)"
    }

# [수정] 텔레그램 송출 가드레일 허들 현실화 (RS>=25, Conv>=65)
def should_send_alert(c):
    ready = c["decision"]["buy_readiness"]
    lvl_val = ready.get("level", "LEVEL 0")
    conv = c["features"]["conviction"]
    rs = c["features"]["rs_20d"]
    
    if lvl_val in ["LEVEL 3", "LEVEL 4"]:
        return True
    if lvl_val == "LEVEL 2":
        if conv >= 65 and rs >= 25:
            return True
    return False

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
            ready_obj = calculate_buy_readiness(c, regime_str, top10, mem, stats)
            
            lvl_num = int(ready_obj["level"].replace("LEVEL ", ""))
            w_level = (lvl_num / 4.0) * 400
            w_conv = min(feats["conviction"], 100) * 2.5
            w_mom = min(max(feats["rs_20d"], 0), 100) * 2.0
            w_qual = min(c["scores"]["prime_score"], 100) * 1.0
            w_pers = min(t10_count, 10) * 5.0
            
            trade_score = w_level + w_conv + w_mom + w_qual + w_pers
            trade_plan = calculate_trade_plan(c["price"], feats["ma_gap"], risk_level)
                
            c["decision"]["trade_score"] = trade_score
            c["decision"]["buy_readiness"] = ready_obj
            c["decision"]["trade_plan"] = trade_plan
            c["decision"]["top10_stability"] = {"top10_count": t10_count, "recent_days": top10["days"], "avg_rank": top10["avg_rank"]}
            
            final_results.append(c)
            
        final_results.sort(key=lambda x: x["decision"]["trade_score"], reverse=True)
        
        # [수정] 텔레그램 송출용 알림 풀 분리
        alert_candidates = [c for c in final_results if should_send_alert(c)]
        
        max_lvl_obj = {"level": "LEVEL 0", "title": "🔴 매수 금지", "action": "관망 유지", "meaning": "현재 장세 진입 불가"}
        max_lvl_code = "없음"
        max_lvl_reason = "알림 조건을 충족하는 유효 후보군 없음"
        
        # [수정] 대표 종목 선정 논리를 전체 풀(final_results)이 아닌 '알림 풀(alert_candidates)' 기준으로 강제 동기화
        if alert_candidates:
            alert_candidates[0]["decision"]["is_trade_leader"] = True
            max_lvl_obj = alert_candidates[0]["decision"]["buy_readiness"]
            max_lvl_code = alert_candidates[0]["name"]
            
            lvl_val = max_lvl_obj.get("level", "LEVEL 0")
            if "LEVEL 4" in lvl_val: max_lvl_reason = "LEVEL 4 최상위 확률 우위 확정 + 수급 및 추세 완전 정렬"
            elif "LEVEL 3" in lvl_val: max_lvl_reason = "LEVEL 3 실전 진입 허용 + 수급확신도 및 모멘텀 임계점 동시 충족"
            elif "LEVEL 2" in lvl_val: max_lvl_reason = "조건부 관심 승격 (수급 및 모멘텀 돌파)"
            else: max_lvl_reason = "단기적 관심 후보"
                
        # Signal Outcome 등록 (DB 전체 풀 대상 유지)
        for c in final_results:
            c_lvl = c["decision"]["buy_readiness"].get("level", "LEVEL 0")
            if "LEVEL 3" in c_lvl or "LEVEL 4" in c_lvl:
                try: register_signal_outcome(c.get("history_id"), c['code'], c['name'], c['price'], regime_str)
                except Exception: pass
        
        # [신규] 형님 지시사항: 데이터 증발 지점 원천 추적 디버그 로그 강제 출력
        print("="*50)
        print(f"📊 [PIPELINE DATA FLOW DEBUG]")
        print(f"▶ 1. RAW 수신   : {len(raw_candidates)} 개")
        print(f"▶ 2. PASS1 통과 : {len(pass1_results)} 개")
        print(f"▶ 3. FINAL 산출 : {len(final_results)} 개")
        print(f"▶ 4. ALERT 추출 : {len(alert_candidates)} 개")
        print("-" * 50)
        print("[FINAL 상위 10개 평가 내역]")
        for c in final_results[:10]:
            print(f" {c['name']:<10} | {c['decision']['buy_readiness']['level']} | RS: {c['features']['rs_20d']:>6.1f} | Conv: {c['features']['conviction']:>3} | T10: {c['decision']['top10_stability']['top10_count']}")
        print("="*50)
                    
        market.update({
            "regime": regime_str, "direction": market_direction, "buy_tolerance": buy_tolerance, 
            "max_level_obj": max_lvl_obj, "max_level_code": max_lvl_code, "max_lvl_reason": max_lvl_reason
        })
        
        # [교정] 텔레그램 모듈(candidates)에는 정제된 alert_candidates만 전송하여 오작동(모순) 원천 차단
        return {"market": market, "stats": scanner_output.get("stats", {}), "candidates": alert_candidates, "database_candidates": final_results}
    
    except Exception as e:
        print(f"🚨 [DECISION ENGINE INTERNAL ERROR] {e}")
        traceback.print_exc()
        return {"stats": {"data_error": True}}
