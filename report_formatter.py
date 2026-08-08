import logging
import html

_logger = logging.getLogger(__name__)

def safe_html(text) -> str:
    """Telegram HTML 파싱 에러( <, >, & 등 ) 방지를 위한 텍스트 이스케이프"""
    if not text:
        return ""
    return html.escape(str(text))

def format_market_report(stats: dict) -> str:
    state = stats.get('state', 'UNKNOWN')
    if state == 'CRASH': state_str = f"🔴 {state}"
    elif state == 'WEAK': state_str = f"🟠 {state}"
    elif state == 'CAUTION': state_str = f"🟡 {state}"
    elif state == 'NORMAL': state_str = f"🟢 {state}"
    else: state_str = state
    
    scan_status = "PASS" if stats.get("allow_scan") else "FAIL (신규매수 차단)"

    msg = f"=== 📊 [1/5] MARKET ===\n"
    msg += f"시장 검증 : {scan_status}\n"
    msg += f"시장 국면 : {state_str} (강도: {stats.get('score')}점)\n"
    msg += f"KOSPI     : {stats.get('kospi_1d')}% | KOSDAQ: {stats.get('kosdaq_1d')}%\n"
    msg += f"Breadth   : {stats.get('advance_ratio')}%\n"
    msg += f"사유      : {safe_html(stats.get('reason'))}\n"
    msg += f"출처      : {safe_html(stats.get('source', '알수없음'))}\n"
    
    warning = stats.get("warning", "")
    if warning:
        msg += f"\n⚠️ {safe_html(warning)}\n"
        
    return msg + "\n"

def format_holding_report(holding_evals: list) -> str:
    msg = "=== 💼 [2/5] HOLDINGS ===\n"
    if not holding_evals:
        return msg + "보유 종목이 없습니다.\n\n"
        
    lines = []
    for i, item in enumerate(holding_evals, 1):
        name = safe_html(item.get("name", "Unknown"))
        rtn = item.get("return_rate", item.get("profit_rate", 0.0))
        action = item.get("action", "HOLD")
        data_status = item.get("data_status", "")
        
        if data_status == "MISSING" or action == "DATA_MISSING":
            lines.append(f"{i}. {name} | ❓ 가격조회실패 (데이터 누락)")
        elif action == "EXIT":
            reason = safe_html(item.get("exit_reason", ""))
            reason_str = f" ({reason})" if reason else ""
            lines.append(f"{i}. {name} ({rtn:.2f}%) | 🔴 EXIT{reason_str}")
        else:
            lines.append(f"{i}. {name} ({rtn:.2f}%) | ✅ {action}")
            
    return msg + "\n".join(lines) + "\n\n"

def format_scanner_health(telemetry: dict) -> str:
    msg = "=== 🔬 [3/5] SCANNER HEALTH ===\n"
    
    if not telemetry.get("is_ran", False):
        return msg + "스캐너 : ❌ FAILED (데이터 파이프라인 장애)\n\n"
        
    msg += "스캐너 : ✅ SUCCESS\n\n"
    msg += f"Universe     : {telemetry.get('total_universe', 0):,}\n"
    msg += f"Pre-filter   : {telemetry.get('prefilter_pass', 0):,}\n"
    
    rejects = telemetry.get('rejects', {})
    fetch_fail = telemetry.get('fetch_fail', 0)
    feature_pass = telemetry.get('feature_pass', 0)
    
    msg += f"Fetch Fail   : {fetch_fail:,}\n"
    msg += f"Feature PASS : {feature_pass:,}\n\n"
    
    critical_reasons = {k: v for k, v in rejects.items() if k not in ["PASS", "PREFILTER_DROP", "FETCH_FAIL"] and v > 0}
    if critical_reasons:
        msg += "[주요 탈락 사유]\n"
        sorted_reasons = sorted(critical_reasons.items(), key=lambda item: item[1], reverse=True)
        for reason, count in sorted_reasons[:5]:
            msg += f"- {safe_html(reason):<14}: {count:,}\n"
            
    return msg + "\n"

