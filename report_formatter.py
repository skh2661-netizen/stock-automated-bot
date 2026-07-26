from typing import Dict, List, Any

def format_market_report(stats: Dict[str, Any]) -> str:
    state = stats.get("state", "UNKNOWN")
    val_pass = state != "INVALID"
    val_text = "PASS" if val_pass else "FAIL"
    
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
    buy_blocked = decision_results.get("buy_blocked", False)
    block_reason = decision_results.get("block_reason", "")
    alert_cands = decision_results.get("alert_candidates", [])
    
    msg = ""
    
    # ==========================================
    # 폭락장(매수 차단) 시 전용 UI 레이아웃
    # ==========================================
    if buy_blocked:
        msg += f"==========================\n"
        msg += f"🚫 <b>오늘 신규매수 불가</b>\n"
        msg += f"사유: {block_reason}\n"
        msg += f"==========================\n"
        msg += f"오늘 매수추천: <b>없음</b>\n"
        msg += f"==========================\n\n"
        
        msg += f"👀 <b>시장 회복 시 최우선 확인할 종목</b>\n"
        
        if not alert_cands:
            msg += "조건에 부합하는 관찰 종목이 없습니다.\n"
        else:
            prime = alert_cands[0]
            name = prime.get('name', 'Unknown')
            chg = prime.get('chg', 0.0)
            strats = prime.get('strategies', [])
            strat_str = ", ".join(strats) if strats else "전략 없음"
            
            decision = prime.get('decision', {})
            score = decision.get('watch_score', 'N/A')
            
            msg += f"① <b>{name}</b> ({chg}%)\n"
            msg += f"관찰점수: <b>{score}</b> | 적용전략: <b>{strat_str}</b>\n\n"
            
            msg += f"📌 <b>매수 진입 조건 (Checklist)</b>\n"
            msg += f" □ 시장 국면 <b>NORMAL / WEAK</b> 회복\n"
            msg += f" □ 시장 상승비율(Breadth) <b>40%</b> 이상\n"
            msg += f" □ 해당 종목 <b>단기 저항선(5일 고점)</b> 돌파\n"
            msg += f" □ 진입 시 <b>의미 있는 거래량</b> 증가\n\n"
            
            if len(alert_cands) > 1:
                msg += f"<b>[추가 관찰 후보]</b>\n"
                for idx, c in enumerate(alert_cands[1:5], 2):
                    c_dec = c.get('decision', {})
                    c_strats = ", ".join(c.get('strategies', []))
                    c_score = c_dec.get('watch_score', 'N/A')
                    msg += f" {idx}. {c.get('name')} ({c.get('chg')}%) | 점수: {c_score} | {c_strats}\n"
                    
        msg += f"\n==========================\n"
        msg += f"👉 <b>현재 행동: 현금 유지 및 관망</b>\n"
        msg += f"=========================="
        return msg

    # ==========================================
    # 정상장(매수 가능) 시 기존 UI 레이아웃
    # ==========================================
    level_counts = decision_results.get("level_counts", {})
    msg += f"<b>[티어별 현황]</b>\n"
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
        strats = prime.get('strategies', [])
        strat_str = ", ".join(strats) if strats else "전략 없음"
        
        decision = prime.get('decision', {})
        score = decision.get('final_score', 'N/A')
        rs = decision.get('true_rs', 'N/A')
        
        msg += f"⭐ <b>{name}</b> | {price:,}원 ({chg}%)\n"
        msg += f"점수: <b>{score}</b> | RS: <b>{rs}</b> | <b>{strat_str}</b>\n"
        
        if len(alert_cands) > 1:
            msg += "\n📈 <b>Observation (추가 관찰)</b>\n"
            for idx, c in enumerate(alert_cands[1:5], 2):
                c_dec = c.get('decision', {})
                c_strats = ", ".join(c.get('strategies', []))
                c_score = c_dec.get('final_score', 'N/A')
                msg += f"{idx}. {c.get('name')} ({c.get('chg')}%) | 점수: {c_score} | {c_strats}\n"
                
    return msg
