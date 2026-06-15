import asyncio, datetime, pytz, sys, subprocess
from scanner import scan_market
from validator import validate_candidates
from database import init_db
from telegram_bot import send_message

async def run():
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    init_db()
    
    try:
        # 실행 모드 판별
        if 8 <= now.hour < 10:
            # 08:50 ~ 09:50 구간: OPEN_SCAN
            data = await scan_market("OPEN_SCAN")
        elif now.hour == 15 and 30 <= now.minute <= 59:
            # 15:30 ~ 15:59 구간: REVIEW
            results = validate_candidates()
            # 텔레그램 발송 로직 추가 필요
        else:
            await send_message(f"🕒 [정기 점검] 현재 시간 {now.strftime('%H:%M')} - 대기 중입니다.")
            return

        # DB Push (변경사항 있을 시)
        # git_push_db() 
    except Exception as e:
        print(f"오류 발생: {e}")
