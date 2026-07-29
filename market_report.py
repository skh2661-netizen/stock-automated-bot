import logging

_logger = logging.getLogger(__name__)

def build_market_report(market_ctx: dict) -> dict:
    """
    시장 상태(market_ctx) 딕셔너리에서 리포트 포맷팅에 필요한 핵심 지표만 추출하여 반환합니다.
    """
    return {
        "state": market_ctx.get("state", "UNKNOWN"),
        "score": market_ctx.get("score", 0),
        "reason": market_ctx.get("reason", ""),
        "kospi_1d": market_ctx.get("kospi_1d", 0.0),
        "kosdaq_1d": market_ctx.get("kosdaq_1d", 0.0),
        "total_up": market_ctx.get("total_up", 0),
        "total_down": market_ctx.get("total_down", 0),
        "total_same": market_ctx.get("total_same", 0),
        "advance_ratio": market_ctx.get("advance_ratio", 0.0),
        "source": market_ctx.get("source", "UNKNOWN"),
        "allow_scan": market_ctx.get("allow_scan", False),
        
        # [추가] 데이터 신뢰도 및 경고 필드
        "confidence": market_ctx.get("confidence", 100),
        "confidence_level": market_ctx.get("confidence_level", "HIGH"),
        "warning": market_ctx.get("warning", "")
    }
