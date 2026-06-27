def evaluate_candidates(scanner_output):
    # ... (생략: 상단 데이터 수집 동일)
    for raw in raw_candidates:
        # [수정 1] 폭락장 셧다운 로직 최상단 배치
        if risk_level == 3:
            if feats["rs_20d"] > 20 and feats["conviction"] >= 60:
                action, rank_bonus = "🔥 폭락장 상대강도 리더", 20
                trade_plan["buy_p"] = 0 
            elif feats["rs_20d"] > 20:
                action, rank_bonus = "🟡 방어 후보", 5
        # ... (이하 동일 조건)
        
    # [수정 2] 통계적 신뢰도 중심의 Memory Score 계산 (Cap 25)
    for c in evaluated_results:
        mem = get_signal_persistence(c["code"])
        stats = c["pattern_stats"]
        win_score = (stats.get("win_rate", 0.0) / 100.0) * 0.6
        sample_score = min(stats.get("match_count", 0) / 20.0, 1.0) * 0.2
        memory_score = min((mem["five_days_days"] * 0.25) + (win_score * 100) + (sample_score * 100), 25)
        c["decision"]["_leader_score"] = c['scores']['prime_final'] + memory_score
            
    # [수정 3] 실제 생성된 history_id로 무결성 연결
    for i in evaluated_results:
        hid = save_candidate_history(..., is_leader=(1 if i["decision"].get("is_prime_leader") else 0))
        if "리더" in i["decision"]["action"] or "최우선" in i["decision"]["action"]:
            register_signal_outcome(hid, i['code'], i['name'], i['price'], risk_level)
    return {"candidates": evaluated_results}