def format_decision_report(signal_stats: dict) -> str:
    scanner_ran = signal_stats.get("scanner_ran", False)
    engine_ran = signal_stats.get("engine_ran", False)
    engine_error = signal_stats.get("engine_error", False)
    features_count = signal_stats.get("features_count", 0)
    level_counts = signal_stats.get("level_counts", {})
    
    msg = "=== 🧠 [4/5] DECISION ENGINE ===\n"
    
    # 4분할 엔진 상태 명시
    if engine_error:
        msg += "상태 : ❌ ERROR\n사유 : Runtime Exception\n\n"
    elif not scanner_ran:
        msg += "상태 : ⚠️ NOT_RUN\n사유 : Scanner FAILURE\n\n"
    elif not engine_ran:
        msg += f"상태 : ⚠️ SKIPPED\n사유 : Scanner Feature 0건\n\n"
    else:
        msg += "상태 : ✅ SUCCESS\n\n"
        
    msg += "[후보 등급 분포]\n"
    display_order = ["LEVEL 3", "LEVEL 2", "LEVEL 1", "WATCH A", "WATCH B", "WATCH C", "HOLD", "REDUCE", "EXIT", "GATED"]
    
    has_data = False
    for lvl in display_order:
        count = level_counts.get(lvl, 0)
        # [핵심] 0건인 항목은 밀도를 위해 숨김
        if count > 0:
            msg += f"- {lvl:<7} : {count}건\n"
            has_data = True
            
    if not has_data:
        msg += "- 분류된 후보 없음\n"
        
    return msg + "\n"

def format_promotion_report(signal_stats: dict) -> str:
    gate_open = signal_stats.get("gate_open", False)
    engine_ran = signal_stats.get("engine_ran", False)
    engine_error = signal_stats.get("engine_error", False)
    engine_buy_blocked = signal_stats.get("engine_buy_blocked", False)
    block_reason = safe_html(signal_stats.get("block_reason", ""))
    
    actual_signals = signal_stats.get("actual_signals", [])
    shadow_candidates = signal_stats.get("shadow_candidates", [])
    
    msg = "=== 🎯 [5/5] PROMOTION ===\n"
    
    # 관제 상태표시
    msg += f"Market Gate  : {'✅ OPEN' if gate_open else '❌ BLOCKED'}\n"
    
    if engine_error: dec_state = "❌ ERROR"
    elif not engine_ran: dec_state = "⚠️ SKIPPED"
    else: dec_state = "✅ SUCCESS"
    msg += f"Decision     : {dec_state}\n"
    
    block_str = "❌ BLOCKED" if engine_buy_blocked else "✅ PASS"
    if engine_buy_blocked and block_reason:
        block_str += f" ({block_reason})"
    msg += f"Engine Block : {block_str}\n\n"
    
    # 매수 승격 카운트 표시
    msg += f"Shadow Candidates : {len(shadow_candidates)}건\n"
    msg += f"Actual Buy Signal : {len(actual_signals)}건\n\n"
    
    # [핵심] 명확한 승격 차단 우선순위 노출 방어
    if engine_error:
        msg += "⚠️ 승격 차단됨 : 시스템 예외 (ENGINE ERROR)\n"
    elif not engine_ran:
        msg += "⚠️ 승격 차단됨 : 엔진 미실행 (FEATURE 0건 / SCANNER 실패)\n"
    elif not gate_open:
        msg += "⚠️ 승격 차단됨 : 시장 게이트 차단 (MARKET BLOCKED)\n"
    elif engine_buy_blocked:
        msg += f"⚠️ 승격 차단됨 : 엔진 방어 로직 작동 (ENGINE BLOCKED)\n"
    elif len(actual_signals) == 0:
        msg += "✅ 승격 게이트 통과 : 단, 최우선 매수 등급(LEVEL 1~3) 종목 없음\n"
    else:
        msg += "🚀 [실제 매수 추천 종목]\n"
        for i, sig in enumerate(actual_signals, 1):
            name = safe_html(sig.get("name", "Unknown"))
            chg = sig.get("chg", 0.0)
            decision = sig.get("decision", {})
            score = decision.get("final_score", 0.0)
            level = safe_html(decision.get("level", "N/A"))
            
            # 원형 기호 매핑 (0x2460부터 1번)
            circle_num = chr(0x2460 + i - 1) if 1 <= i <= 20 else f"{i}."
            msg += f"{circle_num} {name} ({chg}%)\n"
            msg += f"   점수: {score} | 등급: {level}\n\n"
            
    return msg
