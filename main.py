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
    # [수정] 테스트를 위한 강제 진입
    if mode is None:
        print("시간 외 작동 - 테스트 모드 진입")
        mode = "CLOSE_BET"

    try:
        if mode == "REVIEW":
            print("복기 모드 실행")
            return

        scan_result = await scan_market(run_type=mode)
        candidates = scan_result.get("candidates", [])

        if candidates:
            msg = format_scan_message(scan_result)
            await send_message(msg)
            mark_telegram_sent([c["code"] for c in candidates])
            print(f"발송 완료: {len(candidates)}건")
        else:
            print("발송할 신규 후보 없음")
            
    except Exception as e:
        print(f"작전 오류 발생 ({mode}): {str(e)}")

if __name__ == "__main__":
    asyncio.run(run_pipeline())
