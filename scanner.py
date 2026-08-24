import os
import time
import logging
import datetime
import concurrent.futures
import multiprocessing as mp
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd
import pandas_ta as ta
import FinanceDataReader as fdr

from models import CandidateFeature, PriceStructure, PricePattern, Volatility, Momentum, VolumeFlow, RiskProfile, QuantConfig

@dataclass
class ScannerConfig:
    MAX_WORKERS: int = min(8, (os.cpu_count() or 4))
    MAX_IO_WORKERS: int = 12
    MIN_PRICE: int = 1000
    MAX_PRICE: int = 500000
    MIN_VOLUME: int = 100000
    PROCESS_TIMEOUT: float = 15.0
    PRE_FILTER_MIN_TVAL_100M: float = QuantConfig.MIN_TRADING_VALUE_100M * 0.5

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

def build_price_cache() -> Dict[str, Dict[str, Any]]:
    _logger.info("Building global price cache (KRX listing snapshot)...")
    def _try_load() -> Dict[str, Dict[str, Any]]:
        cache: Dict[str, Dict[str, Any]] = {}
        krx = fdr.StockListing('KRX')
        krx = krx[~krx['Name'].str.contains('스팩|우$|우B|우C')]
        if 'Sector' not in krx.columns:
            krx['Sector'] = krx['Market']
        krx['Sector'] = krx['Sector'].fillna(krx['Market'])
        if 'Close' in krx.columns and 'Volume' in krx.columns:
            krx['Close'] = pd.to_numeric(krx['Close'].astype(str).str.replace(',', ''), errors='coerce')
            krx['Volume'] = pd.to_numeric(krx['Volume'].astype(str).str.replace(',', ''), errors='coerce')
        for _, row in krx.iterrows():
            close = float(row['Close']) if pd.notna(row['Close']) else 0.0
            volume = float(row['Volume']) if pd.notna(row['Volume']) else 0.0
            cache[row['Code']] = {
                "name": row['Name'], 
                "market": row['Market'], 
                "sector": str(row['Sector']), 
                "price": close, 
                "volume": volume, 
                "trading_value_100m": (close * volume) / 100_000_000.0,
            }
        return cache

    cache: Dict[str, Dict[str, Any]] = {}
    for attempt in range(2):
        try:
            cache = _try_load()
            if cache:
                break
        except Exception as e:
            _logger.error("Failed to build price cache (attempt %d/2): %s", attempt + 1, e)
            if attempt == 0:
                time.sleep(5)
    _logger.info("Price cache built: %d symbols", len(cache))
    return cache

