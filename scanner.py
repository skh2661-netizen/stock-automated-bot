import os
import time
import logging
import datetime
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED

import numpy as np
import pandas as pd
import FinanceDataReader as fdr
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =========================================================
# 1. Configuration 
# =========================================================
@dataclass
class ScannerConfig:
    MAX_WORKERS: int = min(8, (os.cpu_count() or 2) * 2)
    FETCH_TIMEOUT: float = 10.0
    MIN_CANDLES: int = 60
    
    MIN_PRICE: int = 1000
    MAX_PRICE: int = 500000
    MIN_VOLUME: int = 100000
    
    MAX_AWAY_FROM_20MA: float = 0.15
    VOL_BREAKOUT_MULTIPLIER: float = 2.0
    
CONFIG = ScannerConfig()

class ContextAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[{self.extra['ctx']}] {msg}", kwargs

_logger = ContextAdapter(logging.getLogger(__name__), {'ctx': 'SCAN'})

_GLOBAL_ADAPTER = HTTPAdapter(
    pool_connections=CONFIG.MAX_WORKERS, pool_maxsize=CONFIG.MAX_WORKERS, 
    max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
)

def _get_fdr_data_safe(symbol: str, start_date: str) -> Optional[pd.DataFrame]:
    try:
        df = fdr.DataReader(symbol, start_date)
        if df is None or df.empty or len(df) < CONFIG.MIN_CANDLES:
            return None
        return df
    except Exception as e:
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug("Fetch failed for %s: %s", symbol, e)
        return None

# =========================================================
# 2. Stage 1 & 2: Hard Filter & Metrics Generation
# =========================================================
def evaluate_stock(symbol: str, name: str, market_ctx: Dict) -> Optional[Dict[str, Any]]:
    """조건을 검사하고 통과한 종목의 순수 지표(Metrics)만 반환"""
    st = time.time()
    start_date = (datetime.datetime.now() - datetime.timedelta(days=120)).strftime("%Y-%m-%d")
    
    df = _get_fdr_data_safe(symbol, start_date)
    if df is None: return None
    
    try:
        close = df['Close'].values
        volume = df['Volume'].values
        
        current_price = close[-1]
        current_vol = volume[-1]
        
        # Hard Filter 1: 기초 요건
        if not (CONFIG.MIN_PRICE <= current_price <= CONFIG.MAX_PRICE): return None
        if current_vol < CONFIG.MIN_VOLUME: return None
        
        # 이동평균 계산
        ma5 = np.mean(close[-5:])
        ma20 = np.mean(close[-20:])
        ma60 = np.mean(close[-60:])
        vol_ma5 = np.mean(volume[-6:-1]) if len(volume) > 6 else np.mean(volume[-5:])
        
        # Hard Filter 2: 정배열 및 이격도
        if ma20 < ma60: return None
        away_from_20ma = (current_price - ma20) / ma20
        if away_from_20ma > CONFIG.MAX_AWAY_FROM_20MA: return None 
            
        # Hard Filter 3: 거래량 돌파
        if current_vol < (vol_ma5 * CONFIG.VOL_BREAKOUT_MULTIPLIER): return None
        
        # 동적 필터링 (CAUTION 상태)
        mkt_state = market_ctx.get("state", "INVALID")
        if mkt_state == "CAUTION":
            if current_vol < (vol_ma5 * 3.0): return None
            if away_from_20ma > 0.05: return None
            
        # Metrics Generation (스코어 계산 안함)
        chg = round((close[-1] / close[-2] - 1) * 100, 2) if len(close) > 1 else 0.0
        gap_pct = away_from_20ma * 100
        vol_ratio = current_vol / vol_ma5 if vol_ma5 > 0 else 0.0

        return {
            "symbol": symbol,
            "name": name,
            "price": int(current_price),
            "chg": chg,
            "ma20_gap": round(gap_pct, 2),
            "vol_ratio": round(vol_ratio, 1),
            "elapsed": round(time.time() - st, 3)
        }
    except Exception as e:
        _logger.warning("Eval error for %s: %s", symbol, e)
        return None

# =========================================================
# 3. Stage 3: Scoring & Market Multiplier
# =========================================================
def calculate_score(metrics: Dict[str, Any], mkt_state: str) -> int:
    """추출된 Metrics를 기반으로 100점 만점 Base Score 계산 후 시장 Multiplier 적용"""
    base_score = 0
    
    # Factor 1: 거래량 모멘텀 (Max 40)
    vr = metrics["vol_ratio"]
    if vr >= 4.0: base_score += 40
    elif vr >= 3.0: base_score += 30
    elif vr >= 2.0: base_score += 20
    
    # Factor 2: 가격 상승률 최적화 (Max 30) - 눌림목(-3~0%) 보상 추가
    chg = metrics["chg"]
    if 2.0 <= chg <= 6.0: base_score += 30
    elif 0.0 <= chg < 2.0: base_score += 25
    elif -3.0 <= chg < 0.0: base_score += 20  # 눌림목(음봉) 점수 부여
    elif 6.0 < chg <= 8.0: base_score += 15
    else: base_score += 0  # >8% 추격리스크, <-3% 추세이탈 간주
    
    # Factor 3: 20일선 이격 안정성 (Max 30) - 기준 강화
    abs_gap = abs(metrics["ma20_gap"])
    if abs_gap <= 3.0: base_score += 30
    elif abs_gap <= 5.0: base_score += 20
    elif abs_gap <= 8.0: base_score += 10
    else: base_score += 0  # >8%는 리스크 산정하여 0점 처리
    
    # Factor 4: Market Multiplier 적용
    multiplier = 1.0
    if mkt_state == "CAUTION":
        multiplier = 0.8
    elif mkt_state == "INVALID": 
        multiplier = 0.5  # Bypassed 겠지만 안전장치 부여
        
    return int(base_score * multiplier)

# =========================================================
# 4. Stage 4: Orchestrator & Ranking
# =========================================================
def run_scanner(market_ctx: Dict) -> List[Dict[str, Any]]:
    mkt_state = market_ctx.get("state", "NORMAL")
    _logger.info("Starting market scan. Context State: %s", mkt_state)
    
    try:
        krx = fdr.StockListing('KRX')
    except Exception as e:
        _logger.warning("KRX StockListing failed (%s). Falling back to KRX-DESC...", str(e)[:50])
        try:
            krx = fdr.StockListing('KRX-DESC')
        except Exception as e2:
            _logger.error("All StockListing fallbacks failed: %s", e2)
            return []

    try:
        krx = krx[~krx['Name'].str.contains('스팩|우$|우B|우C')]
        targets = krx[['Code', 'Name']].to_dict('records')
    except Exception as e:
        _logger.error("Failed to parse target list: %s", e)
        return []

    signals = []
    with ThreadPoolExecutor(max_workers=CONFIG.MAX_WORKERS) as executor:
        future_to_stock = {
            executor.submit(evaluate_stock, t['Code'], t['Name'], market_ctx): t for t in targets
        }
        
        done, not_done = wait(future_to_stock.keys(), timeout=120.0, return_when=ALL_COMPLETED)
        
        for f in done:
            try:
                metrics = f.result()
                if metrics:
                    # [핵심] 분리된 스코어링 모듈 호출
                    metrics["score"] = calculate_score(metrics, mkt_state)
                    signals.append(metrics)
            except Exception: pass
            
        for f in not_done:
            f.cancel()
            
    # [핵심] 스코어 기반 최종 정렬 (Ranking)
    signals.sort(key=lambda x: x['score'], reverse=True)
    
    _logger.info("Scan complete. Found %d signals.", len(signals))
    return signals
