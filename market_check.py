import datetime
import pytz
import FinanceDataReader as fdr
import requests
from bs4 import BeautifulSoup
import time
import re
import logging

# GitHub Actions 디버깅을 위한 로깅 레벨 세팅
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

_breadth_cache = {"timestamp": 0, "data": None}
_prev_avg_ratio = 50.0

def get_realtime_breadth():
    global _breadth_cache, _prev_avg_ratio
    current_time = time.time()
    
    if _breadth_cache["data"] is not None and (current_time - _breadth_cache["timestamp"] < 180):
        cached_data = _breadth_cache["data"]
        cached_data["is_cached"] = True
        cached_data["source"] = "CACHE"
        return cached_data
        
    b_data = {"kp_up": 0, "kp_down": 0, "kd_up": 0, "kd_down": 0, "error_detail": None, "is_cached": False, "source": "NONE"}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.naver.com/'
    }
    success = False
    
    # [Fallback 1] API
    try:
        res_kp = requests.get("https://m.stock.naver.com/api/index/KOSPI/price", headers=headers, timeout=3)
        res_kd = requests.get("https://m.stock.naver.com/api/index/KOSDAQ/price", headers=headers, timeout=3)
        if res_kp.status_code == 200 and res_kd.status_code == 200:
            b_data["kp_up"] = res_kp.json().get("riseFall", {}).get("rise", 0)
            b_data["kp_down"] = res_kp.json().get("riseFall", {}).get("fall", 0)
            b_data["kd_up"] = res_kd.json().get("riseFall", {}).get("rise", 0)
            b_data["kd_down"] = res_kd.json().get("riseFall", {}).get("fall", 0)
            if (b_data["kp_up"] + b_data["kp_down"]) > 0: 
                success = True
                b_data["source"] = "NAVER_API"
    except Exception as e:
        logging.warning(f"Breadth API Fallback 1 Failed: {e}")
    
    # [Fallback 2] DOM
    if not success:
        try:
            res_kp = requests.get("https://finance.naver.com/sise/sise_index.naver?code=KOSPI", headers=headers, timeout=5)
            soup_kp = BeautifulSoup(res_kp.text, 'html.parser')
            dl_kp = soup_kp.find("dl", class_="lst_kos_info")
            if dl_kp:
                for dt in dl_kp.find_all("dt"):
                    txt = dt.get_text().strip()
                    dd = dt.find_next_sibling("dd")
                    if not dd: continue
                    val = int(re.search(r'[\d,]+', dd.get_text()).group().replace(",", "")) if re.search(r'[\d,]+', dd.get_text()) else 0
                    if "상승" in txt: b_data["kp_up"] = val
                    elif "하락" in txt: b_data["kp_down"] = val
            
            res_kd = requests.get("https://finance.naver.com/sise/sise_index.naver?code=KOSDAQ", headers=headers, timeout=5)
            soup_kd = BeautifulSoup(res_kd.text, 'html.parser')
            dl_kd = soup_kd.find("dl", class_="lst_kos_info")
            if dl_kd:
                for dt in dl_kd.find_all("dt"):
                    txt = dt.get_text().strip()
                    dd = dt.find_next_sibling("dd")
                    if not dd: continue
                    val = int(re.search(r'[\d,]+', dd.get_text()).group().replace(",", "")) if re.search(r'[\d,]+', dd.get_text()) else 0
                    if "상승" in txt: b_data["kd_up"] = val
                    elif "하락" in txt: b_data["kd_down"] = val
            if (b_data["kp_up"] + b_data["kp_down"]) > 0: 
                success = True
                b_data["source"] = "NAVER_DOM"
        except Exception as e:
            b_data["error_detail"] = f"DOM Fail: {str(e)[:20]}"
            logging.warning(f"Breadth DOM Fallback 2 Failed: {e}")

    # [Fallback 3] Cache
    if not success:
        if _breadth_cache["data"] is not None:
            cached_data = _breadth_cache["data"]
            cached_data["is_cached"] = True
            cached_data["source"] = "STALE_CACHE"
            cached_data["error_detail"] = "Using Stale Cache"
            logging.warning("Breadth scraping failed, using stale cache.")
            return cached_data
        else:
            logging.error("All Breadth scrapers blocked and no cache available.")
            return {"kp_up": 0, "kp_down": 0, "kd_up": 0, "kd_down": 0, "kp_ratio": 50.0, "kd_ratio": 50.0, "avg_ratio": 50.0, "trend": "Unknown", "error_detail": "All Scrapers Blocked", "is_cached": False, "source": "NONE"}

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
    is_breadth_ok = breadth.get("trend") != "Unknown"
    is_breadth_cached = breadth.get("is_cached", False)
    
    is_fdr_ok = False
    fdr_error = None
    kp_1d, kp_5d, kp_20d = 0.0, 0.0, 0.0
    kd_1d, kd_5d, kd_20d = 0.0, 0.0, 0.0
    
    try:
        kospi = fdr.DataReader("KS11", start_date)
        kosdaq = fdr.DataReader("KQ11", start_date)
        if len(kospi) >= 2 and len(kosdaq) >= 2:
            kp_1d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-2]) - 1) * 100
            kd_1d = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-2]) - 1) * 100
            kp_5d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-6]) - 1) * 100 if len(kospi) >= 6 else 0
            kd_5d = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-6]) - 1) * 100 if len(kosdaq) >= 6 else 0
            kp_20d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-21]) - 1) * 100 if len(kospi) >= 21 else 0
            kd_20d = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-21]) - 1) * 100 if len(kosdaq) >= 21 else 0
            is_fdr_ok = True
        else: 
            fdr_error = "Insufficient FDR Data"
            logging.warning("FDR DataReader returned insufficient rows.")
    except Exception as e:
        fdr_error = f"FDR Blocked: {str(e)[:20]}"
        logging.error(f"FDR DataReader Failed: {e}")

    # 신뢰도 세분화 (캐시 여부 엄격 적용)
    if is_fdr_ok and is_breadth_ok and not is_breadth_cached:
        data_conf = "HIGH"
    elif is_fdr_ok and is_breadth_ok and is_breadth_cached:
        data_conf = "MEDIUM (Cache)"
    elif is_fdr_ok and not is_breadth_ok:
        data_conf = "MEDIUM (Idx Only)"
    elif not is_fdr_ok and is_breadth_ok:
        data_conf = "MEDIUM (Brd Only)"
    else:
        data_conf = "LOW (All Failed)"

    # 보수적 국면 판정 (맹목적 NORMAL 진입 차단)
    if data_conf == "LOW (All Failed)":
        state = "UNKNOWN_HOLD"
    elif data_conf == "MEDIUM (Idx Only)":
        if kp_1d <= -3.0: state = "CRASH"
        elif kp_1d <= -1.5: state = "RISK"
        else: state = "CAUTION" 
    elif data_conf in ["MEDIUM (Brd Only)", "MEDIUM (Cache)"]:
        if breadth.get("trend") == "Weakening": state = "RISK"
        else: state = "CAUTION"
    else:
        if kp_1d <= -3.0: state = "CRASH"
        elif kp_1d <= -1.5: state = "RISK"
        elif kp_1d >= 1.0 and breadth.get("trend") == "Improving": state = "BULL"
        else: state = "NORMAL"
        
    return {
        "state": state, "data_confidence": data_conf, "fdr_error": fdr_error,
        "kospi_1d": round(kp_1d, 2), "kospi_5d": round(kp_5d, 2), "kospi_20d": round(kp_20d, 2),
        "kosdaq_1d": round(kd_1d, 2), "kosdaq_5d": round(kd_5d, 2), "kosdaq_20d": round(kd_20d, 2),
        "breadth": breadth
    }
