# report_formatter.py
import logging
import html
from typing import Tuple, List

_logger = logging.getLogger(__name__)

def safe_html(text) -> str:
    if not text: return ""
    return html.escape(str(text))

def format_market_report(stats: dict) -> str:
    state = stats.get("state", "UNKNOWN")
    scan_status = "✅ 허용" if stats.get("allow_scan") else "🚫 차단"

    msg = f"=== 📊 [1/5] MARKET ===\n"
    msg += f"신규 추천 게이트 : <b>{scan_status}</b>\n"
    msg += f"시장 국면 : {safe_html(state)} ({stats.get('score', 0):.0f}점)\n"
    msg += f"KOSPI : {stats.get('kospi_1d', 0.0)}% | KOSDAQ: {stats.get('kosdaq_1d', 0.0)}%\n"
    msg += f"Breadth (상승비율) : {stats.get('advance_ratio', 0.0)}%\n"
    
    warning = stats.get("warning", "")
    if warning: msg += f"⚠️ {safe_html(warning)}\n"
    return msg

def format_holding_report(holding_evals: list, success: bool) -> str:
    msg = "=== 💼 [2/5] HOLDINGS ===\n"
    
    if not success:
        return msg + "⚠️ 보유종목 상태 불명 (데이터 로드 실패)\n"
        
    if not holding_evals:
        return msg + "보유 종목 없음\n"
        
    lines = []
    for i, item in enumerate(holding_evals, 1):
        name = safe_html(item.get("name", "UNKNOWN"))
        action = item.get("action", "HOLD")
        rtn = item.get("return_rate", 0.0)
        circle_num = chr(0x2460 + i - 1) if 1 <= i <= 20 else f"{i}."
        
        lines.append(f"{circle_num} <b>{name}</b>")
        lines.append(f"   {rtn:+.2f}%")
        
        if action == "EXIT":
            reason = item.get("exit_reason", "판정 근거 미전달")
            lines.append(f"   🔴 EXIT\n   {safe_html(reason)}\n")
        elif action == "REDUCE":
            lines.append(f"   🟠 REDUCE\n   비중 축소 필요\n")
        elif action == "DATA_MISSING":
            lines.append(f"   ⚠️ DATA_MISSING\n   시세 확인 불가\n")
        else:
            lines.append(f"   🟢 HOLD\n   트레일링 스탑 유지\n")
            
    return msg + "\n".join(lines)

def format_scanner_health(telemetry: dict) -> str:
    is_ran = telemetry.get("is_ran", False)
    if not is_ran:
        return "=== 🔬 [3/5] SCANNER ALERT ===\n스캐너 : ❌ FAILED (데이터 파이프라인 장애)\n"
        
    fetch_fail = telemetry.get("fetch_fail", 0)
    if fetch_fail > 10:
        msg = "=== 🔬 [3/5] SCANNER WARNING ===\n"
        msg += f"탐색 Universe : {telemetry.get('total_universe', 0):,}개\n"
        msg += f"FDR Fetch 실패 : {fetch_fail}건 (네트워크 불안정 의심)\n"
        msg += f"Feature 통과   : {telemetry.get('feature_pass', 0)}개\n"
        return msg
    
    return f"=== 🔬 [3/5] SCANNER HEALTH ===\n스캐너 : ✅ 정상 (스캔 {telemetry.get('total_universe', 0):,}개 ➡️ 통과 {telemetry.get('feature_pass', 0)}개)\n"

def format_decision_report(signal_stats: dict) -> str:
    engine_status = signal_stats.get("engine_status", "UNKNOWN")
    
    if engine_status == "ERROR":
        return "=== 🧠 [4/5] DECISION ENGINE ===\n상태 : ❌ ERROR\n사유 : Runtime Exception\n"
    elif engine_status in ("NOT_RUN", "SKIPPED"):
        reason = safe_html(signal_stats.get("engine_skip_reason", "알 수 없는 사유"))
        return f"=== 🧠 [4/5] DECISION ENGINE ===\n상태 : ⚠️ {engine_status}\n사유 : {reason}\n"
        
    msg = "=== 🧠 [4/5] DECISION ENGINE ===\n상태 : ✅ SUCCESS\n\n[후보 등급 분포]\n"
    display_order = ["LEVEL 3", "LEVEL 2", "LEVEL 1", "WATCH A", "WATCH B", "WATCH C", "HOLD", "REDUCE", "EXIT", "GATED"]
    
    has_data = False
    level_counts = signal_stats.get("level_counts", {})
    for lvl in display_order:
        count = level_counts.get(lvl, 0)
        if count > 0:
            msg += f"- {lvl:<7} : {count}건\n"
            has_data = True
            
    if not has_data:
        msg += "- 분류된 후보 없음\n"
        
    return msg

