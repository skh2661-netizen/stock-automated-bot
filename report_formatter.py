# report_formatter.py
import logging
import html
from typing import Tuple, List, Dict, Any

_logger = logging.getLogger(__name__)

def format_market_report(m_ctx: dict) -> str:
    try:
        state = m_ctx.get("state", "UNKNOWN")
        score = m_ctx.get("score", 0.0)
        kospi = m_ctx.get("kospi_1d", 0.0)
        kosdaq = m_ctx.get("kosdaq_1d", 0.0)
        advance = m_ctx.get("advance_ratio", 0.0)
        allow_scan = m_ctx.get("allow_scan", False)

        lines = [
            "📈 <b>[시장 환경 및 상태 리포트]</b>",
            f"• 시장 상태: <b>{state}</b> (점수: {score:.1f})",
            f"• 신규 매수 허용: <b>{'허용 (GATE OPEN)' if allow_scan else '차단 (GATE CLOSED)'}</b>",
            f"• 지수 변동: KOSPI {kospi:+.2f}% | KOSDAQ {kosdaq:+.2f}%",
            f"• 상승 종목 비율: {advance:.1f}%"
        ]
        return "\n".join(lines)
    except Exception as e:
        _logger.error(f"Market report formatting failed: {e}")
        return "📈 <b>[시장 환경 및 상태 리포트]</b>\n- 데이터 포맷팅 중 오류 발생"

def format_holding_report(holdings: list) -> str:
    try:
        if not holdings:
            return "📋 <b>[보유 종목 평가 리포트]</b>\n- 현재 보유 중인 종목이 없습니다."

        lines = ["📋 <b>[보유 종목 평가 리포트]</b>"]
        for h in holdings:
            name = html.escape(str(h.get("name", "Unknown")))
            action = h.get("action", "HOLD")

            if action == "DATA_MISSING":
                data_status = html.escape(str(h.get("data_status", "가격조회실패")))
                lines.append(f"• <b>{name}</b>: <b>❓ 데이터 누락</b> ({data_status})")
                continue

            rtn = h.get("return_rate", 0.0)
            line = f"• <b>{name}</b>: 액션 <b>{action}</b> (수익률: {rtn:+.2f}%)"

            exit_reason = h.get("exit_reason", "")
            if action == "EXIT" and exit_reason:
                line += f"\n   └ 사유: {html.escape(str(exit_reason))}"

            lines.append(line)
        return "\n".join(lines)
    except Exception as e:
        _logger.error(f"Holding report formatting failed: {e}")
        return "📋 <b>[보유 종목 평가 리포트]</b>\n- 데이터 포맷팅 중 오류 발생"

def format_scanner_health(telemetry: dict) -> str:
    try:
        is_ran = telemetry.get("is_ran", False)
        if not is_ran:
            return "🔍 <b>[스캐너 헬스 리포트]</b>\n- 스캐너가 실행되지 않았습니다."

        total = telemetry.get("total_universe", 0)
        pass_cnt = telemetry.get("feature_pass", 0)
        fail_cnt = telemetry.get("fetch_fail", 0)
        active_scanned = telemetry.get("active_scanned", 0)
        active_tracked = telemetry.get("active_tracked", 0)

        lines = [
            "🔍 <b>[스캐너 헬스 리포트]</b>",
            f"• 전체 유니버스: {total}개",
            f"• 통과 후보: {pass_cnt}개 (수집 실패: {fail_cnt}개)",
            f"• 활성 종목 스캔 커버리지: {active_scanned}/{active_tracked}"
        ]
        return "\n".join(lines)
    except Exception as e:
        _logger.error(f"Scanner health report formatting failed: {e}")
        return "🔍 <b>[스캐너 헬스 리포트]</b>\n- 헬스 데이터 포맷팅 중 오류 발생"

def format_decision_report(stats: dict) -> str:
    try:
        counts = stats.get("level_counts", {})
        block_reason = stats.get("block_reason", "")
        buy_blocked = stats.get("engine_buy_blocked", True)

        lines = [
            "🤖 <b>[의사결정 엔진 리포트]</b>",
            f"• 매수 차단 여부: <b>{'차단됨' if buy_blocked else '정상'}</b>"
        ]
        if block_reason:
            lines.append(f"• 차단 사유: {html.escape(block_reason)}")

        if counts:
            level_strs = [f"{lvl}: {cnt}" for lvl, cnt in counts.items()]
            lines.append(f"• 레벨별 분포: {', '.join(level_strs)}")
        else:
            lines.append("• 레벨별 분포: 평가된 후보 없음")

        return "\n".join(lines)
    except Exception as e:
        _logger.error(f"Decision report formatting failed: {e}")
        return "🤖 <b>[의사결정 엔진 리포트]</b>\n- 엔진 리포트 포맷팅 중 오류 발생"

def format_promotion_report(stats: dict) -> str:
    try:
        promotion_state = stats.get("promotion_state", "NOT_EVALUATED")
        promotion_safe = stats.get("promotion_safe", True)
        buy_failures = stats.get("buy_contract_failures", 0)
        actual_signals = stats.get("actual_signals", [])

        status_text = "승인됨 (SAFE)" if promotion_safe else f"차단됨 (FAIL: {buy_failures}건)"

        lines = [
            "🚀 <b>[프로모션 및 최종 시그널 리포트]</b>",
            f"• 프로모션 상태: <b>{promotion_state}</b> ({status_text})",
            f"• 최종 실행 시그널 수: {len(actual_signals)}개"
        ]

        if actual_signals:
            for sig in actual_signals:
                name = html.escape(str(sig.get("name", "Unknown")))
                code = html.escape(str(sig.get("code", "")))
                decision = sig.get("decision", {})
                level = decision.get("level", "UNKNOWN")
                lines.append(f"  - [{level}] {name} ({code})")

        return "\n".join(lines)
    except Exception as e:
        _logger.error(f"Promotion report formatting failed: {e}")
        return "🚀 <b>[프로모션 및 최종 시그널 리포트]</b>\n- 프로모션 리포트 포맷팅 중 오류 발생"
