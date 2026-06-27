def format_scan_messages(run_type, result):
    if not result or "candidates" not in result: return ["⚠️ 데이터 추출 실패"]
    
    market = result.get("market", {})
    candidates = result.get("candidates", [])
    
    risk_level = market.get("risk_level", 1)
    risk_text = "위험도 0/100 (안정)" if risk_level == 1 else ("위험도 50/100 (조정)" if risk_level == 2 else "위험도 100/100 (극단적 약세)")
    
    # [신규] 텍스트 매칭으로 생존 후보 판독
    survival_count = sum(1 for c in candidates if "폭락장 상대강도 리더" in c["decision"]["action"] or "생존 감시 대상" in c["decision"]["action"])
    
    msg_list = []
    header = f"🎯 <b>V8.8.17 DAILY QUANT REPORT ({run_type})</b>\n\n"
    header += f"📊 <b>시장 지표</b>\n"
    header += f"KOSPI: {market.get('kospi', 0.0)}% | KOSDAQ: {market.get('kosdaq', 0.0)}%\n"
    header += f"시장 진단: {risk_text}\n"
    header += f"폭락장 생존 후보 포착: {survival_count} / {len(candidates)}\n"
    header += "━" * 20 + "\n\n"
    
    current_msg = header
    
    for idx, c in enumerate(candidates, 1):
        is_leader = c["decision"].get("is_prime_leader", False)
        icon = "👑 [PRIME WATCH]" if is_leader else f"🔹 {idx}위"
        
        block = f"{icon} <b>{c['name']}</b> ({c['code']})\n"
        block += f"등급: {c['decision']['action']}\n"
        block += f"Final: {c['scores']['prime_final']} | Prime: {c['scores']['prime_score']}\n"
        block += f"RS20D: {'+' if c['features']['rs_20d']>0 else ''}{c['features']['rs_20d']}% | Conv: {c['features']['conviction']}\n\n"
        
        # [신규] 지속성 및 매매 준비도 분석 투하
        t10 = c['decision'].get('top10_stability', {})
        block += f"📌 <b>지속성 분석</b>\n"
        block += f"오늘 TOP10 유지: {t10.get('top10_count', 0)}시간\n"
        block += f"평균 순위: {t10.get('avg_rank', 0.0)}위\n\n"
        block += f"🎯 <b>매매 준비도</b>\n"
        block += f"{c['decision'].get('buy_readiness', '👀 LEVEL 0: 관찰')}\n"
        
        block += "━" * 20 + "\n\n"
        
        if len(current_msg) + len(block) > 4000:
            msg_list.append(current_msg)
            current_msg = block
        else:
            current_msg += block
            
    if current_msg:
        msg_list.append(current_msg)
        
    return msg_list
