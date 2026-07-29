import logging

_logger = logging.getLogger(__name__)

def format_market_report(stats: dict) -> str:
    """
    텔레그램 전송을 위해 시장 리포트 딕셔너리를 HTML 형태의 문자열로 포맷팅합니다.
    """
    # 상태별 이모지 설정
    state = stats.get('state', 'UNKNOWN')
    if state == 'CRASH': state_str = f"🔴 {state}"
    elif state == 'WEAK': state_str = f"🟠 {state}"
    elif state == 'CAUTION': state_str = f"🟡 {state}"
    elif state == 'NORMAL': state_str = f"🟢 {state}"
    else: state_str = state
    
    scan_status = "PASS" if stats.get("allow_scan") else "FAIL (신규매수 차단)"

    msg = f"🌐 시장 데이터 검증 : {scan_status}\n"
    msg += f"시장 국면 : {state_str} (강도: {stats.get('score')}점)\n"
    msg += f"KOSPI : {stats.get('kospi_1d')}% | KOSDAQ : {stats.get('kosdaq_1d')}%\n"
    msg += f"판단 근거 : {stats.get('reason')}\n"
    
    # 신뢰도 및 경고 (출처 바로 앞)
    msg += f"신뢰도 : {stats.get('confidence_level', 'HIGH')} ({stats.get('confidence', 100)}점)\n"
    warning = stats.get("warning", "")
    if warning:
        msg += f"⚠️ {warning}\n"
        
    msg += f"출처 : {stats.get('source', '알수없음')}\n\n"
    
    msg += f"📈 상승 {stats.get('total_up')} | 하락 {stats.get('total_down')} | 보합 {stats.get('total_same')}\n"
    msg += f"📊 상승 비율(Breadth) : {stats.get('advance_ratio')}%\n"
    
    return msg


def format_holding_report(holding_evals: list) -> str:
    """
    보유 종목의 수익률 및 액션(EXIT/HOLD/DATA_MISSING) 상태를 포맷팅합니다.
    """
    if not holding_evals:
        return "보유 종목이 없습니다."
        
    lines = []
    for i, item in enumerate(holding_evals, 1):
        name = item.get("name", "Unknown")
        rtn = item.get("return_rate", item.get("profit_rate", 0.0))
        action = item.get("action", "HOLD")
        
        # [핵심] 데이터 누락 시 확실한 시각적 경고
        if action == "DATA_MISSING":
            lines.append(f"{i}. {name} | ❓ 가격조회실패 (데이터 누락)")
        else:
            lines.append(f"{i}. {name} ({rtn:.2f}%) | {action}")
        
    return "\n".join(lines)


def format_signal_report(decision_results: dict) -> str:
    """
    신규 추천(매수 시그널) 종목을 포맷팅합니다.
    """
    # 데이터 구조에 따라 signals 또는 candidates 리스트를 가져옴
    signals = decision_results.get("signals", decision_results.get("candidates", []))
    
    if not signals:
        return "==========================\n오늘 매수추천: 없음\n=========================="
        
    lines = []
    for i, sig in enumerate(signals, 1):
        name = sig.get("name", "Unknown")
        chg = sig.get("chg", 0.0)
        score = sig.get("score", 0.0)
        strategy = sig.get("strategy", "N/A")
        
        # 숫자 원문자 변환 (①, ②, ③ 등)
        circle_num = chr(0x245F + i) if 1 <= i <= 20 else f"{i}."
        
        lines.append(f"{circle_num} {name} ({chg}%)")
        lines.append(f"관찰점수: {score} | 적용전략: {strategy}")
        lines.append("") # 줄바꿈 여백
        
    return "\n".join(lines).strip()
