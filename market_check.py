import datetime
import pytz
import FinanceDataReader as fdr
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import time
import re
import logging

_breadth_cache = {"timestamp": 0, "data": None}
_prev_avg_ratio = 50.0

def get_realtime_breadth():
    global _breadth_cache, _prev_avg_ratio
    current_time = time.time()
    
    if _breadth_cache["data"] is not None and (current_time - _breadth_cache["timestamp"] < 180):
        cached = _breadth_cache["data"].copy()
        cached["source"] = "CACHE"
        return cached
        
    b_data = {"kp_up": 0, "kp_down": 0, "kp_same": 0, "kd_up": 0, "kd_down": 0, "kd_same": 0, "error_detail": None, "source": "NONE"}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    success = False
    
    # [Fallback 1] NAVER API
    try:
        res_kp = requests.get("https://m.stock.naver.com/api/index/KOSPI/price", headers=headers, timeout=3)
        res_kd = requests.get("https://m.stock.naver.com/api/index/KOSDAQ/price", headers=headers, timeout=3)
        if res_kp.status_code == 200 and res_kd.status_code == 200:
            kp_rf, kd_rf = res_kp.json().get("riseFall", {}), res_kd.json().get("riseFall", {})
            b_data["kp_up"], b_data["kp_down"], b_data["kp_same"] = kp_rf.get("rise",0), kp_rf.get("fall",0), kp_rf.get("same",0)
            b_data["kd_up"], b_data["kd_down"], b_data["kd_same"] = kd_rf.get("rise",0), kd_rf.get("fall",0), kd_rf.get("same",0)
            if (b_data["kp_up"] + b_data["kp_down"]) > 0: 
                success, b_data["source"] = True, "NAVER API"
    except Exception as e: logging.warning(f"Breadth API Failed: {e}")
    
    # [Fallback 2] NAVER DOM
    if not success:
        try:
            for code, k_up, k_down, k_same in [("KOSPI", "kp_up", "kp_down", "kp_same"), ("KOSDAQ", "kd_up", "kd_down", "kd_same")]:
                res = requests.get(f"https://finance.naver.com/sise/sise_index.naver?code={code}", headers=headers, timeout=5)
                soup = BeautifulSoup(res.text, 'html.parser')
                dl = soup.find("dl", class_="lst_kos_info")
                if dl:
                    for dt in dl.find_all("dt"):
                        txt = dt.get_text().strip()
                        dd = dt.find_next_sibling("dd")
                        if not dd: continue
                        val = int(re.search(r'[\d,]+', dd.get_text()).group().replace(",", "")) if re.search(r'[\d,]+', dd.get_text()) else 0
                        if "상승" in txt: b_data[k_up] = val
                        elif "하락" in txt: b_data[k_down] = val
                        elif "보합" in txt: b_data[k_same] = val
            if (b_data["kp_up"] + b_data["kp_down"]) > 0: 
                success, b_data["source"] = True, "NAVER DOM"
        except Exception as e: logging.warning(f"Breadth DOM Failed: {e}")

    # [Fallback 3] FinanceDataReader (KRX 전체 종목 카운팅)
    if not success:
        try:
            krx = fdr.StockListing('KRX')
            b_data["kp_up"] = len(krx[(krx['Market'] == 'KOSPI') & (krx['ChangesRatio'] > 0)])
            b_data["kp_down"] = len(krx[(krx['Market'] == 'KOSPI') & (krx['ChangesRatio'] < 0)])
            b_data["kp_same"] = len(krx[(krx['Market'] == 'KOSPI') & (krx['ChangesRatio'] == 0)])
            b_data["kd_up"] = len(krx[(krx['Market'] == 'KOSDAQ') & (krx['ChangesRatio'] > 0)])
            b_data["kd_down"] = len(krx[(krx['Market'] == 'KOSDAQ') & (krx['ChangesRatio'] < 0)])
            b_data["kd_same"] = len(krx[(krx['Market'] == 'KOSDAQ') & (krx['ChangesRatio'] == 0)])
            if (b_data["kp_up"] + b_data["kp_down"]) > 0: 
                success, b_data["source"] = True, "FDR KRX"
        except Exception as e: logging.warning(f"Breadth FDR Failed: {e}")

    # [Fallback 4] Yahoo Finance (지수만이라도 확인)
    if not success:
        try:
            yf_kp = yf.Ticker("^KS11").history(period="1d")
            if not yf_kp.empty:
                success, b_data["source"] = True, "YAHOO (Index Only)"
        except Exception as e: logging.warning(f"Breadth Yahoo Failed: {e}")

    # [Fallback 5] CACHE
    if not success:
        if _breadth_cache["data"] is not None:
            cached = _breadth_cache["data"].copy()
            cached["source"] = "CACHE"
            return cached
        else:
            return {"kp_up": 0, "kp_down": 0, "kp_same": 0, "kd_up": 0, "kd_down": 0, "kd_same": 0, "kp_ratio": 50.0, "kd_ratio": 50.0, "avg_ratio": 50.0, "trend": "Unknown", "source": "NONE", "error_detail": "All Scrapers Blocked"}

    kp_total = b_data["kp_up"] + b_data["kp_down"]
    kd_total = b_data["kd_up"] + b_data["kd_down"]
    b_data["kp_ratio"] = round((b_data["kp_up"] / kp_total) * 100, 1) if kp_total > 0 else 50.0
    b_data["kd_ratio"] = round((b_data["kd_up"] / kd_total) * 100, 1) if kd_total > 0 else 50.0
    avg_ratio = (b_data["kp_ratio"] + b_data["kd_ratio"]) / 2
    b_data["avg_ratio"] = avg_ratio
    
    if avg_ratio > _prev_avg_ratio + 3: b_data["trend"] = "Improving"
    elif avg_ratio < _prev_avg_ratio - 3: b_data["trend"] = "Weakening"
    else: b_data["trend"] = "Flat"
    
    _prev_avg_ratio = avg_ratio
    _breadth_cache = {"timestamp": current_time, "data": b_data}
    return b_data

