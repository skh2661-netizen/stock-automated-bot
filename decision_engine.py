import datetime
import pytz
from database import save_candidate, save_candidate_history, get_signal_persistence, register_signal_outcome, get_signal_quality

def calculate_trade_plan(price, ma20_price, ma_gap, score):
    if ma_gap > 20: buy_p = int(price * 0.92)
    elif ma_gap > 10: buy_p = int(price * 0.96)
    else: buy_p = int(price * 0.985)

    pullback_price = max(int(ma20_price), int(price * 0.95))

    if score >= 80 and ma_gap <= 10: target1, target2 = price * 1.10, price * 1.18
    elif ma_gap <= 5: target1, target2 = price * 1.08, price * 1.15
    elif ma_gap <= 15: target1, target2 = price * 1.05, price * 1.10
    else: target1, target2 = price * 1.03, price * 1.06
    
    stop_p = int(buy_p * 0.95)
    return {"buy_p": buy_p, "pullback_price": pullback_price, "target_1": int(target1), "target_2": int(target2), "stop_p": stop_p}

def evaluate_candidates(scanner_output):
    market = scanner_output.get("market", {})
    raw_candidates = scanner_output.get("raw_data", [])
    run_type = market.get("mode", "OPEN_SCAN")
    risk_level = market.get("risk_level", 1)
    
    kst = pytz.timezone("Asia/Seoul")
    scan_datetime = datetime.datetime.now(kst).strftime("%Y-%m-%d %H:%M")
    
    evaluated_results = []
    
    for raw in raw_candidates:
        feats = raw["features"]
        scores = raw["scores"]
        
        trade_plan = calculate_trade_plan(raw["price"], feats["ma20_price"], feats["ma_gap"], scores["score"])
        
        action = "👀 관망"
        reason = []
        rank_bonus = 0
        
        # [수정 3 & 5] 폭락장(Risk 3) 셧다운 방어 로직 적용
        if feats["is_overheated"]:
            action = "⏳ 눌림 대기"
            reason.append("가격 확장 상태 (신규 진입 효율 감소)")
            rank_bonus -= 10
        elif feats["ma_gap"] > 15:
            action = "⏳ 눌림 대기"
            reason.append("20일선 상방 이격 부담")
        elif feats["ma_gap"] < -10:
            action = "♻️ 낙폭 과대 (RECOVERY)"
            reason.append("20일선 하방 이격 (낙폭 과대)")
        elif risk_level == 3:
            if feats["rs_20d"] > 20 and feats["conviction"] >= 60:
                action = "🔥 시장 생존 리더"
                reason.append("폭락장 생존 및 강력한 수급 동반 (즉시 진입 금지)")
                rank_bonus += 20
                trade_plan["buy_p"] = 0 # 실전 매매 필터: 즉시 진입가 블라인드 처리
            elif feats["rs_20d"] > 20:
                action = "🟡 방어 후보"
                reason.append("상대강도는 높으나 수급(Conviction) 부족")
                rank_bonus += 5
        elif scores["prime_score"] >= 75 and -10 <= feats["ma_gap"] <= 15:
            action = "🔥 최우선 관찰"
            reason.append("시장 대비 강한 수급 (분할 접근)")
            rank_bonus += 20
        elif scores["score"] >= 55 and -10 <= feats["ma_gap"] <= 15:
            action = "🟢 진입 후보"
            reason.append("진입 조건 충족")
            rank_bonus += 5
        else:
            reason.append("수급 및 위치 확인 단계")
            
        if feats["conviction"] < 40: reason.append("수급 확인 단계")
        elif feats["conviction"] < 60: reason.append("확신 형성 과정 (눌림 확인 필요)")
            
        rank_score = scores["prime_final"] + rank_bonus
        pattern_stats = get_signal_quality(risk_level, feats["rs_20d"], feats["conviction"])
        
        evaluated_results.append({
            "code": raw["code"], "name": raw["name"], "price": raw["price"], "chg": raw["chg"],
            "features": feats, "scores": scores, "trade_plan": trade_plan, "pattern_stats": pattern_stats,
            "decision": {"action": action, "reason": reason, "rank_score": rank_score, "is_prime_leader": False}
        })
        
    evaluated_results.sort(key=lambda x: x["decision"]["rank_score"], reverse=True)
    
    if evaluated_results:
        for c in evaluated_results:
            memory = get_signal_persistence(c["code"])
            stats = c["pattern_stats"]
            
            # [수정 2] 출현 편향 제거 및 실제 승률(Outcome) 기반의 Memory Confidence 재설계
            persistence_score = (min(memory.get("five_days_days", 0), 3) * 2) + (memory.get("leader_count", 0) * 6) + max(0, 10 - memory.get("max_rank", 10))
            win_rate = stats.get("win_rate", 0.0) if stats.get("is_valid") else 0.0
            sample_count = stats.get("match_count", 0)
            
            memory_score = (persistence_score * 0.4) + (win_rate * 0.4) + (min(sample_count, 20) * 0.2)
            c["decision"]["_leader_score"] = (c['scores']['prime_final'] * 0.5) + (c['features']['conviction'] * 0.3) + (20 if "진입" in c['decision']['action'] else 0) + memory_score
            
        prime_leader = max(evaluated_results, key=lambda x: x["decision"]["_leader_score"])
        prime_leader["decision"]["is_prime_leader"] = True
        
    for rank_idx, i in enumerate(evaluated_results, 1):
        is_leader_flag = 1 if i["decision"]["is_prime_leader"] else 0
        try:
            save_candidate(run_type, i['code'], i['name'], i['scores']['score'], i['trade_plan']['buy_p'], i['trade_plan']['target_1'], i['trade_plan']['target_2'], i['trade_plan']['stop_p'], i['price'], i['chg'], i['features']['ma_gap'], i['scores']['prime_score'], i['scores']['prime_final'], i['features']['conviction'], i['features']['amount_strength'], i['features']['rs_1d'], i['features']['rs_5d'], i['features']['rs_20d'], is_leader_flag, risk_level)
            
            actual_history_id = save_candidate_history(
                scan_datetime=scan_datetime, run_type=run_type, code=i['code'], name=i['name'], rank_position=rank_idx,
                price=i['price'], chg=i['chg'], prime_final=i['scores']['prime_final'], prime_score=i['scores']['prime_score'],
                conviction=i['features']['conviction'], rs_1d=i['features']['rs_1d'], rs_5d=i['features']['rs_5d'], rs_20d=i['features']['rs_20d'],
                ma_gap=i['features']['ma_gap'], amount=i['features']['amount'], amount_strength=i['features']['amount_strength'],
                risk_level=risk_level, is_leader=is_leader_flag, engine_version="V8.8.14"
            )
            
            action_type = i["decision"]["action"]
            if is_leader_flag or "최우선" in action_type or "진입" in action_type or "생존 리더" in action_type or "방어" in action_type:
                register_signal_outcome(history_id=actual_history_id, code=i['code'], name=i['name'], price_at_signal=i['price'])
                
        except Exception:
            import traceback
            traceback.print_exc()
            
    return {"market": market, "stats": scanner_output.get("stats", {}), "candidates": evaluated_results}
