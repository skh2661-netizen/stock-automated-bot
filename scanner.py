import os
import time
import logging
import datetime
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import pandas_ta as ta
import FinanceDataReader as fdr

from models import CandidateFeature, PriceStructure, PricePattern, Volatility, Momentum, VolumeFlow

@dataclass
class ScannerConfig:
    MAX_WORKERS: int = 8  
    CHUNK_SIZE: int = 100  
    MIN_CANDLES: int = 250  
    MIN_PRICE: int = 1000
    MAX_PRICE: int = 500000
    MIN_VOLUME: int = 100000
    
CONFIG = ScannerConfig()
_logger = logging.getLogger(__name__)

def _get_fdr_data_safe(symbol: str, start_date: str) -> Optional[pd.DataFrame]:
    try:
        df = fdr.DataReader(symbol, start_date)
        if df is None or df.empty or len(df) < 60:  
            return None
        return df
    except Exception:
        return None

def build_candidate_feature(symbol: str, name: str, market_str: str, market_returns: Dict[str, Dict[str, float]]) -> Optional[CandidateFeature]:
    start_date = (datetime.datetime.now() - datetime.timedelta(days=400)).strftime("%Y-%m-%d")
    df = _get_fdr_data_safe(symbol, start_date)
    if df is None: return None
    
    try:
        close, volume, low, high, open_p = df['Close'], df['Volume'], df['Low'], df['High'], df['Open']
        current_price, current_vol = close.iloc[-1], volume.iloc[-1]
        
        if not (CONFIG.MIN_PRICE <= current_price <= CONFIG.MAX_PRICE): return None
        if current_vol < CONFIG.MIN_VOLUME: return None
        
        chg = round((current_price / close.iloc[-2] - 1) * 100, 2) if len(close) > 1 else 0.0
        
        # [핵심 수정] Relative Volume (5일 -> 20일 평균으로 안정화)
        vol_ma20 = np.mean(volume.iloc[-21:-1]) if len(volume) > 21 else np.mean(volume.iloc[:-1])
        if current_vol < vol_ma20 * 0.3: return None  
        relative_vol_today = current_vol / vol_ma20 if vol_ma20 > 0 else 0.0
        
        df.ta.sma(length=5, append=True)
        df.ta.sma(length=20, append=True)
        df.ta.sma(length=60, append=True)
        df.ta.atr(length=14, append=True)
        df.ta.natr(length=14, append=True)
        df.ta.mfi(length=14, append=True)
        
        ma5 = df['SMA_5'].iloc[-1]
        ma20 = df['SMA_20'].iloc[-1]
        ma60 = df['SMA_60'].iloc[-1]
        
        if current_price < ma60 * 0.85: return None  
        
        atr_col = next((c for c in df.columns if c.startswith("ATR")), None)
        natr_col = next((c for c in df.columns if c.startswith("NATR")), None)
        atr14 = df[atr_col].iloc[-1] if atr_col else 0.0
        natr14 = df[natr_col].iloc[-1] if natr_col else 0.0
        mfi14 = df['MFI_14'].iloc[-1] if 'MFI_14' in df.columns else 50.0
        
        is_trend_up = bool(ma20 > ma60)
        dist_ma20 = (current_price - ma20) / ma20 * 100 if ma20 > 0 else 0.0
        ma_gap = (ma5 - ma20) / ma20 * 100 if ma20 > 0 else 0.0
        
        def calc_ret(days): 
            idx = min(days + 1, len(close))
            return (current_price / close.iloc[-idx]) - 1 if len(close) >= idx else 0.0
        
        bm = market_returns.get(market_str, market_returns.get("KOSPI", {}))
        rs_20d = (calc_ret(20) - bm.get("20d", 0)) * 100
        rs_60d = (calc_ret(60) - bm.get("60d", 0)) * 100
        rs_120d = (calc_ret(120) - bm.get("120d", 0)) * 100
        rs_250d = (calc_ret(250) - bm.get("250d", 0)) * 100
        
        true_rs_composite = (rs_20d * 0.4) + (rs_60d * 0.3) + (rs_120d * 0.2) + (rs_250d * 0.1)
        
        vr_20 = np.sum(np.where(close.iloc[-20:] > close.shift(1).iloc[-20:], volume.iloc[-20:], 0)) / (np.sum(np.where(close.iloc[-20:] < close.shift(1).iloc[-20:], volume.iloc[-20:], 0)) + 1)
        
        # [핵심 수정] 1일이 아닌 20일 평균 거래대금(억원) 산출 (노이즈, 휩소 차단)
        if len(close) >= 20:
            trading_value_100m = float(np.mean(close.iloc[-20:].values * volume.iloc[-20:].values)) / 100_000_000.0
        else:
            trading_value_100m = (float(current_price) * float(current_vol)) / 100_000_000.0
        
        # [핵심 수정] Pivot 탐색 윈도우를 좌우 5봉(총 11봉)으로 넓혀 잔파도(Noise) 대신 진짜 구조적 저항선 도출
        lows, highs = low.values, high.values
        pivots = []
        for i in range(5, len(lows)-5):
            if lows[i] == np.min(lows[i-5:i+6]):
                pivots.append(lows[i])
                
        last_pivot_low = pivots[-1] if len(pivots) > 0 else 0.0
        prev_pivot_low = pivots[-2] if len(pivots) > 1 else 0.0
        
        high_pivots = []
        for i in range(5, len(highs)-5):
            if highs[i] == np.max(highs[i-5:i+6]):
                high_pivots.append(highs[i])
                
        prev_pivot_high = high_pivots[-1] if len(high_pivots) > 0 else 0.0

        high_52w = high.iloc[-250:].max() if len(high) >= 250 else high.max()
        dist_52w_high = (current_price - high_52w) / high_52w * 100 if len(high) >= 20 else -100.0
        high_stay_days = int(np.sum(close.iloc[-60:] >= high_52w * 0.90)) if len(close) > 0 else 0

        # [핵심 수정] Gap Survived: 당일 저가가 아닌, 전일 고가 위에서 종가를 마감해야 인정 (진짜 갭 유지)
        is_gap_up = low.iloc[-1] > high.iloc[-2] if len(high) > 1 else False
        gap_survived = is_gap_up and close.iloc[-1] > high.iloc[-2]
        
        body = abs(close.iloc[-1] - open_p.iloc[-1])
        lower_shadow = min(close.iloc[-1], open_p.iloc[-1]) - low.iloc[-1]
        upper_shadow = high.iloc[-1] - max(close.iloc[-1], open_p.iloc[-1])
        
        # [수정] 해머 조건 완화 (실전 반영 0.5)
        is_hammer = lower_shadow > (2 * body) and upper_shadow < (body * 0.5)
        
        recent_downtrend = close.iloc[-2] < close.iloc[-5] if len(close) > 5 else False
        near_20ma = abs(dist_ma20) < 5.0
        is_bull_engulfing = recent_downtrend and near_20ma and (close.iloc[-2] < open_p.iloc[-2]) and (close.iloc[-1] > open_p.iloc[-1]) and (open_p.iloc[-1] < close.iloc[-2]) and (close.iloc[-1] > open_p.iloc[-2]) if len(close) > 1 else False

        # [핵심 수정] 장대 윗꼬리(매도세) 감지: 고점 대비 3% 이상 밀리면 강한 저항으로 판정
        has_long_upper_shadow = ((high.iloc[-1] - close.iloc[-1]) / high.iloc[-1]) > 0.03

        atr_compression = natr14 < np.mean(df[natr_col].iloc[-60:]) if natr_col and len(df) > 60 else False

        struc = PriceStructure(prev_pivot_high, prev_pivot_low, last_pivot_low, dist_ma20, dist_52w_high, high_stay_days)
        pat = PricePattern(is_bull_engulfing, is_hammer, gap_survived, is_gap_up, has_long_upper_shadow)
        vty = Volatility(atr14, natr14, atr_compression)
        mom = Momentum(rs_20d, rs_60d, rs_120d, rs_250d, true_rs_composite, ma20, ma_gap, is_trend_up)
        vol = VolumeFlow(vr_20, mfi14, relative_vol_today, trading_value_100m)

        return CandidateFeature(symbol, name, float(current_price), chg, struc, pat, vty, mom, vol)
    except Exception as e:
        return None

