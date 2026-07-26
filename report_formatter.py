from typing import Dict, List, Any

# (format_market_report, format_holding_report는 기존과 동일)

def format_signal_report(decision_results: Dict[str, Any]) -> str:
    """ decision_engine 의 결과를 포매팅 """
    buy_blocked = decision_results.get("buy_blocked", False)
    block_reason = decision_results.get("block_reason", "")
    alert_cands = decision_results.get("alert_candidates", [])
    level_counts = decision_results.get("level_counts", {})
    
    msg = ""
    
    if buy_blocked:
        msg += f"⚠️ <b>신규 매수 차단됨</b>\n사유: {block_reason}\n\n"
        
    msg += f"<b>[티어별 현황]</b>\n"
    # [핵심] 매수 차단 시 용어를 '관찰'로 변경하여 혼선 방지
    if buy_blocked:
        msg += f"관찰 L3: {level_counts.get('LEVEL 3', 0)}개 | "
        msg += f"관찰 L2: {level_counts.get('LEVEL 2', 0)}개 | "
        msg += f"관찰 L1: {level_counts.get('LEVEL 1', 0)}개\n\n"
    else:
        msg += f"LEVEL 3: {level_counts.get('LEVEL 3', 0)}개 | "
        msg += f"LEVEL 2: {level_counts.get('LEVEL 2', 0)}개 | "
        msg += f"LEVEL 1: {level_counts.get('LEVEL 1', 0)}개\n\n"
    
    # [핵심] 국면에 따른 리더 타이틀 동적 변환
    leader_title = "👀 <b>Observation Leader (최우선 관찰)</b>" if buy_blocked else "👑 <b>Prime Leader (최상위 타점)</b>"
    msg += f"{leader_title}\n"
    
    if not alert_cands:
        msg += "오늘의 추천/관찰 타점이 없습니다.\n"
    else:
        prime = alert_cands[0]
        name = prime.get('name', 'Unknown')
        price = prime.get('price', 0)
        chg = prime.get('chg', 0.0)
        
        decision = prime.get('decision', {})
        score = decision.get('final_score', 'N/A')
        rs = decision.get('true_rs', 'N/A')
        
        msg += f"⭐ <b>{name}</b> | {price:,}원 ({chg}%)\n"
        msg += f"점수: <b>{score}</b> | RS: <b>{rs}</b>\n"
        
        # [핵심] 관찰 모드일 경우 실전 매수 진입(트리거) 조건 부착
        if buy_blocked:
            msg += f"\n📌 <b>사전 매수 준비 조건 (Watchlist)</b>\n"
            msg += f" □ 시장 국면 <b>WEAK</b> 이상 회복\n"
            msg += f" □ 시장 상승비율(Breadth) <b>40%</b> 이상\n"
            msg += f" □ 해당 종목 <b>단기 저항선(5일 고점)</b> 돌파\n"
            msg += f" □ 진입 시 <b>의미 있는 거래대금</b> 유입 확인\n"
        
        if len(alert_cands) > 1:
            msg += "\n📈 <b>Observation (추가 관찰)</b>\n"
            for idx, c in enumerate(alert_cands[1:5], 2):
                c_score = c.get('decision', {}).get('final_score', 'N/A')
                msg += f"{idx}. {c.get('name')} ({c.get('chg')}%) | 점수: {c_score}\n"
                
    return msg
