import datetime
import pytz
import FinanceDataReader as fdr
import requests
from bs4 import BeautifulSoup
import time

_breadth_cache = {"timestamp": 0, "data": None}
_prev_avg_ratio = 50.0

def get_realtime_breadth():
    global _breadth_cache, _prev_avg_ratio
    current_time = time.time()
    
    if _breadth_cache["data"] is not None and (current_time - _breadth_cache["timestamp"] < 180):
        return _breadth_cache["data"]
        
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        b_data = {"kp_up": 0, "kp_down": 0, "kd_up": 0, "kd_down": 0}
        
        res_kp = requests.get("https://finance.naver.com/sise/sise_index.naver?code=KOSPI", headers=headers, timeout=3)
        soup_kp = BeautifulSoup(res_kp.text, 'html.parser')
        dl_kp = soup_kp.find("dl", class_="lst_kos_info")
        if dl_kp:
            b_data["kp_up"] = int(dl_kp.find("dt", string="상승").find_next_sibling("dd").text.strip().replace(",", ""))
            b_data["kp_down"] = int(dl_kp.find("dt", string="하락").find_next_sibling("dd").text.strip().replace(",", ""))
            
        res_kd = requests.get("https://finance.naver.com/sise/sise_index.naver?code=KOSDAQ", headers=headers, timeout=3)
        soup_kd = BeautifulSoup(res_kd.text, 'html.parser')
        dl_kd = soup_kd.find("dl", class_="lst_kos_info")
        if dl_kd:
            b_data["kd_up"] = int(dl_kd.find("dt", string="상승").find_next_sibling("dd").text.strip().replace(",", ""))
            b_data["kd_down"] = int(dl_kd.find("dt", string="하락").find_next_sibling("dd").text.strip().replace(",", ""))
            
        kp_total = max(b_data["kp_up"] + b_data["kp_down"], 1)
        kd_total = max(b_data["kd_up"] + b_data["kd_down"], 1)
        
        b_data["kp_ratio"] = round((b_data["kp_up"] / kp_total) * 100, 1)
        b_data["kd_ratio"] = round((b_data["kd_up"] / kd_total) * 100, 1)
        avg_ratio = (b_data["kp_ratio"] + b_data["kd_ratio"]) / 2
        b_data["avg_ratio"] = avg_ratio
        
        if avg_ratio > _prev_avg_ratio + 5: b_data["trend"] = "Improving"
        elif avg_ratio < _prev_avg_ratio - 5: b_data["trend"] = "Weakening"
        else: b_data["trend"] = "Flat"
        
        _prev_avg_ratio = avg_ratio
        _breadth_cache = {"timestamp": current_time, "data": b_data}
        return b_data
    except Exception:
        return {"kp_up": 0, "kp_down": 0, "kd_up": 0, "kd_down": 0, "kp_ratio": 50.0, "kd_ratio": 50.0, "avg_ratio": 50.0, "trend": "Flat"}

def get_market_context():
    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=40)).strftime("%Y-%m-%d")
    
    try:
        kospi = fdr.DataReader("KS11", start_date)
        kp_1d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-2]) - 1) * 100
        kp_5d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-6]) - 1) * 100
        kp_20d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-21]) - 1) * 100
        
        breadth = get_realtime_breadth()
        
        if kp_1d <= -3.0: state = "CRASH"
        elif kp_1d <= -1.5: state = "RISK"
        elif kp_1d >= 1.0 and breadth["avg_ratio"] >= 60: state = "BULL"
        else: state = "NORMAL"
        
        return {
            "state": state, "kospi_1d": round(kp_1d, 2), "kospi_5d": round(kp_5d, 2),
            "kospi_20d": round(kp_20d, 2), "breadth": breadth
        }
    except Exception:
        return {"state": "NORMAL", "kospi_1d": 0.0, "kospi_5d": 0.0, "kospi_20d": 0.0, "breadth": {"avg_ratio": 50.0, "trend": "Flat"}}
