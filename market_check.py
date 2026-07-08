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
        
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        b_data = {"kp_up": 0, "kp_down": 0, "kd_up": 0, "kd_down": 0}
        
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
                
        kp_total = b_data["kp_up"] + b_data["kp_down"]
        kd_total = b_data["kd_up"] + b_data["kd_down"]
        
        if kp_total == 0 or kd_total == 0:
            return {
                "kp_up": 0, "kp_down": 0, "kd_up": 0, "kd_down": 0,
                "kp_ratio": 50.0, "kd_ratio": 50.0, "avg_ratio": 50.0,
                "trend": "Unknown"
            }
        
        b_data["kp_ratio"] = round((b_data["kp_up"] / kp_total) * 100, 1)
        b_data["kd_ratio"] = round((b_data["kd_up"] / kd_total) * 100, 1)
        avg_ratio = (b_data["kp_ratio"] + b_data["kd_ratio"]) / 2
        b_data["avg_ratio"] = avg_ratio
        
        if avg_ratio > _prev_avg_ratio + 3: b_data["trend"] = "Improving"
        elif avg_ratio < _prev_avg_ratio - 3: b_data["trend"] = "Weakening"
        else: b_data["trend"] = "Flat"
        
        _prev_avg_ratio = avg_ratio
        _breadth_cache = {"timestamp": current_time, "data": b_data}
        return b_data
    except Exception:
        return {"kp_up": 0, "kp_down": 0, "kd_up": 0, "kd_down": 0, "kp_ratio": 50.0, "kd_ratio": 50.0, "avg_ratio": 50.0, "trend": "Unknown"}

def get_market_context():
    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=40)).strftime("%Y-%m-%d")
    
    try:
        kospi = fdr.DataReader("KS11", start_date)
        kp_1d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-2]) - 1) * 100
        kp_5d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-6]) - 1) * 100
        kp_20d = ((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-21]) - 1) * 100
        
        breadth = get_realtime_breadth()
        
        # ✅ 형님 지시사항: 지수와 시장 체력을 결합한 입체적 국면 판정
        if kp_1d <= -3.0: 
            state = "CRASH"
        elif kp_1d <= -1.5 and breadth.get("trend") == "Weakening": 
            state = "RISK"
        elif kp_1d >= 1.0 and breadth.get("trend") == "Improving": 
            state = "BULL"
        else: 
            state = "NORMAL" # Unknown이거나 조건 미달 시 모두 방어적 NORMAL 처리
        
        print("=" * 60)
        print("KOSPI 1D :", round(kp_1d, 2))
        print("Breadth  :", breadth["avg_ratio"])
        print("Trend    :", breadth["trend"])
        print("STATE    :", state)
        print("=" * 60)
        
        return {
            "state": state, "kospi_1d": round(kp_1d, 2), "kospi_5d": round(kp_5d, 2),
            "kospi_20d": round(kp_20d, 2), "breadth": breadth
        }
    except Exception:
        return {"state": "NORMAL", "kospi_1d": 0.0, "kospi_5d": 0.0, "kospi_20d": 0.0, "breadth": {"avg_ratio": 50.0, "trend": "Unknown"}}