def build_candidate_feature(args: Tuple) -> Tuple[str, str, Optional[CandidateFeature], Dict[str, float]]:
    symbol, name, market_str, sector_str, market_returns, df = args
    latency = {"ta": 0.0, "total": 0.0}
    t_start = time.perf_counter()

    if df is None or df.empty:
        return symbol, "FETCH_FAIL", None, latency
    try:
        close, volume, low, high, open_p = df['Close'], df['Volume'], df['Low'], df['High'], df['Open']
        current_price, current_vol = close.iloc[-1], volume.iloc[-1]
    except (KeyError, IndexError):
        return symbol, "DATA_CORRUPT", None, latency

    if current_price <= 0 or current_vol <= 0:
        return symbol, "INVALID_DATA", None, latency
    if not (CONFIG.MIN_PRICE <= current_price <= CONFIG.MAX_PRICE):
        return symbol, "LOW_PRICE", None, latency
    if current_vol < CONFIG.MIN_VOLUME:
        return symbol, "LOW_VOL", None, latency

    trading_value_100m_today = (float(current_price) * float(current_vol)) / 100_000_000.0
    trading_value_100m_avg20 = float(np.mean(close.iloc[-20:].values * volume.iloc[-20:].values)) / 100_000_000.0 if len(close) >= 20 else trading_value_100m_today
    mixed_tval = (trading_value_100m_today * 0.7) + (trading_value_100m_avg20 * 0.3)
    if mixed_tval < QuantConfig.MIN_TRADING_VALUE_100M:
        return symbol, "LOW_TVAL", None, latency

    if len(close) >= 60:
        ma60_fast = close.iloc[-60:].mean()
        if current_price < ma60_fast * 0.90:
            return symbol, "MA60_DOWN", None, latency
    else:
        return symbol, "DATA_LACK", None, latency

    t1 = time.perf_counter()
    try:
        chg = round((current_price / close.iloc[-2] - 1) * 100, 2) if len(close) > 1 else 0.0
        vol_ma20 = np.mean(volume.iloc[-21:-1]) if len(volume) > 21 else np.mean(volume.iloc[:-1])
        if current_vol < vol_ma20 * 0.3:
            return symbol, "VOL_DRY", None, latency
        relative_vol_today = current_vol / vol_ma20 if vol_ma20 > 0 else 0.0

        ma5 = close.rolling(window=5).mean().iloc[-1]
        ma20 = close.rolling(window=20).mean().iloc[-1]
        ma60 = close.rolling(window=60).mean().iloc[-1]
        ma120 = close.rolling(window=120).mean().iloc[-1] if len(close) >= 120 else ma60

        tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
        atr14 = tr.rolling(window=14).mean().iloc[-1]
        atr14 = max(atr14, current_price * QuantConfig.ATR_MIN_PCT)
        natr14 = (atr14 / current_price) * 100

        mfi_series = df.ta.mfi(length=14)
        mfi14 = mfi_series.iloc[-1] if mfi_series is not None and not mfi_series.empty else 50.0

        if not (np.isfinite(ma20) and np.isfinite(atr14) and atr14 > 0 and ma20 > 0):
            return symbol, "INDICATOR_FAIL", None, latency

        is_trend_up = bool(ma20 > ma60)
        if len(close) >= 5:
            ma20_slope = np.polyfit(np.arange(5), close.rolling(window=20).mean().iloc[-5:].values, 1)[0]
            is_ma20_up = bool(ma20_slope > 0)
        else:
            is_ma20_up = False

        dist_ma20 = (current_price - ma20) / ma20 * 100 if ma20 > 0 else 0.0
        ma_gap = (ma5 - ma20) / ma20 * 100 if ma20 > 0 else 0.0
        atr_pct = (atr14 / current_price * 100) if current_price > 0 else 0.0
        chg_limit = max(6.0, atr_pct * 2.5)
        max_gap_allowed = min(max(3.0, atr_pct), QuantConfig.GAP_CHASE_MAX_PCT)
        return_var_20d = float(close.pct_change().iloc[-20:].var() * 252) if len(close) >= 20 else 0.0
    except Exception:
        return symbol, "TA_CALC_FAIL", None, latency

    latency["ta"] = (time.perf_counter() - t1) * 1000.0

    try:
        def calc_ret(days):
            idx = min(days + 1, len(close))
            return (current_price / close.iloc[-idx]) - 1 if len(close) >= idx else 0.0

        bm = market_returns.get(market_str, market_returns.get("KOSPI", {}))
        rs_10d = (calc_ret(10) - bm.get("10d", 0)) * 100
        rs_25d = (calc_ret(25) - bm.get("25d", 0)) * 100
        rs_60d = (calc_ret(60) - bm.get("60d", 0)) * 100
        rs_120d = (calc_ret(120) - bm.get("120d", 0)) * 100
        true_rs_composite = (rs_10d * 0.40) + (rs_25d * 0.30) + (rs_60d * 0.20) + (rs_120d * 0.10)
        if ma120 > 0 and current_price < ma120:
            true_rs_composite *= 0.5
    except Exception:
        return symbol, "RS_FAIL", None, latency

    try:
        vr_20 = np.sum(np.where(close.iloc[-20:] > close.shift(1).iloc[-20:], volume.iloc[-20:], 0)) / (np.sum(np.where(close.iloc[-20:] < close.shift(1).iloc[-20:], volume.iloc[-20:], 0)) + 1)
        is_vol_dry_up = current_vol < (vol_ma20 * 0.5)
        adr_20 = float(((high.iloc[-20:] / low.iloc[-20:]) - 1).mean() * 100) if len(high) >= 20 else 0.0
        adv_100m = float(np.mean(close.iloc[-20:].values * volume.iloc[-20:].values)) / 100_000_000.0 if len(close) >= 20 else trading_value_100m_today

        pivot_window = int(np.clip(round(8 * np.exp(-atr_pct / 10.0)) + 2, 3, 10))
        window_size = 2 * pivot_window + 1
        low_series = pd.Series(low.values)
        high_series = pd.Series(high.values)
        low_min = low_series.rolling(window_size).min()
        high_max = high_series.rolling(window_size).max()

        is_piv_low = (low_series.shift(pivot_window) == low_min) & low_min.notna()
        is_piv_high = (high_series.shift(pivot_window) == high_max) & high_max.notna()

        valid_lows_raw = low_series.shift(pivot_window)[is_piv_low].dropna()
        valid_lows = valid_lows_raw.loc[valid_lows_raw.shift() != valid_lows_raw].values
        valid_highs_raw = high_series.shift(pivot_window)[is_piv_high].dropna()
        valid_highs = valid_highs_raw.loc[valid_highs_raw.shift() != valid_highs_raw].values

        last_pivot_low = float(valid_lows[-1]) if len(valid_lows) > 0 else 0.0
        prev_pivot_low = float(valid_lows[-2]) if len(valid_lows) > 1 else 0.0
        last_pivot_high_price = float(valid_highs[-1]) if len(valid_highs) > 0 else 0.0
        prev_pivot_high_price = float(valid_highs[-2]) if len(valid_highs) > 1 else 0.0

        is_higher_high = bool(last_pivot_high_price > prev_pivot_high_price + (atr14 * QuantConfig.HH_BREAKOUT_ATR_MULT)) if prev_pivot_high_price > 0 else False
        high_52w = high.iloc[-250:].max() if len(high) >= 250 else high.max()
        dist_52w_high = (current_price - high_52w) / high_52w * 100 if len(high) >= 20 else -100.0
        high_stay_days = int(np.sum(close.iloc[-60:] >= high_52w * 0.90)) if len(close) > 0 else 0
        is_5d_breakout = bool(current_price > high.iloc[-6:-1].max()) if len(high) > 6 else False
    except Exception:
        return symbol, "PIVOT_FAIL", None, latency

    try:
        is_gap_up = low.iloc[-1] > high.iloc[-2] if len(high) > 1 else False
        gap_survived = is_gap_up and close.iloc[-1] > high.iloc[-2]
        body = max(abs(close.iloc[-1] - open_p.iloc[-1]), atr14 * QuantConfig.DOJI_BODY_ATR_MULT)
        lower_shadow = min(close.iloc[-1], open_p.iloc[-1]) - low.iloc[-1]
        upper_shadow = high.iloc[-1] - max(close.iloc[-1], open_p.iloc[-1])
        recent_downtrend = bool(close.iloc[-2] < close.iloc[-5]) if len(close) > 5 else False
        is_hammer = lower_shadow > (2 * body) and upper_shadow < (body * 0.5) and recent_downtrend
        near_20ma = abs(dist_ma20) < 5.0
        vol_confirm = bool(current_vol > vol_ma20 * 1.2)
        is_bull_engulfing = recent_downtrend and near_20ma and vol_confirm and (close.iloc[-2] < open_p.iloc[-2]) and (close.iloc[-1] > open_p.iloc[-1]) and (open_p.iloc[-1] < close.iloc[-2]) and (close.iloc[-1] > open_p.iloc[-2]) if len(close) > 1 else False

        min_shadow_limit = max(atr14 * QuantConfig.UPPER_SHADOW_ATR_MULT, current_price * 0.01)
        candle_len = high.iloc[-1] - low.iloc[-1] + 1e-5
        close_pos = (close.iloc[-1] - low.iloc[-1]) / candle_len
        is_upper_heavy = bool(close_pos < QuantConfig.UPPER_SHADOW_CLOSE_POS)
        has_long_upper_shadow = (upper_shadow > min_shadow_limit) and is_upper_heavy

        atr_compression = False
        if len(close) > 120:
            tr_series = pd.Series(tr)
            natr_series = (tr_series.rolling(window=14).mean() / close) * 100
            atr_compression = natr_series.rolling(120).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1]).iloc[-1] < 0.20

        struc = PriceStructure(last_pivot_high_price, prev_pivot_high_price, prev_pivot_low, last_pivot_low, dist_ma20, dist_52w_high, high_stay_days, is_5d_breakout, is_higher_high)
        pat = PricePattern(is_bull_engulfing, is_hammer, gap_survived, is_gap_up, has_long_upper_shadow)
        vty = Volatility(atr14, natr14, atr_compression, adr_20, return_var_20d)
        mom = Momentum(rs_10d, rs_25d, rs_60d, rs_120d, true_rs_composite, ma20, ma_gap, is_trend_up, is_ma20_up)
        vol = VolumeFlow(vr_20, mfi14, relative_vol_today, mixed_tval, adv_100m, is_vol_dry_up)
        risk = RiskProfile(atr_pct, chg_limit, max_gap_allowed)

        latency["total"] = (time.perf_counter() - t_start) * 1000.0
        return symbol, "PASS", CandidateFeature(symbol, name, sector_str, float(current_price), chg, struc, pat, vty, mom, vol, risk), latency
    except Exception:
        return symbol, "PATTERN_FAIL", None, latency

