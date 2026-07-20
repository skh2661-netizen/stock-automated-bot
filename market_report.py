from typing import Dict, Any

def build_market_report(market_ctx: Dict[str, Any]) -> Dict[str, Any]:
    breadth = market_ctx.get("breadth", {})
    data = breadth.get("data", {})
    
    kp_up = data.get("kp_up", 0)
    kp_down = data.get("kp_down", 0)
    kp_same = data.get("kp_same", 0)
    kd_up = data.get("kd_up", 0)
    kd_down = data.get("kd_down", 0)
    kd_same = data.get("kd_same", 0)
    
    total_up = kp_up + kd_up
    total_down = kp_down + kd_down
    total_same = kp_same + kd_same
    
    advance_ratio = round((total_up / total_down * 100), 2) if total_down > 0 else 0.0
    
    return {
        "state": market_ctx.get("state", "UNKNOWN"),
        "score": market_ctx.get("data_quality", 0),
        "reason": market_ctx.get("reason", "N/A"),
        "kospi_1d": market_ctx.get("kospi_1d", 0.0),
        "kosdaq_1d": market_ctx.get("kosdaq_1d", 0.0),
        "total_up": total_up,
        "total_down": total_down,
        "total_same": total_same,
        "advance_ratio": advance_ratio,
        "source": market_ctx.get("source", "NONE")
    }
