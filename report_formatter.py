# report_formatter.py
import logging
import html
from typing import Tuple, List

_logger = logging.getLogger(__name__)

def safe_html(text) -> str:
    if not text:
        return ""
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
    if warning:
        msg += f"⚠️ {safe_html(warning)}\n"
    return msg

def format_holding_report(holding_evals: list, success: bool = True) -> str:
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
    if engine_status != "SUCCESS":
        return "", []
    
    promotions = signal_stats.get("promotions", [])
    if not promotions:
        return "", []
        
    blocks = []
    summary_msg = f"=== 🚀 [5/5] PROMOTIONS ===\n총 {len(promotions)}건 신규 편입/승격\n"
    for item in promotions:
        code = item.get("code", "")
        name = safe_html(item.get("name", ""))
        lvl = item.get("level", "")
        entry = item.get("entry", 0)
        t1 = item.get("target1", 0)
        stop = item.get("stop_loss", 0)
        
        block = f"🔥 <b>[{lvl}] {name}</b> ({code})\n"
        block += f"• 매수가 : {entry:,}원\n"
        block += f"• 목표가 : {t1:,}원\n"
        block += f"• 손절가 : {stop:,}원"
        blocks.append(block)
        
    return summary_msg, blocks
