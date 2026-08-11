import os
import json
import logging

_logger = logging.getLogger(__name__)

def load_holdings(filepath: str = "holdings.json") -> list:
    """
    보유 종목 데이터(holdings.json)를 안전하게 로드합니다.
    """
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _logger.error(f"Failed to load holdings from {filepath}: {e}")
        return []

def evaluate_holdings(holdings_data: list, price_cache: dict) -> list:
    """
    보유 종목의 현재가 갱신 및 수익률, EXIT/HOLD 여부를 평가합니다.
    (데이터 누락 시 가짜 HOLD를 막기 위해 DATA_MISSING 처리)
    """
    results = []
    
    for h in holdings_data:
        code = h.get("code")
        entry_price = float(h.get("entry_price", 0.0))
        
        # 1. price_cache에서 현재가 확인
        cache_hit = price_cache.get(code)
        
        if not cache_hit:
            # [핵심] 시세 데이터가 없으면 가짜 0% HOLD를 막기 위해 즉시 DATA_MISSING 판정
            _logger.warning(f"[{h.get('name')}] 시세 캐시 누락. DATA_MISSING 처리 (오판 방지).")
            
            h["action"] = "DATA_MISSING"
            # 현재가를 이전 가격(없으면 진입가)으로 임시 셋팅하여 구조 붕괴 방지
            current_price = float(h.get("current_price", entry_price))
            h["current_price"] = current_price
            h["return_rate"] = (current_price / entry_price - 1) * 100 if entry_price > 0 else 0.0
            
            results.append(h)
            continue  # 일반적인 EXIT/HOLD 평가 로직 건너뜀
            
        # 2. 정상적으로 시세를 가져온 경우
        current_price = float(cache_hit["price"])
        h["current_price"] = current_price
        h["return_rate"] = (current_price / entry_price - 1) * 100 if entry_price > 0 else 0.0
        
        # 최고가(highest_price) 갱신 로직
        highest_price = float(h.get("highest_price", entry_price))
        if current_price > highest_price:
            highest_price = current_price
            h["highest_price"] = highest_price
            
        # 3. Trailing Stop 및 손절 평가 로직
        action = "HOLD"
        exit_reason = ""  # [수술 2순위] 텔레그램 전달용 사유 변수 초기화
        
        # 동적/절대 손절 기준선 가져오기 (기본값 세팅)
        loss_limit = float(h.get("loss_limit", -10.0))       # 절대 손절선
        trailing_limit = float(h.get("trailing_limit", -15.0)) # 고점 대비 하락선
        
        drawdown_from_high = (current_price / highest_price - 1) * 100 if highest_price > 0 else 0.0
        
        # [수술 2순위] 로깅과 동시에 exit_reason 문자열 명시적 생성
        if h["return_rate"] <= loss_limit:
            action = "EXIT"
            exit_reason = f"절대 손절선({loss_limit}%) 이탈"
            _logger.info(f"[{h.get('name')}] {exit_reason}: EXIT")
        elif drawdown_from_high <= trailing_limit:
            action = "EXIT"
            exit_reason = f"고점 대비 트레일링 스탑({trailing_limit}%) 이탈"
            _logger.info(f"[{h.get('name')}] {exit_reason}: EXIT")
            
        h["action"] = action
        # 텔레그램 포맷터가 읽을 수 있도록 딕셔너리에 데이터 주입
        if exit_reason:
            h["exit_reason"] = exit_reason 
            
        results.append(h)
        
    return results
