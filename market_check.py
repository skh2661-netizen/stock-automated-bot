import datetime
import logging
import FinanceDataReader as fdr

_logger = logging.getLogger(__name__)

def get_market_context() -> dict:
    _logger.info("시장 상태(KOSPI/KOSDAQ) 분석 중...")
    try:
        start_date = (datetime.datetime.now() - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
        kospi = fdr.DataReader("KS11", start_date)
        kosdaq = fdr.DataReader("KQ11", start_date)
        
        # 최근 1일 등락률
        kospi_1d = round((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-2] - 1) * 100, 2)
        kosdaq_1d = round((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-2] - 1) * 100, 2)
        
        # 20일 이동평균선 계산
        kospi_20ma = kospi['Close'].rolling(window=20).mean().iloc[-1]
        kosdaq_20ma = kosdaq['Close'].rolling(window=20).mean().iloc[-1]
        
        current_kospi = kospi['Close'].iloc[-1]
        current_kosdaq = kosdaq['Close'].iloc[-1]
        
        advance_ratio = 50.0  # (임시값 - market_report.py에서 덮어씌움)
        total_up, total_down, total_same = 0, 0, 0
        
        # 시장 상태(State) 판별 (Bull / Normal / Bear)
        if current_kospi < kospi_20ma and current_kosdaq < kosdaq_20ma:
            if kospi_1d < -1.5 or kosdaq_1d < -1.5:
                state = "CRASH" # 폭락장 (신규 매수 차단)
                allow_scan = False
                score = 20
            else:
                state = "WEAK" # 약세장 (매수 기준 엄격하게)
                allow_scan = True
                score = 40
        elif current_kospi > kospi_20ma and current_kosdaq > kosdaq_20ma:
            state = "NORMAL" # 상승장
            allow_scan = True
            score = 80
        else:
            state = "CAUTION" # 혼조세
            allow_scan = True
            score = 60

        return {
            "state": state,
            "score": score,
            "kospi_1d": kospi_1d,
            "kosdaq_1d": kosdaq_1d,
            "allow_scan": allow_scan,
            "source": "FDR (KS11, KQ11)",
            "reason": f"KOSPI 20MA({int(kospi_20ma)}) vs 현재({int(current_kospi)})",
            "total_up": total_up,
            "total_down": total_down,
            "total_same": total_same,
            "advance_ratio": advance_ratio
        }
        
    except Exception as e:
        _logger.error(f"시장 데이터 수집 실패: {e}")
        return {
            "state": "INVALID",
            "score": 0,
            "kospi_1d": 0.0,
            "kosdaq_1d": 0.0,
            "allow_scan": False,
            "reason": "데이터 수집 에러",
            "total_up": 0, "total_down": 0, "total_same": 0, "advance_ratio": 0.0
        }