def run_scanner(*args, **kwargs) -> Dict[str, Any]:
    active_tracked_codes = kwargs.get("active_tracked_codes") or (args[0] if len(args) > 0 and isinstance(args[0], list) else None)
    market_ctx = kwargs.get("market_ctx") or (args[1] if len(args) > 1 and isinstance(args[1], dict) else {})
    price_cache = kwargs.get("price_cache") or (args[2] if len(args) > 2 and isinstance(args[2], dict) else None)

    active_tracked_codes = set(active_tracked_codes or [])

    _logger.info("Starting target generation (PriceCache pre-filter + ThreadPool I/O + multiprocessing CPU)")

    if price_cache is None:
        price_cache = build_price_cache()
    if not price_cache:
        _logger.error("Price cache empty, scanner aborted.")
        return {"features_list": [], "active_scanned_codes": set(), "active_tracked_codes": active_tracked_codes}

    valid_items = []
    scanner_target_codes = set()
    scanner_fetch_failed_codes = set()

    for code, meta in price_cache.items():
        is_tracked = code in active_tracked_codes
        prefilter_pass = (
            CONFIG.MIN_PRICE <= meta['price'] <= CONFIG.MAX_PRICE 
            and meta['volume'] >= CONFIG.MIN_VOLUME 
            and meta['trading_value_100m'] >= CONFIG.PRE_FILTER_MIN_TVAL_100M
        )
        if prefilter_pass or is_tracked:
            valid_items.append((code, meta))
            scanner_target_codes.add(code)

    _logger.info("Pre-filter: %d / %d symbols kept for download (tracked forced-in=%d)", len(valid_items), len(price_cache), sum(1 for code, _ in valid_items if code in active_tracked_codes))

    market_returns = {"KOSPI": {}, "KOSDAQ": {}}
    idx_start_date = (datetime.datetime.now() - datetime.timedelta(days=400)).strftime("%Y-%m-%d")
    try:
        for mkt, sym in [("KOSPI", "KS11"), ("KOSDAQ", "KQ11")]:
            df = fdr.DataReader(sym, idx_start_date)
            if len(df) > 0:
                c = df['Close']
                market_returns[mkt] = {
                    "10d": (c.iloc[-1] / c.iloc[-min(11, len(c))] - 1) if len(c) >= 11 else 0,
                    "25d": (c.iloc[-1] / c.iloc[-min(26, len(c))] - 1) if len(c) >= 26 else 0,
                    "60d": (c.iloc[-1] / c.iloc[-min(61, len(c))] - 1) if len(c) >= 61 else 0,
                    "120d": (c.iloc[-1] / c.iloc[-min(121, len(c))] - 1) if len(c) >= 121 else 0,
                }
    except Exception:
        pass

    symbol_start_date = (datetime.datetime.now() - datetime.timedelta(days=300)).strftime("%Y-%m-%d")
    df_cache: Dict[str, pd.DataFrame] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.MAX_IO_WORKERS) as executor:
        future_to_code = {executor.submit(_get_fdr_data_safe, code, symbol_start_date): code for code, _ in valid_items}
        for future in concurrent.futures.as_completed(future_to_code):
            code = future_to_code[future]
            df = future.result()
            if df is not None:
                df_cache[code] = df
            else:
                scanner_fetch_failed_codes.add(code)

    reject_counts = {
        "FETCH_FAIL": 0, "INVALID_DATA": 0, "LOW_PRICE": 0, "LOW_VOL": 0, 
        "LOW_TVAL": 0, "MA60_DOWN": 0, "DATA_LACK": 0, "VOL_DRY": 0, 
        "DATA_CORRUPT": 0, "TA_CALC_FAIL": 0, "INDICATOR_FAIL": 0, 
        "RS_FAIL": 0, "PIVOT_FAIL": 0, "PATTERN_FAIL": 0, "PASS": 0
    }
    reject_counts["PREFILTER_DROP"] = len(price_cache) - len(valid_items)

    args_list = []
    for code, meta in valid_items:
        df = df_cache.get(code)
        if df is None:
            reject_counts["FETCH_FAIL"] += 1
            continue
        args_list.append((code, meta['name'], meta['market'], meta['sector'], market_returns, df))

    features_list: List[CandidateFeature] = []
    active_scanned_codes = set()
    latency_stats = {"ta": [], "total": []}

    with mp.Pool(processes=CONFIG.MAX_WORKERS, maxtasksperchild=50) as pool:
        for code, reason, res, latency in pool.imap_unordered(build_candidate_feature, args_list):
            active_scanned_codes.add(code)
            reject_counts[reason] = reject_counts.get(reason, 0) + 1
            if res is not None:
                features_list.append(res)
                latency_stats["ta"].append(latency["ta"])
                latency_stats["total"].append(latency["total"])

    scanner_missing_tracked = active_tracked_codes - active_scanned_codes
    if scanner_missing_tracked:
        _logger.warning("Scanner coverage gap detected (tracked not fully scanned): %s", sorted(scanner_missing_tracked))

    if latency_stats["total"]:
        market_ctx["latency_metrics_ms"] = {
            "ta_p95": round(np.percentile(latency_stats["ta"], 95), 1),
            "total_mean": round(np.mean(latency_stats["total"]), 1),
            "total_p99": round(np.percentile(latency_stats["total"], 99), 1),
        }
    market_ctx["scanner_rejects"] = reject_counts
    market_ctx["scanner_coverage"] = {
        "tracked_count": len(active_tracked_codes),
        "targeted_count": len(scanner_target_codes),
        "scanned_count": len(active_scanned_codes),
        "fetch_failed_count": len(scanner_fetch_failed_codes),
        "missing_tracked_count": len(scanner_missing_tracked),
    }

    return {
        "features_list": features_list,
        "active_scanned_codes": active_scanned_codes,
        "active_tracked_codes": active_tracked_codes,
    }