def run_scanner(market_ctx: Dict) -> List[CandidateFeature]:
    _logger.info("Starting target generation with Chunking.")
    
    try:
        krx = fdr.StockListing('KRX')
    except Exception:
        try:
            krx = fdr.StockListing('KRX-DESC')
        except Exception as e2:
            _logger.error("All StockListing fallbacks failed: %s", e2)
            return []

    try:
        krx = krx[~krx['Name'].str.contains('스팩|우$|우B|우C')]
        targets = krx[['Code', 'Name', 'Market']].to_dict('records')
        _logger.info("Targeting %d stocks.", len(targets))
    except Exception as e:
        _logger.error("Failed to parse target list: %s", e)
        return []

    market_returns = {"KOSPI": {}, "KOSDAQ": {}}
    start_date = (datetime.datetime.now() - datetime.timedelta(days=400)).strftime("%Y-%m-%d")
    try:
        for mkt, sym in [("KOSPI", "KS11"), ("KOSDAQ", "KQ11")]:
            df = fdr.DataReader(sym, start_date)
            if len(df) > 0:
                c = df['Close']
                market_returns[mkt] = {
                    "20d": (c.iloc[-1] / c.iloc[-min(21, len(c))] - 1) if len(c) >= 21 else 0,
                    "60d": (c.iloc[-1] / c.iloc[-min(61, len(c))] - 1) if len(c) >= 61 else 0,
                    "120d": (c.iloc[-1] / c.iloc[-min(121, len(c))] - 1) if len(c) >= 121 else 0,
                    "250d": (c.iloc[-1] / c.iloc[-min(251, len(c))] - 1) if len(c) >= 251 else 0,
                }
    except Exception as e:
        _logger.warning("Benchmark fetch failed. RS will be absolute. %s", e)

    features_list = []
    
    for i in range(0, len(targets), CONFIG.CHUNK_SIZE):
        chunk = targets[i:i + CONFIG.CHUNK_SIZE]
        with ThreadPoolExecutor(max_workers=CONFIG.MAX_WORKERS) as executor:
            future_to_stock = {
                executor.submit(build_candidate_feature, t['Code'], t['Name'], t['Market'], market_returns): t for t in chunk
            }
            for f in as_completed(future_to_stock):
                try:
                    res = f.result(timeout=60.0)
                    if res: features_list.append(res)
                except Exception: pass
        time.sleep(0.3) 
            
    return features_list
