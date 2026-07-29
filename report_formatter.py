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
    
    # [정확히 지시하신 위치] 신뢰도 및 경고 (출처 바로 앞)
    msg += f"신뢰도 : {stats.get('confidence_level')} ({stats.get('confidence')}점)\n"
    warning = stats.get("warning", "")
    if warning:
        msg += f"⚠️ {warning}\n"
        
    msg += f"출처 : {stats.get('source', '알수없음')}\n\n"
    
    msg += f"📈 상승 {stats.get('total_up')} | 하락 {stats.get('total_down')} | 보합 {stats.get('total_same')}\n"
    msg += f"📊 상승 비율(Breadth) : {stats.get('advance_ratio')}%\n"
    
    return msg

# (아래 format_holding_report, format_signal_report 등 기존 함수들은 100% 그대로 유지)
