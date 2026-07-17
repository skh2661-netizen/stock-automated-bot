import datetime
import pytz
import FinanceDataReader as fdr
import requests
from bs4 import BeautifulSoup
import time
import re
import logging

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False

_breadth_cache = {"timestamp": 0, "data": None}

def get_realtime_breadth():
    global _breadth_cache
    current_time = time.time()
    
    b_data = {"kp_up": 0, "kp_down": 0, "kp_same": 0, "kd_up": 0, "kd_down": 0, "kd_same": 0}
    diag = {"API": "FAIL", "DOM": "FAIL", "FDR": "FAIL", "YAHOO": "OFF" if not YF_AVAILABLE else "FAIL", "CACHE": "NO"}
    source_used = "NONE"
    success = False
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    # 1. API (리스트/딕셔너리 동적 파싱)
    try:
        res_kp = requests.get("https://m.stock.naver.com/api/index/KOSPI/price", headers=headers, timeout=3)
        res_kd = requests.get("https://m.stock.naver.com/api/index/KOSDAQ/price", headers=headers, timeout=3)
        if res_kp.status_code == 200 and res_kd.status_code == 200:
            data_kp, data_kd = res_kp.json(), res_kd.json()
            # 👑 네이버 API 배열 반환 버그 대응
            if isinstance(data_kp, list) and len(data_kp) > 0: data_kp = data_kp[0]
            if isinstance(data_kd, list) and len(data_kd) > 0: data_kd = data_kd[0]
            
            kp_rf, kd_rf = data_kp.get("riseFall", {}), data_kd.get("riseFall", {})
            b_data["kp_up"], b_data["kp_down"], b_data["kp_same"] = int(kp_rf.get("rise",0)), int(kp_rf.get("fall",0)), int(kp_rf.get("same",0))
            b_data["kd_up"], b_data["kd_down"], b_data["kd_same"] = int(kd_rf.get("rise",0)), int(kd_rf.get("fall",0)), int(kd_rf.get("same",0))
            if (b_data["kp_up"] + b_data["kp_down"]) > 0: 
                success, source_used, diag["API"] = True, "NAVER API", "PASS"
    except Exception as e: logging.warning(f"Breadth API Fail: {e}")
    
    # 2. DOM
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
                success, source_used, diag["DOM"] = True, "NAVER DOM", "PASS"
        except Exception as e: logging.warning(f"Breadth DOM Fail: {e}")

    # 3. FDR KRX
    if not success:
        try:
            krx = fdr.StockListing('KRX')
            if 'ChangesRatio' not in krx.columns and 'ChagesRatio' in krx.columns:
                krx.rename(columns={'ChagesRatio': 'ChangesRatio'}, inplace=True)
            if 'ChangesRatio' in krx.columns:
                b_data["kp_up"] = len(krx[(krx['Market'] == 'KOSPI') & (krx['ChangesRatio'] > 0)])
                b_data["kp_down"] = len(krx[(krx['Market'] == 'KOSPI') & (krx['ChangesRatio'] < 0)])
                b_data["kp_same"] = len(krx[(krx['Market'] == 'KOSPI') & (krx['ChangesRatio'] == 0)])
                b_data["kd_up"] = len(krx[(krx['Market'] == 'KOSDAQ') & (krx['ChangesRatio'] > 0)])
                b_data["kd_down"] = len(krx[(krx['Market'] == 'KOSDAQ') & (krx['ChangesRatio'] < 0)])
                b_data["kd_same"] = len(krx[(krx['Market'] == 'KOSDAQ') & (krx['ChangesRatio'] == 0)])
                if (b_data["kp_up"] + b_data["kp_down"]) > 0: 
                    success, source_used, diag["FDR"] = True, "FDR KRX", "PASS"
        except Exception as e: logging.warning(f"Breadth FDR Fail: {e}")

    # 4. YAHOO & CACHE
    if not success and YF_AVAILABLE:
        try:
            yf_kp = yf.Ticker("^KS11").history(period="1d")
            if not yf_kp.empty:
                success, source_used, diag["YAHOO"] = True, "YAHOO (Index Only)", "PASS"
        except Exception: pass
        
    if not success and _breadth_cache["data"] is not None:
        b_data = _breadth_cache["data"].copy()
        success, source_used, diag["CACHE"] = True, "CACHE", "PASS"

    total_up = b_data["kp_up"] + b_data["kd_up"]
    total_all = total_up + b_data["kp_down"] + b_data["kd_down"]
    b_data["up_ratio"] = round((total_up / total_all) * 100, 1) if total_all > 0 else 50.0
    
    if b_data["up_ratio"] >= 55.0: b_data["trend"] = "Improving"
    elif b_data["up_ratio"] <= 45.0: b_data["trend"] = "Weakening"
    else: b_data["trend"] = "Flat"
    
    if success: _breadth_cache = {"timestamp": current_time, "data": b_data}
    
    return b_data, diag, source_used

def get_market_context():
    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    breadth, diag, source_used = get_realtime_breadth()
    
    is_fdr_ok = False
    kp_1d, kp_5d, kp_20d, kd_1d, kd_5d, kd_20d = [0.0]*6
    
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
            diag["FDR Index"] = "PASS"
        else: diag["FDR Index"] = "FAIL"
    except Exception as e:
        diag["FDR Index"] = "FAIL"
        logging.error(f"FDR Index Failed: {e}")

    quality_score = 0
    if is_fdr_ok: quality_score += 40
    if diag["API"] == "PASS" or diag["DOM"] == "PASS": quality_score += 60
    elif diag["FDR"] == "PASS": quality_score += 40
    elif diag["CACHE"] == "PASS": quality_score += 20
    
    is_crash = False
    if kp_1d <= -3.0 and breadth.get("up_ratio", 50) < 35 and kp_20d < -5.0:
        is_crash = True
        
    if quality_score == 0: state = "UNKNOWN_HOLD"
    elif is_crash: state = "CRASH"
    elif kp_1d <= -1.5 or breadth.get("up_ratio", 50) < 40: state = "RISK"
    elif quality_score <= 40: state = "CAUTION"
    elif kp_1d >= 1.0 and breadth.get("trend") == "Improving": state = "BULL"
    else: state = "NORMAL"
        
    return {
        "state": state, "data_quality": f"{quality_score}%", "diag": diag, "source": source_used,
        "kospi_1d": round(kp_1d, 2), "kospi_5d": round(kp_5d, 2), "kospi_20d": round(kp_20d, 2),
        "kosdaq_1d": round(kd_1d, 2), "kosdaq_5d": round(kd_5d, 2), "kosdaq_20d": round(kd_20d, 2),
        "breadth": breadth
    }
