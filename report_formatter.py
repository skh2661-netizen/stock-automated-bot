import logging
import html
from typing import Tuple, List

_logger = logging.getLogger(__name__)

def safe_html(text) -> str:
    if not text: return ""
    return html.escape(str(text))

def format_market_report(stats: dict) -> str:
    state = stats["state"]
    scan_status = "✅ 허용" if stats["allow_scan"] else "🚫 차단"

    msg = f"=== 📊 [1/5] MARKET ===\n"
    msg += f"신규 추천 게이트 : <b>{scan_status}</b>\n"
    msg += f"시장 국면 : {safe_html(state)} ({stats['score']:.0f}점)\n"
    msg += f"KOSPI : {stats['kospi_1d']}% | KOSDAQ: {stats['kosdaq_1d']}%\n"
    msg += f"Breadth (상승비율) : {stats['advance_ratio']}%\n"
    
    warning = stats["warning"] if "warning" in stats else ""
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
        name = safe_html(item["name"])
        action = item["action"]
        rtn = item["return_rate"]
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
            lines.append(f"   🟢 HOLD\n   트레일링 스탑 대기\n")
            
    return msg + "\n".join(lines)

def format_scanner_health(telemetry: dict) -> str:
    is_ran = telemetry["is_ran"]
    if not is_ran:
        return "=== 🔬 [3/5] SCANNER ALERT ===\n스캐너 : ❌ FAILED (데이터 파이프라인 장애)\n"
        
    fetch_fail = telemetry["fetch_fail"]
    if fetch_fail > 10:
        msg = "=== 🔬 [3/5] SCANNER WARNING ===\n"
        msg += f"탐색 Universe : {telemetry['total_universe']:,}개\n"
        msg += f"FDR Fetch 실패 : {fetch_fail}건 (네트워크 불안정 의심)\n"
        msg += f"Feature 통과   : {telemetry['feature_pass']}개\n"
        return msg
    
    return f"=== 🔬 [3/5] SCANNER HEALTH ===\n스캐너 : ✅ 정상 (스캔 {telemetry['total_universe']:,}개 ➡️ 통과 {telemetry['feature_pass']}개)\n"

def format_decision_report(signal_stats: dict) -> str:
    engine_status = signal_stats["engine_status"]
    
    if engine_status == "ERROR":
        return "=== 🧠 [4/5] DECISION ENGINE ===\n상태 : ❌ ERROR\n사유 : Runtime Exception\n"
    elif engine_status in ("NOT_RUN", "SKIPPED"):
        reason = safe_html(signal_stats["engine_skip_reason"])
        return f"=== 🧠 [4/5] DECISION ENGINE ===\n상태 : ⚠️ {engine_status}\n사유 : {reason}\n"
        
    msg = "=== 🧠 [4/5] DECISION ENGINE ===\n상태 : ✅ SUCCESS\n\n[후보 등급 분포]\n"
    display_order = ["LEVEL 3", "LEVEL 2", "LEVEL 1", "WATCH A", "WATCH B", "WATCH C", "HOLD", "REDUCE", "EXIT", "GATED"]
    
    has_data = False
    level_counts = signal_stats["level_counts"]
    for lvl in display_order:
        count = level_counts[lvl] if lvl in level_counts else 0
        if count > 0:
            msg += f"- {lvl:<7} : {count}건\n"
            has_data = True
            
    if not has_data:
        msg += "- 분류된 후보 없음\n"
        
    return msg

def format_promotion_blocks(signal_stats: dict) -> Tuple[str, List[str]]:
    engine_status = signal_stats["engine_status"]
    core_operational = signal_stats["core_operational"]
    engine_buy_blocked = signal_stats["engine_buy_blocked"]
    block_reason = safe_html(signal_stats["block_reason"])
    actual_signals = signal_stats["actual_signals"]
    gate_open = signal_stats["gate_open"]
    promotion_safe = signal_stats["promotion_safe"]
    
    header = "=== 🎯 [5/5] NEW RECOMMENDATIONS ===\n"
    
    if engine_status == "ERROR":
        header += "🚫 <b>신규 매수 추천 없음</b>\n사유 : 판정 엔진 런타임 에러"
        return header, []
    elif engine_status in ("NOT_RUN", "SKIPPED"):
        header += f"🚫 <b>신규 매수 추천 없음</b>\n사유 : {safe_html(signal_stats['engine_skip_reason'])}"
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

    candidate_blocks = []
    for i, sig in enumerate(actual_signals, 1):
        name = safe_html(sig["name"])
        circle_num = chr(0x2460 + i - 1) if 1 <= i <= 20 else f"{i}."
        
        block = f"{circle_num} <b>{name}</b>\n   🆕 신규 진입 후보"
        candidate_blocks.append(block)
        
    return header, candidate_blocks
