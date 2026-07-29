import os
import time
import random
import logging
import datetime
import requests
import numpy as np
import pandas as pd
import FinanceDataReader as fdr

_logger = logging.getLogger(__name__)

# -------------------------------------------------------------
# [설정] 시스템 상수 및 임계값
# -------------------------------------------------------------
SOURCE_NAVER = "Naver Real-time"
SOURCE_MIXED = "Mixed (Naver/FDR)"
SOURCE_FDR = "FDR Cached (Fallback)"

CONFIDENCE_HIGH_THRESHOLD = 80
CONFIDENCE_MEDIUM_THRESHOLD = 50

SCORE_MA_KOSPI = 30
SCORE_MA_KOSDAQ = 30
SCORE_BREADTH_STRONG = 40
SCORE_BREADTH_WEAK = 20

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/114.0.1823.58",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15"
]

def get_realtime_naver_index(session: requests.Session, code="KOSPI"):
    url = f"https://polling.finance.naver.com/api/realtime/domestic/index/{code}"
    
    for attempt in range(2):
        headers = {"User-Agent": random.choice(UA_POOL)}
        try:
            res = session.get(url, headers=headers, timeout=(5, 10))
            res.raise_for_status()
            data = res.json()
            
            datas = data.get('datas', [])
            if not datas:
                return None, None
                
            idx_data = datas[0]
            current_price = float(idx_data.get('closePrice', '0').replace(',', ''))
            fluctuation_ratio = float(idx_data.get('fluctuationsRatio', '0'))
            
            if current_price == 0:
                return None, None
                
            return current_price, fluctuation_ratio
            
        except Exception as e:
            _logger.warning("Naver realtime API failed for %s (Attempt %d/2): %s", code, attempt + 1, e)
            if attempt == 0:
                time.sleep(0.5 * (attempt + 1))
                
    return None, None

def get_market_breadth() -> dict:
    breadth_data = {"up": 0, "down": 0, "same": 0, "valid_price_count": 0, "listed_count": None}
    try:
        krx = fdr.StockListing("KRX")
        if krx is not None and not krx.empty:
            breadth_data["listed_count"] = len(krx)
            chg_col = next((col for col in ['Chg', 'Change', 'ChangesRatio', 'ChagesRatio', 'Changes', 'Fluctuation'] if col in krx.columns), None)
            
            if chg_col:
                numeric_series = pd.to_numeric(krx[chg_col], errors='coerce')
                
                # [수정 3] NaN 제외는 물론, 상하한가(-30~30%) 범위를 벗어나는 이상치(Sanity Check)까지 필터링
                valid_mask = numeric_series.notna() & numeric_series.between(-31.0, 31.0)
                
                breadth_data["up"] = int((numeric_series[valid_mask] > 0).sum())
                breadth_data["down"] = int((numeric_series[valid_mask] < 0).sum())
                breadth_data["same"] = int((numeric_series[valid_mask] == 0).sum())
                
                breadth_data["valid_price_count"] = int(valid_mask.sum())
            else:
                _logger.warning(f"FDR KRX 데이터에 등락 컬럼 없음. 현재 컬럼: {krx.columns.tolist()}")
    except Exception as e:
        _logger.error(f"Breadth calculation failed: {e}")
        
    return breadth_data

