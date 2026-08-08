import logging
import html

_logger = logging.getLogger(__name__)

def safe_html(text) -> str:
    """Telegram HTML 파싱 에러( <, >, & 등 ) 방지를 위한 텍스트 이스케이프"""
    if not text: return ""
    return html.escape(str(text))

def format_market_report(stats: dict) -> str:
    state = stats.get('state', 'UNKNOWN')
    scan_status = "✅ 허용" if stats.get("allow_scan") else "🚫 차단"

    msg = f"=== 📊 [1/5] MARKET ===\n"
    msg += f"신규 추천 게이트 : <b>{scan_status}</b>\n"
    msg += f"시장 국면 : {safe_html(state)} ({stats.get('score')}점)\n"
    msg += f"KOSPI : {stats.get('kospi_1d')}% | KOSDAQ: {stats.get('kosdaq_1d')}%\n"
    msg += f"Breadth (상승비율) : {stats.get('advance_ratio')}%\n"
    
    warning = stats.get("warning", "")
    if warning: msg += f"⚠️ {safe_html(warning)}\n"
    return msg + "\n"

def format_holding_report(holding_evals: list) -> str:
    msg = "=== 💼 [2/5] HOLDINGS ===\n"
    if not holding_evals:
        return msg + "보유 종목 없음\n\n"
        
    lines = []
    for i, item in enumerate(holding_evals, 1):
        name = safe_html(item.get("name", "Unknown"))
        current_price = item.get("current_price", 0)
        entry_price = item.get("entry_price", 0)
        highest_price = item.get("highest_price", current_price)
        rtn = item.get("return_rate", 0.0)
        
        action = item.get("action", "HOLD")
        data_status = item.get("data_status", "")
        
        circle_num = chr(0x2460 + i - 1) if 1 <= i <= 20 else f"{i}."
        
        if data_status == "MISSING" or action == "DATA_MISSING":
            lines.append(f"{circle_num} <b>{name}</b>\n   현재가 : 조회 실패\n   판정   : ⚠️ DATA_MISSING (데이터 누락/판정 보류)\n")
        elif action == "EXIT":
            # [핵심 수술] 엔진이 주지 않은 사유를 지어내지 않음 (데이터 계약 준수)
            reason = item.get("exit_reason")
            if reason:
                lines.append(f"{circle_num} <b>{name}</b> (수익률: {rtn:.2f}%)\n   현재가 : {current_price:,}원 (매입가: {entry_price:,}원)\n   판정   : 🔴 <b>EXIT</b>\n   사유   : {safe_html(reason)}\n")
            else:
                lines.append(f"{circle_num} <b>{name}</b> (수익률: {rtn:.2f}%)\n   현재가 : {current_price:,}원 (매입가: {entry_price:,}원)\n   판정   : 🔴 <b>EXIT</b>\n   사유   : ⚠️ 판정 근거 미전달 (데이터 계약 위반)\n")
        else:
            lines.append(f"{circle_num} <b>{name}</b> (수익률: {rtn:.2f}%)\n   현재가 : {current_price:,}원 (고점: {highest_price:,}원)\n   판정   : ✅ HOLD\n")
            
    return msg + "\n".join(lines)

def format_scanner_health(telemetry: dict) -> str:
    """정상 시 축소 출력, 장애 시 경고 노출 (Advisor 관점)"""
    is_ran = telemetry.get("is_ran", False)
    if not is_ran:
        return "=== 🔬 [3/5] SCANNER ALERT ===\n스캐너 : ❌ FAILED (데이터 파이프라인 장애)\n\n"
        
    fetch_fail = telemetry.get('fetch_fail', 0)
    if fetch_fail > 10:
        msg = "=== 🔬 [3/5] SCANNER WARNING ===\n"
        msg += f"탐색 Universe : {telemetry.get('total_universe', 0):,}개\n"
        msg += f"FDR Fetch 실패 : {fetch_fail}건 (네트워크 불안정 의심)\n"
        msg += f"Feature 통과   : {telemetry.get('feature_pass', 0)}개\n\n"
        return msg
    
    return f"=== 🔬 [3/5] SCANNER HEALTH ===\n스캐너 : ✅ 정상 (스캔 {telemetry.get('total_universe', 0):,}개 ➡️ 통과 {telemetry.get('feature_pass', 0)}개)\n\n"

