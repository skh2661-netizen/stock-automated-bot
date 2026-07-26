import datetime
import logging
import FinanceDataReader as fdr
import pandas as pd

_logger = logging.getLogger(__name__)

def get_market_context() -> dict:
    _logger.info("시장 상태(KOSPI/KOSDAQ 및 Breadth) 분석 중...")
    try:
        start_date = (datetime.datetime.now() - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
        kospi = fdr.DataReader("KS11", start_date)
        kosdaq = fdr.DataReader("KQ11", start_date)
        
        kospi_1d = round((kospi['Close'].iloc[-1] / kospi['Close'].iloc[-2] - 1) * 100, 2)
        kosdaq_1d = round((kosdaq['Close'].iloc[-1] / kosdaq['Close'].iloc[-2] - 1) * 100, 2)
        
        kospi_20ma = kospi['Close'].rolling(window=20).mean().iloc[-1]
        kosdaq_20ma = kosdaq['Close'].rolling(window=20).mean().iloc[-1]
        
        current_kospi = kospi['Close'].iloc[-1]
        current_kosdaq = kosdaq['Close'].iloc[-1]

        # 실제 KRX 데이터로 Breadth 계산
        total_up, total_down, total_same = 0, 0, 0
        advance_ratio = 50.0
        try:
            krx = fdr.StockListing('KRX')
            
            # [디버그 로그] 실제 받아온 컬럼 목록과 Row 수 확인
            _logger.info(f"[DEBUG Breadth] KRX Rows: {len(krx)}")
            _logger.info(f"[DEBUG Breadth] KRX Columns: {krx.columns.tolist()}")
            
            # [핵심 패치] FDR 버전별 오타 및 다양한 컬럼명 모두 대응
            possible_cols = ['ChangesRatio', 'ChagesRatio', 'Change', 'Changes', 'Chg', '등락률', 'FLUC_RT']
            c = next((col for col in possible_cols if col in krx.columns), None)
            
            _logger.info(f"[DEBUG Breadth] Selected Change Column: {c}")

            if c and not krx.empty:
                krx[c] = pd.to_numeric(krx[c], errors='coerce').fillna(0)
                noise_filter = '스팩|우$|우B|우C|ETF|ETN|리츠|선박투자|인버스|레버리지|KODEX|TIGER|ACE|SOL|HANARO|TIMEFOLIO|PLUS|KOSEF|ARIRANG|KBSTAR|RISE'
                if 'Name' in krx.columns:
                    krx = krx[~krx['Name'].str.contains(noise_filter, regex=True, na=False)]

                total_up = int((krx[c] > 0).sum())
                total_down = int((krx[c] < 0).sum())
                total_same = int((krx[c] == 0).sum())

                # 형님이 알려주신 간소화 공식
                advance_ratio = round((100.0 * total_up) / max(total_up + total_down, 1), 1)
            else:
                _logger.warning("[DEBUG Breadth] 등락률 컬럼을 찾지 못해 계산을 스킵합니다. (0 반환)")
                
        except Exception as e:
            _logger.warning(f"Breadth 수집 실패 (기본값 사용): {e}")
        
        if current_kospi < kospi_20ma and current_kosdaq < kosdaq_20ma:
            if kospi_1d < -1.5 or kosdaq_1d < -1.5:
                state = "CRASH" 
                allow_scan = False
                score = 20
            else:
                state = "WEAK" 
                allow_scan = True
                score = 40
        elif current_kospi > kospi_20ma and current_kosdaq > kosdaq_20ma:
            state = "NORMAL" 
            allow_scan = True
            score = 80
        else:
            state = "CAUTION" 
            allow_scan = True
            score = 60

        return {
            "state": state,
            "score": score,
            "kospi_1d": kospi_1d,
            "kosdaq_1d": kosdaq_1d,
            "allow_scan": allow_scan,
            "source": "FDR (KS11, KQ11, KRX)",
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
            "source": "ERROR",
            "reason": "데이터 수집 에러",
            "total_up": 0, "total_down": 0, "total_same": 0, "advance_ratio": 0.0
        }
