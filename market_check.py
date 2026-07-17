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
    
    b_data = {"kp_up": 0, "kp_down": 0, "kp_same": 0, "kd_up": 0, "kd_down": 0, "kd_same": 0, "is_ok": False}
    source_used = "NONE"
    success = False
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    # [1] 네이버 API
    try:
        res_kp = requests.get("https://m.stock.naver.com/api/index/KOSPI/price", headers=headers, timeout=3)
        res_kd = requests.get("https://m.stock.naver.com/api/index/KOSDAQ/price", headers=headers, timeout=3)
        if res_kp.status_code == 200 and res_kd.status_code == 200:
            data_kp, data_kd = res_kp.json(), res_kd.json()
            if isinstance(data_kp, list) and len(data_kp) > 0: data_kp = data_kp[0]
            if isinstance(data_kd, list) and len(data_kd) > 0: data_kd = data_kd[0]
            
            kp_rf, kd_rf = data_kp.get("riseFall", {}), data_kd.get("riseFall", {})
            b_data["kp_up"], b_data["kp_down"], b_data["kp_same"] = int(kp_rf.get("rise",0)), int(kp_rf.get("fall",0)), int(kp_rf.get("same",0))
            b_data["kd_up"], b_data["kd_down"], b_data["kd_same"] = int(kd_rf.get("rise",0)), int(kd_rf.get("fall",0)), int(kd_rf.get("same",0))
            if (b_data["kp_up"] + b_data["kp_down"]) > 0: 
                success, source_used = True, "네이버"
    except Exception as e: logging.info(f"[Market] API Fetch Failed: {e}")
    
    # [2] 네이버 DOM
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
                success, source_used = True, "네이버"
        except Exception as e: logging.info(f"[Market] DOM Fetch Failed: {e}")

    # [3] 한국거래소(FDR)
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
                    success, source_used = True, "한국거래소(FDR)"
        except Exception as e: logging.info(f"[Market] FDR Fetch Failed: {e}")

    # [4] YAHOO & CACHE (Fallback)
    if not success and YF_AVAILABLE:
        try:
            yf_kp = yf.Ticker("^KS11").history(period="1d")
            if not yf_kp.empty:
                success, source_used = True, "YAHOO (지수만)"
        except Exception: pass
        
    if not success and _breadth_cache["data"] is not None:
        b_data = _breadth_cache["data"].copy()
        success, source_used = True, "캐시"

    total_up = b_data["kp_up"] + b_data["kd_up"]
    total_down = b_data["kp_down"] + b_data["kd_down"]
    total_all = total_up + total_down
    b_data["up_ratio"] = round((total_up / total_all) * 100, 1) if total_all > 0 else 50.0
    
    if b_data["up_ratio"] >= 55.0: b_data["trend"] = "Improving"
    elif b_data["up_ratio"] <= 45.0: b_data["trend"] = "Weakening"
    else: b_data["trend"] = "Flat"
    
    b_data["is_ok"] = success and total_all > 0
    if success: _breadth_cache = {"timestamp": current_time, "data": b_data}
    
    return b_data, source_used

def get_market_context():
    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    breadth, source_used = get_realtime_breadth()
    
    is_fdr_ok = False
    kp_1d, kp_5d, kp_20d, kd_1d, kd_5d, kd_20d = [0.0]*6
    
    try:
        kospi = fdr.DataReader("KS11", start_date)
        kosdaq = fdr.DataReader("KQ11", start_date)
        if len(kospi) >= 21 and len(kosdaq) >= 21:
            kp_1d = round(((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-2]) - 1) * 100, 2)
            kd_1d = round(((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-2]) - 1) * 100, 2)
            kp_5d = round(((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-6]) - 1) * 100, 2)
            kd_5d = round(((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-6]) - 1) * 100, 2)
            kp_20d = round(((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-21]) - 1) * 100, 2)
            kd_20d = round(((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-21]) - 1) * 100, 2)
            is_fdr_ok = True
    except Exception as e:
        logging.error(f"[Market] FDR Index Failed: {e}")

    # 👑 데이터 품질 연산 (지수 30 + 상승비율 40 + 출처 30/10)
    quality_score = 0
    if is_fdr_ok: quality_score += 30
    if breadth["is_ok"]: quality_score += 40
    
    if source_used in ["네이버", "한국거래소(FDR)"]: quality_score += 30
    elif source_used == "캐시": quality_score += 10
    
    # 종합 시장 국면 판정
    is_crash = False
    if kp_1d <= -3.0 and breadth.get("up_ratio", 50) < 35 and kp_20d < -5.0:
        is_crash = True
        
    if quality_score < 30: state = "UNKNOWN_HOLD"
    elif is_crash: state = "CRASH"
    elif kp_1d <= -1.5 or breadth.get("up_ratio", 50) < 40: state = "RISK"
    elif quality_score <= 50: state = "CAUTION"
    elif kp_1d >= 1.0 and breadth.get("trend") == "Improving": state = "BULL"
    else: state = "NORMAL"
        
    return {
        "state": state, "data_quality": quality_score, "source": source_used, "fdr_ok": is_fdr_ok,
        "kospi_1d": kp_1d, "kospi_5d": kp_5d, "kospi_20d": kp_20d,
        "kosdaq_1d": kd_1d, "kosdaq_5d": kd_5d, "kosdaq_20d": kd_20d,
        "breadth": breadth
    }
