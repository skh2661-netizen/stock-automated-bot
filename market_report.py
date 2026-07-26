from typing import Dict, Any

def build_market_report(market_ctx: Dict[str, Any]) -> Dict[str, Any]:
    # 중첩된(nested) 딕셔너리 조회를 제거하고, market_ctx에서 직접 가져옴
    total_up = market_ctx.get("total_up", 0)
    total_down = market_ctx.get("total_down", 0)
    total_same = market_ctx.get("total_same", 0)
    advance_ratio = market_ctx.get("advance_ratio", 0.0)
    
    return {
        "state": market_ctx.get("state", "UNKNOWN"),
        "score": market_ctx.get("score", 0),
        "reason": market_ctx.get("reason", "N/A"),
        "kospi_1d": market_ctx.get("kospi_1d", 0.0),
        "kosdaq_1d": market_ctx.get("kosdaq_1d", 0.0),
        "total_up": total_up,
        "total_down": total_down,
        "total_same": total_same,
        "advance_ratio": advance_ratio,
        "source": market_ctx.get("source", "NONE"),
        "allow_scan": market_ctx.get("allow_scan", False)
    }
