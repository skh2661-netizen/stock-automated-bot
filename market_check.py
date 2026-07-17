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
    """1. 지수 데이터 수집 및 등락률 검증 연산"""
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
            idx_data["error"] = "데이터 행(Row) 부족 (21일 미만)"
    except Exception as e:
        idx_data["error"] = f"{type(e).__name__}: {str(e)[:30]}"
        
    return idx_data

def load_breadth():
    """2. 상승/하락/보합 데이터 수집 및 구성 요소 분해"""
    global _breadth_cache
    current_time = time.time()
    
    b_data = {
        "success": False, "source": "NONE",
        "kp_up": 0, "kp_down": 0, "kp_same": 0, 
        "kd_up": 0, "kd_down": 0, "kd_same": 0, 
        "fdr_total": 0, "fdr_kp": 0, "fdr_kd": 0, "fdr_konex": 0, "fdr_others": 0,
        "diag": {
            "API": {"status": "FAIL", "error": ""},
            "DOM": {"status": "FAIL", "error": ""},
            "FDR": {"status": "FAIL", "error": ""},
            "YAHOO": {"status": "OFF" if not YF_AVAILABLE else "FAIL", "error": ""},
            "CACHE": {"status": "NO", "age": 0}
        }
    }
    
    if _breadth_cache["data"] is not None:
        b_data["diag"]["CACHE"]["age"] = int(current_time - _breadth_cache["timestamp"])
        
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
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
                else: raise ValueError("Selector 'lst_kos_info' 누락")
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
                konex_df = krx[krx['Market'] == 'KONEX']
                
                b_data["fdr_kp"] = len(kpi_df)
                b_data["fdr_kd"] = len(kdq_df)
                b_data["fdr_konex"] = len(konex_df)
                b_data["fdr_others"] = b_data["fdr_total"] - (b_data["fdr_kp"] + b_data["fdr_kd"] + b_data["fdr_konex"])
                
                b_data["kp_up"] = len(kpi_df[kpi_df['ChangesRatio'] > 0])
                b_data["kp_down"] = len(kpi_df[kpi_df['ChangesRatio'] < 0])
                b_data["kp_same"] = len(kpi_df[kpi_df['ChangesRatio'] == 0])
                
                b_data["kd_up"] = len(kdq_df[kdq_df['ChangesRatio'] > 0])
                b_data["kd_down"] = len(kdq_df[kdq_df['ChangesRatio'] < 0])
                b_data["kd_same"] = len(kdq_df[kdq_df['ChangesRatio'] == 0])
                
                if (b_data["kp_up"] + b_data["kp_down"]) > 0:
                    b_data["success"], b_data["source"], b_data["diag"]["FDR"]["status"] = True, "한국거래소(FDR)", "PASS"
            else: raise ValueError("ChangesRatio 칼럼 누락")
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
        b_data["success"], b_data["source"], b_data["diag"]["CACHE"]["status"] = True, "캐시", "USED"

    if b_data["success"] and b_data["source"] != "캐시":
        _breadth_cache = {"timestamp": current_time, "data": b_data.copy()}

    return b_data

def calculate_up_ratio(b_data):
    """3. 상승 종목 비율 및 일관성 계산식 적용"""
    b_data["total_up"] = b_data["kp_up"] + b_data["kd_up"]
    b_data["total_down"] = b_data["kp_down"] + b_data["kd_down"]
    b_data["total_same"] = b_data["kp_same"] + b_data["kd_same"]
    
    b_data["actual_sum"] = b_data["total_up"] + b_data["total_down"] + b_data["total_same"]
    
    if b_data["source"] == "한국거래소(FDR)":
        b_data["expected_sum"] = b_data["fdr_kp"] + b_data["fdr_kd"]
    else:
        # 네이버의 경우 전체 종목수를 주지 않으므로 합계를 기대값으로 간주
        b_data["expected_sum"] = b_data["actual_sum"]
        
    b_data["missing"] = b_data["expected_sum"] - b_data["actual_sum"] if b_data["expected_sum"] >= b_data["actual_sum"] else 0
    
    total_valid = b_data["total_up"] + b_data["total_down"]
    if total_valid > 0:
        b_data["up_ratio"] = round((b_data["total_up"] / total_valid) * 100, 1)
    else:
        b_data["up_ratio"] = 0.0
        
    if b_data["up_ratio"] >= 55.0: b_data["trend"] = "Improving"
    elif b_data["up_ratio"] > 0 and b_data["up_ratio"] <= 45.0: b_data["trend"] = "Weakening"
    else: b_data["trend"] = "Flat"
    
    return b_data

