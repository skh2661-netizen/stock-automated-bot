import FinanceDataReader as fdr
import logging  # [추가] 로깅 모듈 임포트

def get_market_risk(start_date):
    try:
        kospi = fdr.DataReader("KS11", start_date)
        if len(kospi) < 6: 
            return {"level": 1, "change": 0, "message": "⚠️ 데이터 부족 (안전 모드)"}
            
        c = (kospi["Close"].iloc[-1] / kospi["Close"].iloc[-6] - 1) * 100
        
        if c <= -3: 
            return {"level": 2, "change": round(c, 2), "message": "🚨 폭락 위험 (진입 통제)"}
        elif c <= -1.5: 
            return {"level": 1, "change": round(c, 2), "message": "⚠️ 시장 주의 (보수적 진입)"}
            
        return {"level": 0, "change": round(c, 2), "message": "✅ 정상"}
        
    except Exception as e: 
        # [핵심 수정 3] 장애 발생 시 침묵(Silence) 방지 및 Warning 로깅
        logging.warning(f"Market risk fetch failed: {e}")
        # 핵심 수정: 데이터 오류 시 정상장(0)으로 판단하는 리스크 원천 차단
        return {"level": 1, "change": 0, "message": "⚠️ API 오류 (안전 모드 작동)"}
