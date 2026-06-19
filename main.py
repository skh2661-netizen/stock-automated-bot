import asyncio
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
    if h == 11 and 0 <= m <= 20: return "BREAKOUT_2"
    if h == 15 and 0 <= m <= 25: return "CLOSE_BET"
    if h == 15 and 30 <= m <= 59: return "REVIEW"
    return None

async def run_pipeline():
    mode = get_mode()
    # 테스트 강제 진입 (필요시 'TEST' 모드로 강제 실행)
    if mode is None:
        mode = "TEST"
        print("시간 외 작동 - TEST 모드 강제 진입")

    try:
        scan_result = await scan_market(run_type=mode)
        candidates = scan_result.get("candidates", [])
        
        # [DEBUG] 후보군 확인용 로그
        print(f"[DEBUG] 모드:{mode} / 최종 후보:{len(candidates)}건")

        if candidates:
            msg = format_scan_message(scan_result)
            await send_message(msg)
            # unique_key 기반 마킹 (날짜_코드)
            today_str = datetime.now(pytz.timezone('Asia/Seoul')).strftime('%Y%m%d')
            mark_telegram_sent([f"{today_str}_{c['code']}" for c in candidates])
            print("발송 완료")
        else:
            print("후보 없음")
    except Exception as e:
        print(f"오류: {e}")

if __name__ == "__main__":
    asyncio.run(run_pipeline())