def calculate_quality(idx_data, b_data):
    """4. 100점 만점의 데이터 품질(Validation) 산정식"""
    q_data = {
        "idx_pass": False, "idx_score": 0,
        "brd_pass": False, "brd_score": 0,
        "consist_pass": False, "consist_score": 0,
        "calc_pass": False, "calc_score": 0,
        "src_pass": False, "src_score": 0,
        "total": 0, "validation_pass": False, "reason": ""
    }
    
    # [Index] 20점
    if idx_data["success"]: q_data["idx_pass"], q_data["idx_score"] = True, 20
    else: q_data["reason"] = f"Index Fail: {idx_data.get('error')}"
        
    # [Breadth] 20점
    if b_data["success"]: q_data["brd_pass"], q_data["brd_score"] = True, 20
    else: 
        if not q_data["reason"]: q_data["reason"] = "Breadth Fetch Fail"
        
    # [Consistency] 20점 (오차 허용치 0)
    if b_data["actual_sum"] > 0 and b_data["missing"] == 0:
        q_data["consist_pass"], q_data["consist_score"] = True, 20
    else:
        if not q_data["reason"]: q_data["reason"] = f"Consistency Fail (Missing {b_data['missing']})"
        
    # [Calculation] 20점 (0으로 나누기 방지)
    if b_data["up_ratio"] > 0:
        q_data["calc_pass"], q_data["calc_score"] = True, 20
    else:
        if not q_data["reason"]: q_data["reason"] = "Calculation Fail (Zero Div)"
        
    # [Source] 20점
    if b_data["source"] in ["NAVER API", "NAVER DOM", "한국거래소(FDR)"]:
        q_data["src_pass"], q_data["src_score"] = True, 20
    elif b_data["source"] == "캐시":
        q_data["src_score"] = 10
        if not q_data["reason"]: q_data["reason"] = "Using Cache"
    else:
        if not q_data["reason"]: q_data["reason"] = "Source NONE"
        
    q_data["total"] = sum([q_data["idx_score"], q_data["brd_score"], q_data["consist_score"], q_data["calc_score"], q_data["src_score"]])
    
    if q_data["total"] == 100:
        q_data["validation_pass"], q_data["reason"] = True, "All Clear"
        
    return q_data

def validation_log(idx_data, b_data, q_data):
    """5. 시장 데이터 파이프라인 검증 전용 로깅 모듈"""
    logging.info("========== SOURCE CHECK ==========")
    for src in ["API", "DOM", "FDR", "YAHOO"]:
        status = b_data["diag"][src]["status"]
        err = f" ({b_data['diag'][src]['error']})" if b_data["diag"][src]["error"] else ""
        logging.info(f"{src:<10} {status}{err}")
        
    logging.info("========== CACHE ==========")
    logging.info(f"USED : {b_data['diag']['CACHE']['status']}")
    if b_data['diag']['CACHE']['age'] > 0:
        logging.info(f"Age  : {b_data['diag']['CACHE']['age']} sec")

    logging.info("========== INDEX VALIDATION ==========")
    logging.info(f"KOSPI  | Today Close: {idx_data['kp_today']:<8} | Prev Close: {idx_data['kp_prev']:<8} | Return: {idx_data['kp_1d']}%")
    logging.info(f"KOSDAQ | Today Close: {idx_data['kd_today']:<8} | Prev Close: {idx_data['kd_prev']:<8} | Return: {idx_data['kd_1d']}%")
    
    logging.info("========== MARKET BREAKDOWN ==========")
    if b_data["source"] == "한국거래소(FDR)":
        logging.info(f"KRX Total : {b_data.get('fdr_total', 0)}")
        logging.info(f"KOSPI     : {b_data.get('fdr_kp', 0)}")
        logging.info(f"KOSDAQ    : {b_data.get('fdr_kd', 0)}")
        logging.info(f"KONEX     : {b_data.get('fdr_konex', 0)}")
        logging.info(f"Others    : {b_data.get('fdr_others', 0)}")
    else:
        logging.info(f"Breakdown Unavailable (Using {b_data['source']})")
        
    logging.info("========== BREADTH ==========")
    logging.info(f"KOSPI  | UP: {b_data['kp_up']:<4} | DOWN: {b_data['kp_down']:<4} | FLAT: {b_data['kp_same']:<4} | SUM: {b_data['kp_up']+b_data['kp_down']+b_data['kp_same']}")
    logging.info(f"KOSDAQ | UP: {b_data['kd_up']:<4} | DOWN: {b_data['kd_down']:<4} | FLAT: {b_data['kd_same']:<4} | SUM: {b_data['kd_up']+b_data['kd_down']+b_data['kd_same']}")
    logging.info("-" * 30)
    logging.info(f"TOTAL  | UP: {b_data['total_up']:<4} | DOWN: {b_data['total_down']:<4} | FLAT: {b_data['total_same']:<4} | SUM: {b_data['actual_sum']}")
    
    logging.info("========== MARKET CONSISTENCY CHECK ==========")
    logging.info(f"Expected Total   : {b_data['expected_sum']}")
    logging.info(f"Breadth Total    : {b_data['actual_sum']}")
    logging.info(f"Missing Symbols  : {b_data['missing']}")
    logging.info(f"Validation       : {'PASS' if q_data['consist_pass'] else 'FAIL'}")
    
    logging.info("========== UP RATIO ==========")
    logging.info(f"UP RATIO : {b_data['total_up']} / ({b_data['total_up']} + {b_data['total_down']}) = {b_data['up_ratio']}%")
    
    logging.info("========== QUALITY SCORE ==========")
    logging.info(f"Index        {'PASS' if q_data['idx_pass'] else 'FAIL':<4}  {q_data['idx_score']}")
    logging.info(f"Breadth      {'PASS' if q_data['brd_pass'] else 'FAIL':<4}  {q_data['brd_score']}")
    logging.info(f"Consistency  {'PASS' if q_data['consist_pass'] else 'FAIL':<4}  {q_data['consist_score']}")
    logging.info(f"Calculation  {'PASS' if q_data['calc_pass'] else 'FAIL':<4}  {q_data['calc_score']}")
    logging.info(f"Source       {'PASS' if q_data['src_pass'] else 'FAIL':<4}  {q_data['src_score']}")
    logging.info(f"TOTAL SCORE : {q_data['total']}")
    logging.info(f"FINAL VALIDATION : {'PASS' if q_data['validation_pass'] else 'FAIL'} ({q_data['reason']})")
    logging.info("===================================")