def get_market_context() -> dict:
    _logger.info("Checking market context (Conservative Auto-Trading Config)...")
    
    now = datetime.datetime.now()
    ctx = {
        "state": "UNKNOWN",
        "score": 0,
        "allow_scan": False,
        "reason": "",
        "warning": "",       
        "market_timestamp": now.strftime("%H:%M:%S.%f")[:-3],
        "health": "UNKNOWN", 
        "kospi_1d": 0.0,
        "kosdaq_1d": 0.0,
        "kospi_20ma": 0.0,
        "kosdaq_20ma": 0.0,
        "advance_ratio": 0.0,
        "total_up": 0,
        "total_down": 0,
        "total_same": 0,
        "source": "UNKNOWN",
        "confidence": 100,
        "confidence_level": "HIGH",
        "diagnostics": {}
    }

    warnings = []
    reasons = []
    confidence = 100.0  # [수정 4] 가중치 곱연산을 위해 float로 시작

    with requests.Session() as session:
        kpi_price_rt, kpi_chg_rt = get_realtime_naver_index(session, "KOSPI")
        kdq_price_rt, kdq_chg_rt = get_realtime_naver_index(session, "KOSDAQ")
    
    sources_success = []
    if kpi_price_rt is not None: sources_success.append("KOSPI")
    if kdq_price_rt is not None: sources_success.append("KOSDAQ")
    
    # [수정 4] 가중치 감점 방식 (*= 0.9, *= 0.7)
    if len(sources_success) == 2:
        source_label = SOURCE_NAVER
    elif len(sources_success) == 1:
        source_label = SOURCE_MIXED
        confidence *= 0.9
        warnings.append(f"네이버 API 부분 실패 ({sources_success[0]} 정상)")
    else:
        source_label = SOURCE_FDR
        confidence *= 0.7
        warnings.append("네이버 API 전면 차단 (FDR 종가 Fallback)")

    start_date = (now - datetime.timedelta(days=40)).strftime("%Y-%m-%d")
    try:
        df_kospi = fdr.DataReader("KS11", start_date)
        df_kosdaq = fdr.DataReader("KQ11", start_date)

        if df_kospi is None or df_kospi.empty or df_kosdaq is None or df_kosdaq.empty:
            raise ValueError("FDR returned empty DataFrame")

        kospi_20ma = float(df_kospi['Close'].rolling(window=20).mean().iloc[-1])
        kosdaq_20ma = float(df_kosdaq['Close'].rolling(window=20).mean().iloc[-1])

        fdr_kpi_price = float(df_kospi['Close'].iloc[-1])
        fdr_kpi_chg = round((fdr_kpi_price / float(df_kospi['Close'].iloc[-2]) - 1) * 100, 2) if len(df_kospi) > 1 else 0.0
        fdr_kdq_price = float(df_kosdaq['Close'].iloc[-1])
        fdr_kdq_chg = round((fdr_kdq_price / float(df_kosdaq['Close'].iloc[-2]) - 1) * 100, 2) if len(df_kosdaq) > 1 else 0.0

        kpi_price = kpi_price_rt if kpi_price_rt is not None else fdr_kpi_price
        kpi_chg = kpi_chg_rt if kpi_chg_rt is not None else fdr_kpi_chg
        kdq_price = kdq_price_rt if kdq_price_rt is not None else fdr_kdq_price
        kdq_chg = kdq_chg_rt if kdq_chg_rt is not None else fdr_kdq_chg

    except Exception as e:
        _logger.error("Index data fetch failed: %s", e)
        ctx["state"] = "INVALID"
        ctx["reason"] = "시장 데이터 로드 완전 실패"
        ctx["warning"] = f"FDR 오류: {e}"
        ctx["confidence"] = 0
        ctx["confidence_level"] = "LOW"
        ctx["health"] = "FAIL"
        return ctx

    ctx["kospi_1d"] = kpi_chg
    ctx["kosdaq_1d"] = kdq_chg
    ctx["kospi_20ma"] = round(kospi_20ma, 2)
    ctx["kosdaq_20ma"] = round(kosdaq_20ma, 2)
    ctx["source"] = source_label

    breadth = get_market_breadth()
    up, down, same = breadth["up"], breadth["down"], breadth["same"]
    valid_price_count = breadth["valid_price_count"]
    listed_count = breadth["listed_count"]

    advance_ratio = round((up / (up + down)) * 100, 1) if (up + down) > 0 else 0.0
    coverage = round(valid_price_count / listed_count, 3) if listed_count else None

    ctx["total_up"] = up
    ctx["total_down"] = down
    ctx["total_same"] = same
    ctx["advance_ratio"] = advance_ratio

    is_breadth_stale = False
    expected_coverage = 0.9
    
    if now.hour == 9:
        if now.minute < 10: expected_coverage = 0.15
        elif now.minute < 30: expected_coverage = 0.5
        
    if coverage is None or coverage < expected_coverage:
        is_breadth_stale = True
        confidence *= 0.8  # [수정 4] 곱연산 가중치
        cov_str = f"{coverage*100:.1f}%" if coverage is not None else "계산 불가"
        warnings.append(f"시장 온기 미완성/누락 (유효 커버리지 {cov_str}, 필요 {expected_coverage*100:.0f}%)")
    else:
        # [수정 2] 장초반(09:30 이전)의 단순 변동성이 지연으로 오판되는 것 방지
        if now.time() >= datetime.time(9, 30):
            if (kpi_chg <= -1.5 and kdq_chg <= -1.5) and advance_ratio > 45.0:
                is_breadth_stale = True
                confidence *= 0.8
                warnings.append("지수 폭락 중 온기 양호 (Breadth 지연 의심)")
            elif (kpi_chg >= 1.5 and kdq_chg >= 1.5) and advance_ratio < 25.0:
                is_breadth_stale = True
                confidence *= 0.8
                warnings.append("지수 급등 중 온기 악화 (Breadth 지연 의심)")

    confidence = int(max(0, confidence))
    ctx["confidence"] = confidence
    
    if confidence >= CONFIDENCE_HIGH_THRESHOLD:
        conf_level = "HIGH"
        ctx["health"] = "OK"
    elif confidence >= CONFIDENCE_MEDIUM_THRESHOLD:
        conf_level = "MEDIUM"
        ctx["health"] = "DEGRADED"
    else:
        conf_level = "LOW"
        ctx["health"] = "FAIL"
        
    ctx["confidence_level"] = conf_level
    
    ctx["diagnostics"] = {
        "coverage": coverage,
        "listed_count": listed_count,
        "valid_price_count": valid_price_count,
        "session_time": ctx["market_timestamp"],
        "source": source_label,
        "api_success": len(sources_success),
        "breadth_stale": is_breadth_stale,
        "raw_confidence": confidence
    }

    score = 0
    if kpi_price > kospi_20ma: score += SCORE_MA_KOSPI
    if kdq_price > kosdaq_20ma: score += SCORE_MA_KOSDAQ
    
    if is_breadth_stale:
        normal_cutoff = SCORE_MA_KOSPI + SCORE_MA_KOSDAQ
        caution_cutoff = SCORE_MA_KOSPI
    else:
        if advance_ratio >= 40.0: score += SCORE_BREADTH_STRONG
        elif advance_ratio >= 30.0: score += SCORE_BREADTH_WEAK
        normal_cutoff = SCORE_MA_KOSPI + SCORE_MA_KOSDAQ + SCORE_BREADTH_WEAK
        caution_cutoff = SCORE_MA_KOSPI + SCORE_BREADTH_WEAK

    ctx["score"] = score

    # 6. [판정 1순위] CRASH
    is_index_crash = (kpi_chg <= -2.0 and kdq_chg <= -2.0)
    is_breadth_crash = (not is_breadth_stale and coverage is not None and coverage >= 0.8 and advance_ratio < 15.0)
    
    if is_index_crash or is_breadth_crash:
        ctx["state"] = "CRASH"
        ctx["allow_scan"] = False
        
        if is_index_crash:
            reasons.append("양시장 -2% 동반 급락 (데이터 신뢰도와 무관한 폭락 판정)")
        else:
            reasons.append(f"심각한 투매장 (상승비율 {advance_ratio}%)")
            
        ctx["reason"] = " | ".join(reasons)
        ctx["warning"] = " | ".join(warnings[:3]) if warnings else ""
        return ctx

    # 7. [판정 2순위] Hard Cutoff
    if conf_level == "LOW":
        _logger.warning(f"Market data confidence is LOW ({confidence}). Blocking operations. Diagnostics: {ctx['diagnostics']}")
        ctx["state"] = "UNKNOWN"
        ctx["allow_scan"] = False
        ctx["reason"] = "시장 데이터 신뢰도 심각한 부족 (오판 방지 셧다운)"
        ctx["warning"] = " | ".join(warnings[:3]) if warnings else "원인 불명"
        return ctx

    # 8. [판정 3순위] NORMAL / CAUTION / WEAK
    # [수정 1] NORMAL은 오직 HIGH 신뢰도에서만 허용. MEDIUM이면 최대 CAUTION으로 강제 격하
    if score >= normal_cutoff:
        if conf_level == "HIGH":
            ctx["state"] = "NORMAL"
            ctx["allow_scan"] = True
            reasons.append("지수 20MA 상회 및 온기 양호" if not is_breadth_stale else "지수 20MA 상회 (온기 제외)")
        else: # MEDIUM
            ctx["state"] = "CAUTION"
            ctx["allow_scan"] = True
            reasons.append("시장 상태는 양호하나 데이터 신뢰도 하락 (안전망 가동)")
    elif score >= caution_cutoff:
        ctx["state"] = "CAUTION"
        ctx["allow_scan"] = True
        reasons.append("시장 혼조세 (주의)")
    else:
        ctx["state"] = "WEAK"
        ctx["allow_scan"] = False
        reasons.append("지수 20MA 하회 및 온기 악화 (매수 차단)")

    ctx["reason"] = " | ".join(reasons) if reasons else "특이사항 없음"
    ctx["warning"] = " | ".join(warnings[:3]) if warnings else ""
    
    return ctx