def format_decision_report(signal_stats: dict) -> str:
    scanner_ran = signal_stats.get("scanner_ran", False)
    engine_ran = signal_stats.get("engine_ran", False)
    engine_error = signal_stats.get("engine_error", False)
    level_counts = signal_stats.get("level_counts", {})
    
    msg = "=== 🧠 [4/5] DECISION ENGINE ===\n"
    
    if engine_error:
        msg += "상태 : ❌ ERROR\n사유 : Runtime Exception\n\n"
        return msg
    elif not scanner_ran:
        msg += "상태 : ⚠️ NOT_RUN\n사유 : Scanner FAILURE\n\n"
        return msg
    elif not engine_ran:
        msg += f"상태 : ⚠️ SKIPPED\n사유 : Scanner Feature 0건\n\n"
        return msg
        
    msg += "상태 : ✅ SUCCESS\n\n[후보 등급 분포]\n"
    display_order = ["LEVEL 3", "LEVEL 2", "LEVEL 1", "WATCH A", "WATCH B", "WATCH C", "HOLD", "REDUCE", "EXIT", "GATED"]
    
    has_data = False
    for lvl in display_order:
        count = level_counts.get(lvl, 0)
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
    
    msg = "=== 🎯 [5/5] NEW RECOMMENDATIONS ===\n"
    
    if engine_error:
        msg += "🚫 <b>신규 매수 추천 없음</b>\n사유 : 판정 엔진 런타임 에러\n"
        return msg
    elif not engine_ran:
        msg += "🚫 <b>신규 매수 추천 없음</b>\n사유 : 스캐너 통과 후보 0건\n"
        return msg
    elif not gate_open:
        msg += "🚫 <b>신규 매수 추천 없음</b>\n사유 : 시장 추천 게이트 차단 (관망 국면)\n"
        return msg
    elif engine_buy_blocked:
        msg += f"🚫 <b>신규 매수 추천 없음</b>\n사유 : {block_reason} (엔진 방어/계좌위험 로직 작동)\n"
        return msg
    elif len(actual_signals) == 0:
        msg += "🚫 <b>신규 매수 추천 없음</b>\n사유 : 최우선 매수 등급(LEVEL 1~3) 기준 충족 종목 없음\n"
        return msg

    msg += f"<b>신규 매수 추천 : {len(actual_signals)}종목</b>\n\n"
    
    for i, sig in enumerate(actual_signals, 1):
        name = safe_html(sig.get("name", "Unknown"))
        price = sig.get("price", 0)
        chg = sig.get("chg", 0.0)
        
        decision = sig.get("decision", {})
        plan = sig.get("plan", {})
        sizing = plan.get("sizing", {})
        
        level = safe_html(decision.get("level", "N/A"))
        score = decision.get("final_score", 0.0)
        win_rate = decision.get("bayesian_win_rate", 0.0) * 100.0
        
        strats = sig.get("strategies", [])
        strat_str = ", ".join([safe_html(s) for s in strats]) if strats else "일반"
        
        entry = plan.get("entry", price)
        stop_loss = plan.get("stop_loss", 0)
        target1 = plan.get("target1", 0)
        target2 = plan.get("target2", 0)
        rr1 = plan.get("rr1", 0.0)
        rr2 = plan.get("rr2", 0.0)
        
        # [핵심] EV 포맷팅 방어 (+0.42R / -0.12R 명확히 표시)
        ev_val = sizing.get("ev", 0.0)
        
        circle_num = chr(0x2460 + i - 1) if 1 <= i <= 20 else f"{i}."
        
        msg += f"{circle_num} <b>{name}</b> (현재가: {price:,}원 / {chg}%)\n"
        msg += f"   • 등급/점수 : <b>{level}</b> ({score}점)\n"
        msg += f"   • 적용전략  : {strat_str}\n"
        msg += f"   • 예상승률  : {win_rate:.1f}% | EV: {ev_val:+.2f}R\n"
        msg += f"   -----------------------------------\n"
        msg += f"   📍 권장진입 : {entry:,}원\n"
        
        stop_pct = ((entry - stop_loss) / entry * 100) if entry > 0 else 0.0
        msg += f"   🛑 손절기준 : {stop_loss:,}원 (-{stop_pct:.1f}%)\n"
        msg += f"   🎯 1차목표  : {target1:,}원 (RR {rr1:.2f})\n"
        msg += f"   🎯 2차목표  : {target2:,}원 (RR {rr2:.2f})\n\n"
            
    return msg
