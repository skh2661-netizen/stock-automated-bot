import datetime
import pytz
import FinanceDataReader as fdr
import requests
from bs4 import BeautifulSoup
import time
import re

_breadth_cache = {"timestamp": 0, "data": None}
_prev_avg_ratio = 50.0

def get_realtime_breadth():
    global _breadth_cache, _prev_avg_ratio
    current_time = time.time()
    
    if _breadth_cache["data"] is not None and (current_time - _breadth_cache["timestamp"] < 180):
        return _breadth_cache["data"]
        
    b_data = {"kp_up": 0, "kp_down": 0, "kd_up": 0, "kd_down": 0, "error_detail": None}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.naver.com/'
    }
    success = False
    
    # [Fallback 1] 네이버 모바일 API (JSON 직결)
    try:
        res_kp = requests.get("https://m.stock.naver.com/api/index/KOSPI/price", headers=headers, timeout=3)
        res_kd = requests.get("https://m.stock.naver.com/api/index/KOSDAQ/price", headers=headers, timeout=3)
        if res_kp.status_code == 200 and res_kd.status_code == 200:
            b_data["kp_up"] = res_kp.json().get("riseFall", {}).get("rise", 0)
            b_data["kp_down"] = res_kp.json().get("riseFall", {}).get("fall", 0)
            b_data["kd_up"] = res_kd.json().get("riseFall", {}).get("rise", 0)
            b_data["kd_down"] = res_kd.json().get("riseFall", {}).get("fall", 0)
            if (b_data["kp_up"] + b_data["kp_down"]) > 0: success = True
    except Exception: pass
    
    # [Fallback 2] 네이버 DOM 직접 파싱 (API 실패 시)
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
                    val_match = re.search(r'[\d,]+', dd.get_text())
                    val = int(val_match.group().replace(",", "")) if val_match else 0
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
                    val_match = re.search(r'[\d,]+', dd.get_text())
                    val = int(val_match.group().replace(",", "")) if val_match else 0
                    if "상승" in txt: b_data["kd_up"] = val
                    elif "하락" in txt: b_data["kd_down"] = val
            if (b_data["kp_up"] + b_data["kp_down"]) > 0: success = True
        except Exception as e:
            b_data["error_detail"] = f"DOM Fail: {str(e)[:20]}"

    # [Fallback 3] 최후의 보루: 캐시 재사용 (KRX 차단 리스크 배제)
    if not success:
        if _breadth_cache["data"] is not None:
            cached_data = _breadth_cache["data"]
            cached_data["error_detail"] = "Using Stale Cache (Network/API Failed)"
            return cached_data
        else:
            return {"kp_up": 0, "kp_down": 0, "kd_up": 0, "kd_down": 0, "kp_ratio": 50.0, "kd_ratio": 50.0, "avg_ratio": 50.0, "trend": "Unknown", "error_detail": "All Scrapers Blocked"}

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
    
    try:
        kospi = fdr.DataReader("KS11", start_date)
        kosdaq = fdr.DataReader("KQ11", start_date)
        
        kp_1d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-2]) - 1) * 100
        kd_1d = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-2]) - 1) * 100
        
        kp_5d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-6]) - 1) * 100 if len(kospi) >= 6 else 0
        kd_5d = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-6]) - 1) * 100 if len(kosdaq) >= 6 else 0
        
        kp_20d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-21]) - 1) * 100 if len(kospi) >= 21 else 0
        kd_20d = ((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-21]) - 1) * 100 if len(kosdaq) >= 21 else 0
        
        breadth = get_realtime_breadth()
        
        if breadth.get("trend") == "Unknown" and kp_1d > -1.5: state = "UNKNOWN_HOLD" 
        elif kp_1d <= -3.0: state = "CRASH"
        elif kp_1d <= -1.5: state = "RISK"
        elif kp_1d >= 1.0 and breadth.get("trend") == "Improving": state = "BULL"
        else: state = "NORMAL"
        
        return {
            "state": state, 
            "kospi_1d": round(kp_1d, 2), "kospi_5d": round(kp_5d, 2), "kospi_20d": round(kp_20d, 2),
            "kosdaq_1d": round(kd_1d, 2), "kosdaq_5d": round(kd_5d, 2), "kosdaq_20d": round(kd_20d, 2),
            "breadth": breadth
        }
    except Exception as e:
        return {
            "state": "UNKNOWN_ERROR", 
            "kospi_1d": 0.0, "kospi_5d": 0.0, "kospi_20d": 0.0,
            "kosdaq_1d": 0.0, "kosdaq_5d": 0.0, "kosdaq_20d": 0.0,
            "breadth": {"avg_ratio": 50.0, "trend": "Unknown", "error_detail": f"FDR Error: {str(e)}"}
        }
