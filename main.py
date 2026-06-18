import asyncio
import sys
import pytz
from datetime import datetime
from scanner import scan_market
from telegram_bot import send_message, format_scan_message
from database import get_today_candidates, mark_telegram_sent, save_log

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
    # [수정] 테스트 모드 강제 실행
    if mode is None:
        mode = "TEST"
        print("시간 외 작동 - 테스트 모드 진입")

    try:
        print(f"작전 개시: {mode} 모드 시장 스캔 중...")
        if mode == "REVIEW":
            print("복기 모드 실행")
            return

        scan_result = await scan_market(run_type=mode)
        save_log(mode, "스캔 완료")
        candidates = scan_result.get("candidates", [])

        if candidates:
            print(f"신규 발송 대상 {len(candidates)}건 발견")
            msg = format_scan_message(scan_result)
            await send_message(msg)
            mark_telegram_sent([c["code"] for c in candidates])
            print("발송 및 DB 마킹 완료")
            save_log(mode, f"{len(candidates)}건 발송 완료")
        else:
            print("발송할 신규 후보 없음")
            save_log(mode, "신규 후보 없음")
    except Exception as e:
        error_msg = f"작전 오류 발생 ({mode}): {str(e)}"
        print(error_msg)
        save_log("ERROR", error_msg)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_pipeline())
