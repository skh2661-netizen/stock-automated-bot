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

def load_index():
    """1. 지수 데이터 수집 및 등락률 연산"""
    kst = pytz.timezone("Asia/Seoul")
    start_date = (datetime.datetime.now(kst) - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    idx_data = {
        "success": False, "error": None,
        "kp_today": 0.0, "kp_prev": 0.0, "kp_1d": 0.0, "kp_5d": 0.0, "kp_20d": 0.0,
        "kd_today": 0.0, "kd_prev": 0.0, "kd_1d": 0.0, "kd_5d": 0.0, "kd_20d": 0.0,
    }
    
    try:
        kospi = fdr.DataReader("KS11", start_date)
        kosdaq = fdr.DataReader("KQ11", start_date)
        
        if len(kospi) >= 21 and len(kosdaq) >= 21:
            idx_data["kp_today"] = float(kospi['Close'].iloc[-1])
            idx_data["kp_prev"] = float(kospi['Close'].iloc[-2])
            idx_data["kp_1d"] = round(((idx_data["kp_today"] / idx_data["kp_prev"]) - 1) * 100, 2)
            idx_data["kp_5d"] = round(((idx_data["kp_today"] / kospi['Close'].iloc[-6]) - 1) * 100, 2)
            idx_data["kp_20d"] = round(((idx_data["kp_today"] / kospi['Close'].iloc[-21]) - 1) * 100, 2)

            idx_data["kd_today"] = float(kosdaq['Close'].iloc[-1])
            idx_data["kd_prev"] = float(kosdaq['Close'].iloc[-2])
            idx_data["kd_1d"] = round(((idx_data["kd_today"] / idx_data["kd_prev"]) - 1) * 100, 2)
            idx_data["kd_5d"] = round(((idx_data["kd_today"] / kosdaq['Close'].iloc[-6]) - 1) * 100, 2)
            idx_data["kd_20d"] = round(((idx_data["kd_today"] / kosdaq['Close'].iloc[-21]) - 1) * 100, 2)
            
            idx_data["success"] = True
        else:
            idx_data["error"] = "Insufficient Data Length"
    except Exception as e:
        idx_data["error"] = str(e)
        
    return idx_data

def load_breadth():
    """2. 상승/하락/보합 시장폭 데이터 다중 소스 수집"""
    global _breadth_cache
    current_time = time.time()
    
    b_data = {
        "success": False, "source": "NONE",
        "kp_up": 0, "kp_down": 0, "kp_same": 0, "kp_total": 0,
        "kd_up": 0, "kd_down": 0, "kd_same": 0, "kd_total": 0,
        "fdr_total": 0, "fdr_kp": 0, "fdr_kd": 0,
        "diag": {
            "API": {"status": "FAIL", "error": ""},
            "DOM": {"status": "FAIL", "error": ""},
            "FDR": {"status": "FAIL", "error": ""},
            "YAHOO": {"status": "OFF" if not YF_AVAILABLE else "FAIL", "error": ""},
            "CACHE": {"status": "NO", "age": 0}
        }
    }
    
    # 캐시 나이 확인
    if _breadth_cache["data"] is not None:
        b_data["diag"]["CACHE"]["age"] = int(current_time - _breadth_cache["timestamp"])
        
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # [1] NAVER API
    try:
        res_kp = requests.get("https://m.stock.naver.com/api/index/KOSPI/price", headers=headers, timeout=3)
        res_kd = requests.get("https://m.stock.naver.com/api/index/KOSDAQ/price", headers=headers, timeout=3)
        res_kp.raise_for_status()
        res_kd.raise_for_status()
        
        data_kp, data_kd = res_kp.json(), res_kd.json()
        if isinstance(data_kp, list) and len(data_kp) > 0: data_kp = data_kp[0]
        if isinstance(data_kd, list) and len(data_kd) > 0: data_kd = data_kd[0]
        
        kp_rf, kd_rf = data_kp.get("riseFall", {}), data_kd.get("riseFall", {})
        b_data["kp_up"], b_data["kp_down"], b_data["kp_same"] = int(kp_rf.get("rise",0)), int(kp_rf.get("fall",0)), int(kp_rf.get("same",0))
        b_data["kd_up"], b_data["kd_down"], b_data["kd_same"] = int(kd_rf.get("rise",0)), int(kd_rf.get("fall",0)), int(kd_rf.get("same",0))
        
        if (b_data["kp_up"] + b_data["kp_down"]) > 0:
            b_data["success"], b_data["source"], b_data["diag"]["API"]["status"] = True, "NAVER API", "PASS"
    except Exception as e:
        b_data["diag"]["API"]["error"] = f"{type(e).__name__}: {str(e)[:30]}"
        
    # [2] NAVER DOM
    if not b_data["success"]:
        try:
            for code, k_up, k_down, k_same in [("KOSPI", "kp_up", "kp_down", "kp_same"), ("KOSDAQ", "kd_up", "kd_down", "kd_same")]:
                res = requests.get(f"https://finance.naver.com/sise/sise_index.naver?code={code}", headers=headers, timeout=5)
                res.raise_for_status()
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
                else: raise ValueError("Selector 'lst_kos_info' missing")
            if (b_data["kp_up"] + b_data["kp_down"]) > 0:
                b_data["success"], b_data["source"], b_data["diag"]["DOM"]["status"] = True, "NAVER DOM", "PASS"
        except Exception as e:
            b_data["diag"]["DOM"]["error"] = f"{type(e).__name__}: {str(e)[:30]}"

    # [3] FDR (KRX)
    if not b_data["success"]:
        try:
            krx = fdr.StockListing('KRX')
            b_data["fdr_total"] = len(krx)
            
            if 'ChangesRatio' not in krx.columns and 'ChagesRatio' in krx.columns:
                krx.rename(columns={'ChagesRatio': 'ChangesRatio'}, inplace=True)
                
            if 'ChangesRatio' in krx.columns:
                kpi_df = krx[krx['Market'] == 'KOSPI']
                kdq_df = krx[krx['Market'] == 'KOSDAQ']
                b_data["fdr_kp"], b_data["fdr_kd"] = len(kpi_df), len(kdq_df)
                
                b_data["kp_up"] = len(kpi_df[kpi_df['ChangesRatio'] > 0])
                b_data["kp_down"] = len(kpi_df[kpi_df['ChangesRatio'] < 0])
                b_data["kp_same"] = len(kpi_df[kpi_df['ChangesRatio'] == 0])
                
                b_data["kd_up"] = len(kdq_df[kdq_df['ChangesRatio'] > 0])
                b_data["kd_down"] = len(kdq_df[kdq_df['ChangesRatio'] < 0])
                b_data["kd_same"] = len(kdq_df[kdq_df['ChangesRatio'] == 0])
                
                if (b_data["kp_up"] + b_data["kp_down"]) > 0:
                    b_data["success"], b_data["source"], b_data["diag"]["FDR"]["status"] = True, "한국거래소(FDR)", "PASS"
            else: raise ValueError("'ChangesRatio' missing")
        except Exception as e:
            b_data["diag"]["FDR"]["error"] = f"{type(e).__name__}: {str(e)[:30]}"

    # [4] YAHOO
    if not b_data["success"] and YF_AVAILABLE:
        try:
            yf_kp = yf.Ticker("^KS11").history(period="1d")
            if not yf_kp.empty: b_data["diag"]["YAHOO"]["status"] = "PASS"
        except Exception as e:
            b_data["diag"]["YAHOO"]["error"] = f"{type(e).__name__}: {str(e)[:30]}"

    # [5] CACHE
    if not b_data["success"] and _breadth_cache["data"] is not None:
        cached = _breadth_cache["data"]
        for k in ["kp_up", "kp_down", "kp_same", "kd_up", "kd_down", "kd_same"]:
            b_data[k] = cached.get(k, 0)
        b_data["success"], b_data["source"], b_data["diag"]["CACHE"]["status"] = True, "캐시", "YES"

    b_data["kp_total"] = b_data["kp_up"] + b_data["kp_down"] + b_data["kp_same"]
    b_data["kd_total"] = b_data["kd_up"] + b_data["kd_down"] + b_data["kd_same"]

    if b_data["success"] and b_data["source"] != "캐시":
        _breadth_cache = {"timestamp": current_time, "data": b_data.copy()}

    return b_data

def calculate_up_ratio(b_data):
    """3. 상승 종목 비율 계산식 적용"""
    total_up = b_data["kp_up"] + b_data["kd_up"]
    total_down = b_data["kp_down"] + b_data["kd_down"]
    total_valid = total_up + total_down
    
    b_data["total_up"] = total_up
    b_data["total_down"] = total_down
    b_data["total_same"] = b_data["kp_same"] + b_data["kd_same"]
    
    if total_valid > 0:
        b_data["up_ratio"] = round((total_up / total_valid) * 100, 1)
    else:
        b_data["up_ratio"] = 50.0
        
    if b_data["up_ratio"] >= 55.0: b_data["trend"] = "Improving"
    elif b_data["up_ratio"] <= 45.0: b_data["trend"] = "Weakening"
    else: b_data["trend"] = "Flat"
    
    return b_data

def calculate_quality(idx_data, b_data):
    """4. 데이터 품질 산정 기준 점수화"""
    q_data = {"score": 0, "idx_score": 0, "brd_score": 0, "src_score": 0}
    
    if idx_data["success"]: q_data["idx_score"] = 40
    if b_data["success"]: q_data["brd_score"] = 40
        
    src = b_data["source"]
    if src in ["NAVER API", "NAVER DOM", "한국거래소(FDR)"]: q_data["src_score"] = 20
    elif src == "캐시": q_data["src_score"] = 10
        
    q_data["score"] = q_data["idx_score"] + q_data["brd_score"] + q_data["src_score"]
    return q_data

def validation_log(idx_data, b_data, q_data):
    """5. 시장 데이터 수집 검증 강화 로깅"""
    logging.info("========== SOURCE CHECK ==========")
    for src, info in b_data["diag"].items():
        if src == "CACHE": continue
        err = f"  [{info.get('error')}]" if info.get('error') else ""
        logging.info(f"{src:<10} {info['status']}{err}")
        
    logging.info("========== CACHE ==========")
    logging.info(f"USED : {b_data['diag']['CACHE']['status']}")
    if b_data['diag']['CACHE']['age'] > 0:
        logging.info(f"Age  : {b_data['diag']['CACHE']['age']} sec")

    logging.info("========== INDEX VALIDATION ==========")
    logging.info(f"KOSPI  | Today Close : {idx_data['kp_today']:<8} | Prev Close : {idx_data['kp_prev']:<8} | Return : {idx_data['kp_1d']}%")
    logging.info(f"KOSDAQ | Today Close : {idx_data['kd_today']:<8} | Prev Close : {idx_data['kd_prev']:<8} | Return : {idx_data['kd_1d']}%")
    if idx_data["error"]: logging.error(f"Index Error: {idx_data['error']}")
    
    if b_data["source"] == "한국거래소(FDR)":
        logging.info("========== FDR VALIDATION ==========")
        logging.info(f"Total Rows : {b_data.get('fdr_total', 0)}")
        logging.info(f"KOSPI      : {b_data.get('fdr_kp', 0)}")
        logging.info(f"KOSDAQ     : {b_data.get('fdr_kd', 0)}")
        
    logging.info("========== BREADTH ==========")
    logging.info(f"KOSPI  | UP: {b_data['kp_up']:<4} | DOWN: {b_data['kp_down']:<4} | FLAT: {b_data['kp_same']:<4} | SUM: {b_data['kp_total']}")
    logging.info(f"KOSDAQ | UP: {b_data['kd_up']:<4} | DOWN: {b_data['kd_down']:<4} | FLAT: {b_data['kd_same']:<4} | SUM: {b_data['kd_total']}")
    logging.info("-" * 30)
    logging.info(f"TOTAL  | UP: {b_data['total_up']:<4} | DOWN: {b_data['total_down']:<4} | FLAT: {b_data['total_same']:<4} | SUM: {b_data['total_up']+b_data['total_down']+b_data['total_same']}")
    
    logging.info("========== UP RATIO ==========")
    log_formula = f"UP RATIO : {b_data['total_up']} / ({b_data['total_up']} + {b_data['total_down']}) = {b_data['up_ratio']}%"
    logging.info(log_formula)
    
    logging.info("========== QUALITY SCORE ==========")
    logging.info(f"Index    PASS  {q_data['idx_score']}")
    logging.info(f"Breadth  PASS  {q_data['brd_score']}")
    logging.info(f"Source   PASS  {q_data['src_score']}")
    logging.info(f"TOTAL SCORE :  {q_data['score']}")
    logging.info("===================================")

def get_market_context():
    """메인 오케스트레이터"""
    idx_data = load_index()
    b_data = load_breadth()
    b_data = calculate_up_ratio(b_data)
    q_data = calculate_quality(idx_data, b_data)
    
    # 강력한 데이터 검증 로깅 호출
    validation_log(idx_data, b_data, q_data)
    
    is_crash = False
    if idx_data["kp_1d"] <= -3.0 and b_data["up_ratio"] < 35 and idx_data["kp_20d"] < -5.0:
        is_crash = True
        
    if q_data["score"] < 40: state = "UNKNOWN_HOLD"
    elif is_crash: state = "CRASH"
    elif idx_data["kp_1d"] <= -1.5 or b_data["up_ratio"] < 40: state = "RISK"
    elif q_data["score"] <= 60: state = "CAUTION"
    elif idx_data["kp_1d"] >= 1.0 and b_data["trend"] == "Improving": state = "BULL"
    else: state = "NORMAL"
        
    return {
        "state": state, "data_quality": q_data["score"], "source": b_data["source"],
        "fdr_ok": idx_data["success"], "diag": b_data["diag"],
        "kospi_1d": idx_data["kp_1d"], "kospi_5d": idx_data["kp_5d"], "kospi_20d": idx_data["kp_20d"],
        "kosdaq_1d": idx_data["kd_1d"], "kosdaq_5d": idx_data["kd_5d"], "kosdaq_20d": idx_data["kd_20d"],
        "breadth": b_data
    }
