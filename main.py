import sys
import pytz
import asyncio
from datetime import datetime
from scanner import scan_market
from review import review_performance  # 복기 전용 함수 임포트

async def main():
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)
    h, m = now.hour, now.minute
    
    # 5단계 모드 분기
    mode = None
    if h == 8 and 35 <= m <= 59: mode = "PRE_OPEN"
    elif h == 9 and 0 <= m <= 30: mode = "BREAKOUT_1"
    elif (h == 10) or (h == 11 and m <= 20): mode = "BREAKOUT_2"
    elif h == 15 and 0 <= m <= 25: mode = "CLOSE_BET"
    elif h == 15 and 30 <= m <= 59: mode = "REVIEW"
    
    if mode is None:
        print(f"작전 시간 아님: {h:02d}:{m:02d}")
        sys.exit()

    print(f"🎯 작전 모드: {mode}")
    
    # 흐름 분기: REVIEW는 스캐너를 타지 않고 별도 처리
    if mode == "REVIEW":
        result = review_performance()
    else:
        result = await scan_market(run_type=mode)
    
    # 결과 발송 로직(기존 함수 활용)
    # send_telegram(result, mode)

if __name__ == "__main__":
    asyncio.run(main())
