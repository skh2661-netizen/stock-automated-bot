import asyncio
import pytz
import sys
from datetime import datetime
from scanner import scan_market
from telegram_bot import send_message, format_scan_message
from database import mark_telegram_sent, save_log

# [시간대 모드 판정 함수]
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

# [메인 파이프라인]
async def run_pipeline():
    mode = get_mode()
    
    # 작전 시간 외 로직: 운영 환경에서는 return, 테스트 시에는 TEST 모드 강제 실행
    if mode is None:
        save_log("SKIP", "작전시간 아님")
        print("작전 시간 아님")
        return

    try:
        print(f"작전 개시: {mode} 모드 실행")
        if mode == "REVIEW":
            # 복기 모드 실행 로직 (필요 시 호출)
            return

        scan_result = await scan_market(run_type=mode)
        candidates = scan_result.get("candidates", [])

        if candidates:
            # 포맷터 연동
            msg = format_scan_message(scan_result)
            await send_message(msg)
            
            # DB 마킹: unique_key(날짜_코드) 기준
            today_str = datetime.now(pytz.timezone('Asia/Seoul')).strftime('%Y%m%d')
            unique_keys = [f"{today_str}_{c['code']}" for c in candidates]
            mark_telegram_sent(unique_keys)
            
            save_log(mode, f"{len(candidates)}건 발송 성공")
            print(f"발송 완료: {len(candidates)}건")
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
