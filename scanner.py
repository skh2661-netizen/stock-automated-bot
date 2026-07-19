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
    
    # 기본 스캔 조건
    MIN_PRICE: int = 1000
    MAX_PRICE: int = 500000
    MIN_VOLUME: int = 100000
    
    # [핵심] 추격매수 방지 (Anti-Chasing) 및 돌파 조건
    MAX_AWAY_FROM_20MA: float = 0.15  # 20일선 대비 15% 이상 급등한 종목은 제외 (고점 추격매수 방지)
    VOL_BREAKOUT_MULTIPLIER: float = 2.0  # 5일 평균 거래량 대비 200% 이상 터진 종목
    
CONFIG = ScannerConfig()

class ContextAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[{self.extra['ctx']}] {msg}", kwargs

_logger = ContextAdapter(logging.getLogger(__name__), {'ctx': 'SCAN'})

# =========================================================
# 2. Session & Network
# =========================================================
_GLOBAL_ADAPTER = HTTPAdapter(
    pool_connections=CONFIG.MAX_WORKERS, pool_maxsize=CONFIG.MAX_WORKERS, 
    max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
)

def _get_fdr_data_safe(symbol: str, start_date: str) -> Optional[pd.DataFrame]:
    """네트워크 예외를 삼키고 DataFrame 반환 (Thread 안전)"""
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
# 3. Strategy Core (시장 상태 연동형 타점 분석)
# =========================================================
def evaluate_stock(symbol: str, name: str, market_ctx: Dict) -> Optional[Dict[str, Any]]:
    st = time.time()
    start_date = (datetime.datetime.now() - datetime.timedelta(days=120)).strftime("%Y-%m-%d")
    
    df = _get_fdr_data_safe(symbol, start_date)
    if df is None: return None
    
    try:
        close = df['Close'].values
        volume = df['Volume'].values
        
        current_price = close[-1]
        current_vol = volume[-1]
        
        # 1. 기초 필터링 (동전주, 우선주, 거래량 부족 컷)
        if not (CONFIG.MIN_PRICE <= current_price <= CONFIG.MAX_PRICE): return None
        if current_vol < CONFIG.MIN_VOLUME: return None
        
        # 2. 이동평균선 계산
        ma5 = np.mean(close[-5:])
        ma20 = np.mean(close[-20:])
        ma60 = np.mean(close[-60:])
        vol_ma5 = np.mean(volume[-6:-1]) if len(volume) > 6 else np.mean(volume[-5:])
        
        # 3. 정배열 확인 (20MA > 60MA)
        if ma20 < ma60: return None
        
        # 4. [핵심] 추격매수 방지 (이격도 체크)
        away_from_20ma = (current_price - ma20) / ma20
        if away_from_20ma > CONFIG.MAX_AWAY_FROM_20MA:
            return None # 20일선 기준 너무 높게 떴으면 포기 (추격매수 금지)
            
        # 5. 거래량 돌파 확인
        if current_vol < (vol_ma5 * CONFIG.VOL_BREAKOUT_MULTIPLIER): return None
        
        # 6. 시장 상태(Market Context)에 따른 동적 필터링
        mkt_state = market_ctx.get("state", "INVALID")
        if mkt_state == "CAUTION":
            # 시장이 불안정할 때는 조건을 훨씬 까다롭게 (거래량 3배 이상, 20일선 이격도 5% 이내)
            if current_vol < (vol_ma5 * 3.0): return None
            if away_from_20ma > 0.05: return None
            
        # 모든 관문 통과 시 시그널 생성
        return {
            "symbol": symbol,
            "name": name,
            "price": int(current_price),
            "ma20_gap": round(away_from_20ma * 100, 2),
            "vol_ratio": round(current_vol / vol_ma5, 1) if vol_ma5 > 0 else 0,
            "elapsed": round(time.time() - st, 3)
        }
    except Exception as e:
        _logger.warning("Eval error for %s: %s", symbol, e)
        return None

# =========================================================
# 4. Scanner Orchestrator
# =========================================================
def run_scanner(market_ctx: Dict) -> List[Dict[str, Any]]:
    _logger.info("Starting market scan. Context State: %s", market_ctx.get("state"))
    
    # 1. 대상 종목 리스트 확보 (FDR 활용)
    try:
        krx = fdr.StockListing('KRX')
        # 우선주, 스팩 등 제외 로직 (간단 구현)
        krx = krx[~krx['Name'].str.contains('스팩|우$|우B|우C')]
        targets = krx[['Code', 'Name']].to_dict('records')
    except Exception as e:
        _logger.error("Failed to fetch target list: %s", e)
        return []

    # 2. 병렬 스캐닝 파이프라인
    signals = []
    with ThreadPoolExecutor(max_workers=CONFIG.MAX_WORKERS) as executor:
        future_to_stock = {
            executor.submit(evaluate_stock, t['Code'], t['Name'], market_ctx): t for t in targets
        }
        
        done, not_done = wait(future_to_stock.keys(), timeout=120.0, return_when=ALL_COMPLETED)
        
        for f in done:
            try:
                res = f.result()
                if res: signals.append(res)
            except Exception: pass
            
        for f in not_done:
            f.cancel()
            
    # 3. 점수(돌파 강도) 기반 정렬
    signals.sort(key=lambda x: x['vol_ratio'], reverse=True)
    
    _logger.info("Scan complete. Found %d signals.", len(signals))
    return signals
