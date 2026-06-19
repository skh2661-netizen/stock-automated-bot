import asyncio
import sys
import pytz
from datetime import datetime
from scanner import scan_market
from telegram_bot import send_message, format_scan_message
from database import mark_telegram_sent, save_log

def get_mode():
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)
    h, m = now.hour, now.minute
    if h == 8 and 35 <= m <= 59: return "PRE_OPEN"
    if h == 9 and 0 <= m <= 30: return "BREAKOUT_1"
    if (h == 10) or (h == 11 and m <= 20): return "BREAKOUT_2"
    if h == 15 and 0 <= m <= 25: return "CLOSE_BET"
    if h == 15 and 30 <= m <= 59: return "REVIEW"
    return None

async def run_pipeline():
    mode = get_mode()
    if mode is None:
        mode = "TEST" # 시간 외 테스트 모드 진입

    try:
        scan_result = await scan_market(run_type=mode)
        candidates = scan_result.get("candidates", [])

        if candidates:
            # 메시지 길이 초과 방지: 3개씩 분할 발송
            chunk_size = 3
            for i in range(0, len(candidates), chunk_size):
                chunk = candidates[i:i + chunk_size]
                chunk_result = scan_result.copy()
                chunk_result["candidates"] = chunk
                
                msg = format_scan_message(chunk_result)
                await send_message(msg)
                await asyncio.sleep(1) # 텔레그램 API 제한 방지
            
            mark_telegram_sent([c["code"] for c in candidates])
            print(f"발송 완료: {len(candidates)}건")
        else:
            print("발송할 신규 후보 없음")
            
    except Exception as e:
        print(f"작전 오류 발생 ({mode}): {str(e)}")

if __name__ == "__main__":
    asyncio.run(run_pipeline())