def get_market_context():
    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    breadth = get_realtime_breadth()
    
    is_fdr_ok = False
    kp_1d, kp_5d, kp_20d = 0.0, 0.0, 0.0
    kd_1d, kd_5d, kd_20d = 0.0, 0.0, 0.0
    
    try:
        kospi = fdr.DataReader("KS11", start_date)
        kosdaq = fdr.DataReader("KQ11", start_date)
        if len(kospi) >= 21 and len(kosdaq) >= 21:
            kp_1d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-2]) - 1) * 100
            kd_1d = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-2]) - 1) * 100
            kp_5d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-6]) - 1) * 100
            kd_5d = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-6]) - 1) * 100
            kp_20d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-21]) - 1) * 100
            kd_20d = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-21]) - 1) * 100
            is_fdr_ok = True
    except Exception as e:
        logging.error(f"Index FDR Failed: {e}")

    active_sources = 0
    if is_fdr_ok: active_sources += 2
    if breadth["source"] in ["NAVER API", "NAVER DOM"]: active_sources += 3
    elif breadth["source"] == "FDR KRX": active_sources += 2
    elif breadth["source"] == "CACHE": active_sources += 1
    
    conf_stars = "★" * active_sources + "☆" * (5 - active_sources)
    
    # 👑 복합 CRASH 판정 (지수 + 시장폭 + 20일 추세)
    is_crash = False
    if kp_1d <= -3.0 and breadth.get("avg_ratio", 50) < 35 and kp_20d < -5.0:
        is_crash = True
        
    if active_sources == 0: state = "UNKNOWN_HOLD"
    elif is_crash: state = "CRASH"
    elif kp_1d <= -1.5 or breadth.get("avg_ratio", 50) < 40: state = "RISK"
    elif active_sources <= 2: state = "CAUTION"
    elif kp_1d >= 1.0 and breadth.get("trend") == "Improving": state = "BULL"
    else: state = "NORMAL"
        
    return {
        "state": state, "conf_stars": conf_stars, "fdr_ok": is_fdr_ok,
        "kospi_1d": round(kp_1d, 2), "kospi_5d": round(kp_5d, 2), "kospi_20d": round(kp_20d, 2),
        "kosdaq_1d": round(kd_1d, 2), "kosdaq_5d": round(kd_5d, 2), "kosdaq_20d": round(kd_20d, 2),
        "breadth": breadth
    }