def get_market_context():
    """메인 오케스트레이터: 수집 -> 연산 -> 품질 평가 -> 로깅 -> 상태 반환"""
    idx_data = load_index()
    b_data = load_breadth()
    b_data = calculate_up_ratio(b_data)
    q_data = calculate_quality(idx_data, b_data)
    
    validation_log(idx_data, b_data, q_data)
    
    # 👑 최상위 안전장치: 시장 데이터 검증 실패 시, 엔진 파이프라인 차단 시그널 송출
    if not q_data["validation_pass"]:
        return {
            "state": "INVALID_MARKET_DATA",
            "allow_scan": False,
            "reason": f"Market data validation failed: {q_data['reason']}",
            # 하위 모듈(Decision Engine, Telegram)의 KeyError 방지용 기본값 매핑
            "data_quality": q_data["total"], "source": b_data["source"], "diag": b_data["diag"],
            "fdr_ok": idx_data["success"],
            "kospi_1d": idx_data["kp_1d"], "kospi_5d": idx_data["kp_5d"], "kospi_20d": idx_data["kp_20d"],
            "kosdaq_1d": idx_data["kd_1d"], "kosdaq_5d": idx_data["kd_5d"], "kosdaq_20d": idx_data["kd_20d"],
            "breadth": b_data
        }
        
    # 정상 검증 통과 시의 시장 국면 판정
    is_crash = False
    if idx_data["kp_1d"] <= -3.0 and b_data["up_ratio"] < 35 and idx_data["kp_20d"] < -5.0:
        is_crash = True
        
    if is_crash: state = "CRASH"
    elif idx_data["kp_1d"] <= -1.5 or b_data["up_ratio"] < 40: state = "RISK"
    elif q_data["total"] <= 60: state = "CAUTION"
    elif idx_data["kp_1d"] >= 1.0 and b_data["trend"] == "Improving": state = "BULL"
    else: state = "NORMAL"
        
    return {
        "state": state, "allow_scan": True, "reason": "All Clear",
        "data_quality": q_data["total"], "source": b_data["source"], "diag": b_data["diag"],
        "fdr_ok": idx_data["success"],
        "kospi_1d": idx_data["kp_1d"], "kospi_5d": idx_data["kp_5d"], "kospi_20d": idx_data["kp_20d"],
        "kosdaq_1d": idx_data["kd_1d"], "kosdaq_5d": idx_data["kd_5d"], "kosdaq_20d": idx_data["kd_20d"],
        "breadth": b_data
    }
