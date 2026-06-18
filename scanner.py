import FinanceDataReader as fdr
import pandas as pd
import asyncio, time
from scoring import calculate_score
from risk import get_market_risk
from database import save_candidate

# 기존 MIN_PRICE 등 설정 유지
MIN_PRICE, MIN_AMOUNT, MAX_CANDIDATES = 2000, 10_000_000_000, 10

# ... get_krx_retry() 및 remove_bad_targets() 기존 함수 완벽 유지 ...

async def scan_market(run_type="OPEN_SCAN"):
    # ... (데이터 로딩 및 필터링) ...
    # 핵심: 거래대금 상위 정렬 복구
    candidates = krx[(krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & 
                     (krx['ChangesRatio'] >= 3) & (krx['ChangesRatio'] <= 18)].sort_values("Amount", ascending=False).head(100)
    
    results = []
    for _, row in candidates.iterrows():
        # [V8.5 전술 필터 레이어: 기존 구조 위에 삽입]
        changes = float(row['ChangesRatio'])
        if run_type == "PRE_OPEN" and not (0 <= changes <= 7): continue
        if run_type == "BREAKOUT_1" and not (3 <= changes <= 12): continue
        if run_type == "CLOSE_BET" and not (1 <= changes <= 5): continue
        
        # [기존 로직 유지 및 지표 계산]
        # (이 부분에 hist, curr, ma20, rs 계산 로직 기존 원본 그대로 유지)
        
        # [무결성 수정: 점수 상한 100]
        score = min(int(calculate_score(...)), 100)
        
        # [기존 데이터 계약(Contract) 완벽 복구]
        buy_p = int(curr['Close'] * 0.985)
        t1 = int(curr['Close'] * 1.023)
        t2 = int(curr['Close'] * 1.063)
        stop = int(curr['Close'] * 0.970)
        
        save_candidate(run_type, code, row['Name'], score, buy_p, t1, t2, stop, 
                       int(curr['Close']), round(changes,2), round(ma_gap,2), round(rs,2), 0,0,0,0,0,0,0,0)
        
        results.append({
            "code": code, "name": row['Name'], "score": score, "price": int(curr['Close']),
            "chg": round(changes, 2), "buy_p": buy_p, "target_1": t1, "target_2": t2, "stop_p": stop,
            "ma_gap": round(ma_gap, 2), "rs": round(rs, 2)
        })
    return {"candidates": results}