def format_promotion_blocks(signal_stats: dict) -> Tuple[str, List[str]]:
    engine_status = signal_stats.get("engine_status", "UNKNOWN")
    core_operational = signal_stats.get("core_operational", False)
    engine_buy_blocked = signal_stats.get("engine_buy_blocked", True)
    block_reason = safe_html(signal_stats.get("block_reason", ""))
    actual_signals = signal_stats.get("actual_signals", [])
    gate_open = signal_stats.get("gate_open", False)
    promotion_safe = signal_stats.get("promotion_safe", False)

    header = "=== 🎯 [5/5] NEW RECOMMENDATIONS ===\n"

    # 1. 시스템 상태 방어
    if engine_status == "ERROR":
        header += "🚫 <b>신규 매수 추천 없음</b>\n사유 : 판정 엔진 런타임 에러"
        return header, []
    elif engine_status in ("NOT_RUN", "SKIPPED"):
        header += f"🚫 <b>신규 매수 추천 없음</b>\n사유 : {safe_html(signal_stats.get('engine_skip_reason', ''))}"
        return header, []
    elif not core_operational:
        header += "🚫 <b>신규 매수 추천 없음</b>\n사유 : 파이프라인 코어 상태 불명확"
        return header, []
    elif not gate_open:
        header += "🚫 <b>신규 매수 추천 없음</b>\n사유 : 시장 추천 게이트 차단 (관망 국면)"
        return header, []
    elif engine_buy_blocked:
        header += f"🚫 <b>신규 매수 추천 없음</b>\n사유 : {block_reason} (계좌위험/엔진방어 작동)"
        return header, []
    elif not promotion_safe:
        header += "🚫 <b>신규 매수 추천 없음</b>\n사유 : ⚠️ Candidate Contract Violation (신뢰성 저하 차단)"
        return header, []
    elif len(actual_signals) == 0:
        header += "🚫 <b>신규 매수 추천 없음</b>\n사유 : 매수 등급(LEVEL 1~3) 통과 종목 없음"
        return header, []

    # 2. 실제 추천 종목 출력 (decision_engine 스키마 완벽 매핑)
    candidate_blocks = []

    for i, sig in enumerate(actual_signals, 1):
        name = safe_html(sig.get("name", "UNKNOWN"))
        code = safe_html(sig.get("code", ""))
        current_price = sig.get("price", 0)
        change_pct = sig.get("chg", 0.0)

        # decision 블록
        decision = sig.get("decision", {})
        level = safe_html(decision.get("level", "UNKNOWN"))
        score = decision.get("final_score", 0.0)
        win_rate = decision.get("bayesian_win_rate", 0.0)

        strats = sig.get("strategies", [])
        strategy = safe_html(strats[0]) if strats else "일반"

        # plan 블록
        plan = sig.get("plan", {})
        entry = plan.get("entry", 0)
        stop_loss = plan.get("stop_loss", 0)
        target1 = plan.get("target1", 0)
        target2 = plan.get("target2", 0)
        rr1 = plan.get("rr1", 0.0)
        rr2 = plan.get("rr2", 0.0)

        # sizing 블록 (EV, 수량, 투자금액, 위험률)
        sizing = plan.get("sizing", {})
        ev = sizing.get("ev", 0.0)
        qty = sizing.get("qty", 0)
        amount = sizing.get("amount", 0)
        risk_pct = sizing.get("actual_risk_pct", 0.0)

        # 손절률 계산
        stop_pct = 0.0
        if entry and stop_loss and entry > 0:
            stop_pct = ((stop_loss / entry) - 1.0) * 100.0

        circle_num = chr(0x2460 + i - 1) if 1 <= i <= 20 else f"{i}."

        block = (
            f"{circle_num} <b>{name}</b> ({code})\n"
            f"   🆕 신규 진입 후보\n"
            f"   현재가 : {current_price:,.0f}원 ({change_pct:+.2f}%)\n"
            f"   • 등급/점수 : <b>{level}</b> ({score:.2f}점)\n"
            f"   • 적용전략 : {strategy}\n"
            f"   • 예상승률 : {win_rate * 100:.1f}% | EV: {ev:+.2f}R\n"
            f"   -----------------------------------\n"
            f"   📍 권장진입 : {entry:,.0f}원\n"
            f"   🛑 손절기준 : {stop_loss:,.0f}원 ({stop_pct:+.1f}%)\n"
            f"   🎯 1차목표 : {target1:,.0f}원 (RR {rr1:.2f})\n"
            f"   🎯 2차목표 : {target2:,.0f}원 (RR {rr2:.2f})\n"
            f"   -----------------------------------\n"
            f"   💼 포지션 수량 : {qty:,}주\n"
            f"   💰 투자금액 : {amount:,.0f}원\n"
            f"   ⚠️ 계좌 위험률 : {risk_pct:.2f}%"
        )
        candidate_blocks.append(block)

    return header, candidate_blocks
