from typing import Dict, List, Any

def format_market_report(stats: Dict[str, Any]) -> str:
    """ market_report.py 에서 전달된 시장 요약 데이터를 포매팅 """
    state = stats.get("state", "UNKNOWN")
    val_pass = state != "INVALID"
    val_text = "PASS" if val_pass else "FAIL"
    
    # 이모지 세팅
    state_emoji = "🟢" if state == "NORMAL" else "🔴" if state == "CRASH" else "🟡"
    
    msg = f"🌐 <b>시장 데이터 검증 : {val_text}</b>\n"
    msg += f"시장 국면 : {state_emoji} <b>{state}</b> (강도: {stats.get('score', 0)}점)\n"
    msg += f"KOSPI : {stats.get('kospi_1d', 0.0)}% | KOSDAQ : {stats.get('kosdaq_1d', 0.0)}%\n"
    msg += f"판단 근거 : {stats.get('reason', 'N/A')}\n"
    msg += f"출처 : {stats.get('source', '알수없음')}\n\n"
    
    up_cnt = stats.get('total_up', 0)
    down_cnt = stats.get('total_down', 0)
    same_cnt = stats.get('total_same', 0)
    
    msg += f"📈 상승 {up_cnt} | 하락 {down_cnt} | 보합 {same_cnt}\n"
    msg += f"📊 상승 비율(Breadth) : <b>{stats.get('advance_ratio', 0.0)}%</b>\n"
    
    return msg

def format_holding_report(holdings: List[Dict[str, Any]]) -> str:
    """ 보유 종목 평가 결과 포매팅 """
    if not holdings:
        return "등록된 보유 종목이 없습니다."
        
    lines = []
    for idx, h in enumerate(holdings, 1):
        name = h.get("name", "Unknown")
        pnl = h.get("pnl", 0.0)
        judgment = h.get("judgment", "보유")
        lines.append(f"{idx}. <b>{name}</b> ({pnl}%) | <b>{judgment}</b>")
        
    return "\n".join(lines)

def format_signal_report(decision_results: Dict[str, Any]) -> str:
    """ decision_engine 의 결과를 포매팅 """
    buy_blocked = decision_results.get("buy_blocked", False)
    block_reason = decision_results.get("block_reason", "")
    alert_cands = decision_results.get("alert_candidates", [])
    level_counts = decision_results.get("level_counts", {})
    
    msg = ""
    
    # [수정] 매수 차단 시 return으로 끝내지 않고 경고문만 상단에 부착
    if buy_blocked:
        msg += f"⚠️ <b>신규 매수 차단됨</b>\n사유: {block_reason}\n\n"
        
    msg += f"<b>[티어별 추천 현황]</b>\n"
    msg += f"LEVEL 3: {level_counts.get('LEVEL 3', 0)}개 | "
    msg += f"LEVEL 2: {level_counts.get('LEVEL 2', 0)}개 | "
    msg += f"LEVEL 1: {level_counts.get('LEVEL 1', 0)}개\n\n"
    
    msg += f"👑 <b>Prime Leader (최상위 타점)</b>\n"
    if not alert_cands:
        msg += "오늘의 추천 타점이 없습니다.\n"
    else:
        prime = alert_cands[0]
        name = prime.get('name', 'Unknown')
        price = prime.get('price', 0)
        chg = prime.get('chg', 0.0)
        
        # decision_engine.py 의 실제 출력 키값인 final_score, true_rs 사용
        decision = prime.get('decision', {})
        score = decision.get('final_score', 'N/A')
        rs = decision.get('true_rs', 'N/A')
        
        msg += f"⭐ <b>{name}</b> | {price:,}원 ({chg}%)\n"
        msg += f"점수: <b>{score}</b> | RS: <b>{rs}</b>\n"
        
        if len(alert_cands) > 1:
            msg += "\n📈 <b>Observation (추가 관찰)</b>\n"
            for idx, c in enumerate(alert_cands[1:5], 2):
                c_score = c.get('decision', {}).get('final_score', 'N/A')
                msg += f"{idx}. {c.get('name')} ({c.get('chg')}%) | 점수: {c_score}\n"
                
    return msg
