import asyncio
import pytz
from datetime import datetime
from scanner import scan_market
from telegram_bot import send_message, format_scan_messages
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
    
    # [수정] 운영 vs 테스트 분리
    if mode is None:
        print("시간 외 작동 - TEST 모드 강제 진입")
        mode = "TEST"

    try:
        scan_result = await scan_market(run_type=mode)
        candidates = scan_result.get("candidates", [])
        
        print(f"[DEBUG] 모드:{mode} / 최종 후보:{len(candidates)}건")

        if candidates:
            # [수정] Chunk 분할 발송 로직 제거 -> 포맷터가 주는 2개 메시지 순차 전송
            messages = format_scan_messages(scan_result)
            for msg in messages:
                await send_message(msg)
                await asyncio.sleep(1) # API 보호용 1초 대기
            
            # DB 마킹 (당일 날짜 + 종목코드 조합)
            today_str = datetime.now(pytz.timezone('Asia/Seoul')).strftime('%Y%m%d')
            mark_telegram_sent([f"{today_str}_{c['code']}" for c in candidates])
            print("발송 및 마킹 완료")
        else:
            print("후보 없음")
            
    except Exception as e:
        print(f"작전 오류 발생 ({mode}): {str(e)}")

if __name__ == "__main__":
    asyncio.run(run_pipeline())
