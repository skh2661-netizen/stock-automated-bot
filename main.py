import sys
import pytz
import asyncio
from datetime import datetime
from scanner import scan_market
from database import get_today_candidates, mark_telegram_sent, save_log
from telegram_bot import send_message, format_scan_message

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
        print("작전 시간 아님")
        return

    print(f"🎯 작전 모드: {mode} 실행 중...")
    
    try:
        # REVIEW 모드인데 함수가 없으면 일단 스킵하고 로그만 기록
        if mode == "REVIEW":
            print("복기 모드 실행 (함수 없음, 스킵)")
            return

        scan_result = await scan_market(run_type=mode)
        candidates = get_today_candidates()

        if candidates:
            msg = format_scan_message({
                "market": scan_result.get("market", {}),
                "stats": scan_result.get("stats", {}),
                "candidates": candidates
            })
            await send_message(msg)
            mark_telegram_sent([c["unique_key"] for c in candidates])
            print("발송 및 DB 마킹 완료")
        else:
            print("발송할 후보 없음")
            
    except Exception as e:
        print(f"작전 오류: {e}")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_pipeline())
