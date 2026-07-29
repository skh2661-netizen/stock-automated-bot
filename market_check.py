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

# [개선] 모듈 레벨 세션 (TCP/TLS Handshake 오버헤드 최소화)
_SESSION = requests.Session()

# [개선] 상수화 (오타 방지 및 가독성 확보)
SOURCE_NAVER = "Naver Real-time"
SOURCE_MIXED = "Mixed (Naver/FDR)"
SOURCE_FDR = "FDR Cached (Fallback)"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"

# [개선] 필수 브라우저 중심의 효율적인 UA Pool
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/114.0.1823.58",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15"
]

def get_realtime_naver_index(code="KOSPI"):
    """
    네이버 금융 Polling API (Session 재사용 및 점진적 재시도 적용)
    """
    url = f"https://polling.finance.naver.com/api/realtime/domestic/index/{code}"
    
    for attempt in range(2):
        headers = {"User-Agent": random.choice(UA_POOL)}
        try:
            res = _SESSION.get(url, headers=headers, timeout=(5, 10))
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

def get_market_context() -> dict:
    _logger.info("Checking market context (Observability & Confidence Enhanced)...")
    
    now = datetime.datetime.now()
    ctx = {
        "state": "UNKNOWN",
        "score": 0,
        "allow_scan": False,
        "reason": "",
        "warning": "",       
        "market_timestamp": now.strftime("%H:%M:%S.%f")[:-3], # [개선] 데이터 관측 시간 (예: 10:02:14.523)
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
        "confidence_level": CONFIDENCE_HIGH,
        "diagnostics": {} # [개선] 운영자 디버깅용 내부 지표
    }

    warnings = []
    reasons = []
    confidence = 100

    # 1. 지수 데이터 획득
    kpi_price_rt, kpi_chg_rt = get_realtime_naver_index("KOSPI")
    kdq_price_rt, kdq_chg_rt = get_realtime_naver_index("KOSDAQ")
    
    # 2. Source 및 초기 Confidence 판독 (감점식)
    sources_success = []
    if kpi_price_rt is not None: sources_success.append("KOSPI")
    if kdq_price_rt is not None: sources_success.append("KOSDAQ")
    
    if len(sources_success) == 2:
        source_label = SOURCE_NAVER
    elif len(sources_success) == 1:
        source_label = SOURCE_MIXED
        confidence -= 20
        warnings.append(f"네이버 API 부분 실패 ({sources_success[0]}만 정상)")
    else:
        source_label = SOURCE_FDR
        confidence -= 50
        warnings.append("네이버 API 전면 차단 (FDR 종가 Fallback)")

    # 3. FDR 과거 데이터 및 Fallback 로드 (20MA용)
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
        ctx["confidence_level"] = CONFIDENCE_LOW
        return ctx

    ctx["kospi_1d"] = kpi_chg
    ctx["kosdaq_1d"] = kdq_chg
    ctx["kospi_20ma"] = round(kospi_20ma, 2)
    ctx["kosdaq_20ma"] = round(kosdaq_20ma, 2)
    ctx["source"] = source_label

    # 4. 시장 온기 (Breadth) 계산
    listed_count = 1
    try:
        krx = fdr.StockListing("KRX")
        if krx is not None and not krx.empty:
            listed_count = len(krx)
            if 'Chg' in krx.columns:
                krx['Chg'] = pd.to_numeric(krx['Chg'], errors='coerce')
                up = int((krx['Chg'] > 0).sum())
                down = int((krx['Chg'] < 0).sum())
                same = int((krx['Chg'] == 0).sum())
            else:
                up, down, same = 0, 0, 0
        else:
            up, down, same = 0, 0, 0
    except Exception:
        up, down, same = 0, 0, 0

    total_valid = up + down
    advance_ratio = round((up / total_valid) * 100, 1) if total_valid > 0 else 0.0
    
    # [개선] 매직 넘버(1000)를 없애고 동적 커버리지 계산
    coverage = round((total_valid + same) / listed_count, 3) if listed_count > 0 else 0.0

    ctx["total_up"] = up
    ctx["total_down"] = down
    ctx["total_same"] = same
    ctx["advance_ratio"] = advance_ratio

    # 5. 데이터 신선도(Freshness) 및 추가 감점
    is_breadth_stale = False
    
    if coverage < 0.4:
        is_breadth_stale = True
        confidence -= 20
        warnings.append(f"시장 온기 미완성 (커버리지 {coverage*100:.1f}%)")
    else:
        if (kpi_chg <= -1.0 and kdq_chg <= -1.0) and advance_ratio > 40.0:
            is_breadth_stale = True
            confidence -= 40
            warnings.append("지수 폭락 중 온기 양호 (FDR 지연 의심)")
        elif (kpi_chg >= 1.0 and kdq_chg >= 1.0) and advance_ratio < 30.0:
            is_breadth_stale = True
            confidence -= 40
            warnings.append("지수 급등 중 온기 악화 (FDR 지연 의심)")

    # 6. 신뢰도 확정 및 Hard Cutoff [버그 픽스 완료]
    confidence = max(0, confidence)
    ctx["confidence"] = confidence
    
    if confidence >= 80:
        conf_level = CONFIDENCE_HIGH
    elif confidence >= 50:
        conf_level = CONFIDENCE_MEDIUM
    else:
        conf_level = CONFIDENCE_LOW
        
    ctx["confidence_level"] = conf_level

    # [개선] Observability Diagnostics 구성
    ctx["diagnostics"] = {
        "coverage": coverage,
        "source": source_label,
        "api_success": len(sources_success),
        "breadth_stale": is_breadth_stale,
        "raw_confidence": confidence
    }

    if conf_level == CONFIDENCE_LOW:
        _logger.warning(f"Market data confidence is LOW ({confidence}). Blocking operations. Diagnostics: {ctx['diagnostics']}")
        ctx["state"] = "UNKNOWN"
        ctx["allow_scan"] = False
        ctx["reason"] = "시장 데이터 신뢰도 심각한 부족 (오판 방지용 셧다운)"
        ctx["warning"] = " | ".join(warnings[:3]) if warnings else "원인 불명"
        return ctx

    # 7. 점수 산정 및 동적 임계값 설정
    score = 0
    if kpi_price > kospi_20ma: score += 30
    if kdq_price > kosdaq_20ma: score += 30
    
    if is_breadth_stale:
        normal_cutoff = 60
        caution_cutoff = 30
    else:
        if advance_ratio >= 40.0: score += 40
        elif advance_ratio >= 30.0: score += 20
        normal_cutoff = 80
        caution_cutoff = 50

    ctx["score"] = score

    # 8. 시장 상태 판독
    if (kpi_chg <= -2.0 and kdq_chg <= -2.0) or (not is_breadth_stale and advance_ratio < 15.0):
        ctx["state"] = "CRASH"
        ctx["allow_scan"] = False
        reasons.append("양시장 -2% 동반 급락 또는 심각한 투매장")
    elif score >= normal_cutoff and conf_level == CONFIDENCE_HIGH:
        ctx["state"] = "NORMAL"
        ctx["allow_scan"] = True
        reasons.append("지수 20MA 상회 및 온기 양호" if not is_breadth_stale else "지수 20MA 상회 (온기 제외)")
    elif score >= caution_cutoff:
        ctx["state"] = "CAUTION"
        ctx["allow_scan"] = True
        reasons.append("시장 혼조세 (주의)")
    else:
        ctx["state"] = "WEAK"
        ctx["allow_scan"] = False
        reasons.append("지수 20MA 하회 및 온기 악화 (매수 차단)")

    ctx["reason"] = " | ".join(reasons) if reasons else "특이사항 없음"
    ctx["warning"] = " | ".join(warnings[:3]) if warnings else "" # [개선] 텔레그램 출력 방어
    
    return ctx
