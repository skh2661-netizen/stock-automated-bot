import json
import logging
import datetime
from typing import List, Dict, Any

_logger = logging.getLogger(__name__)


def load_holdings(filepath: str = "holdings.json") -> List[Dict[str, Any]]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        _logger.warning("holdings.json not found. Returning empty list.")
        return []
    except Exception as e:
        _logger.error("Failed to load holdings: %s", e)
        return []


def evaluate_holdings(holdings: List[Dict[str, Any]], price_cache: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    [수정 이력]
    기존 코드는 scanner가 만든 features_map(CandidateFeature)이 있을 때만
    generate_trade_plan(cf, strats, bayesian_win_rate, sys_state, ...)을 호출해야 하는데
    인자를 2개(cf, strategies)만 넘겨서 TypeError로 크래시가 났었다.
    (보유 종목이 스캐너 통과 목록에 있는 날에만 재현되는 간헐적 버그)

    price_cache(당일 시세 스냅샷)만으로는 ATR/피벗 등 generate_trade_plan에
    필요한 정보가 없으므로, 여기서는 트레이드플랜을 다시 계산하지 않고
    holdings.json에 저장돼 있던 손절/목표가를 그대로 이어서 쓰고,
    없으면(최초 1회) 진입가 기준 기본값으로 초기화한다.
    출력 스키마는 report_formatter.format_holding_report()가 기대하는
    'pnl' / 'judgment' 키로 통일했다.
    """
    evaluated = []
    today = str(datetime.date.today())

    for h in holdings:
        code = h.get("code")
        entry_price = h.get("entry_price", 0)
        quantity = h.get("quantity", 0)
        entry_date_str = h.get("entry_date", today)

        stop_loss = h.get("stop_loss", round(entry_price * 0.9))
        target1 = h.get("target1", round(entry_price * 1.1))
        target2 = h.get("target2", round(entry_price * 1.2))
        highest_price = h.get("highest_price", entry_price)

        cache_hit = price_cache.get(code)
        if cache_hit and cache_hit.get("price", 0) > 0:
            current_price = cache_hit["price"]
        else:
            # 캐시에 없으면(상장폐지/코드 오류 등) 마지막으로 알던 현재가 유지, 없으면 진입가
            current_price = h.get("current_price", entry_price)
            _logger.warning("Price cache miss for holding %s(%s), keeping last known price.", code, h.get("name"))

        if entry_price > 0 and current_price > highest_price:
            highest_price = current_price

        pnl = round(((current_price / entry_price) - 1) * 100, 2) if entry_price > 0 else 0.0

        judgment = "HOLD"
        if current_price <= stop_loss:
            judgment = "EXIT"
        elif pnl >= 15.0 or current_price >= target2:
            judgment = "SELL"
        elif pnl >= 7.0 and current_price >= target1:
            judgment = "REDUCE"

        evaluated.append({
            "code": code,
            "name": h.get("name", "Unknown"),
            "entry_price": entry_price,
            "current_price": current_price,
            "quantity": quantity,
            "entry_date": entry_date_str,
            "pnl": pnl,
            "stop_loss": stop_loss,
            "target1": target1,
            "target2": target2,
            "highest_price": highest_price,
            "strategy": h.get("strategy", "추세매매"),
            "entry_level": h.get("entry_level", "LEVEL 3"),
            "judgment": judgment,
        })

    return evaluated
