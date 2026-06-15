import asyncio, datetime, pytz, traceback, sys, subprocess
from scanner import scan_market
from validator import validate_candidates
from database import init_db
from telegram_bot import send_message, format_scan_message, format_validate_message

def git_push_db():
    try:
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not result.stdout.strip(): return
        subprocess.run(["git", "config", "--global", "user.name", "github-actions"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "add", "candidates.db"], check=True)
        subprocess.run(["git", "commit", "-m", "Auto-update DB"], check=True)
        subprocess.run(["git", "push"], check=True)
    except Exception as e:
        print(f"Git Push 경고: {e}")

async def run():
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    init_db()
    
    try:
        # 1. 08:50 ~ 09:50 구간 (시초 탐색)
        if 8 <= now.hour < 10:
            data = await scan_market("OPEN_SCAN")
            await send_message(format_scan_message(data))
        
        # 2. 15:00 ~ 15:20 구간 (종가 베팅)
        elif now.hour == 15 and now.minute < 20:
            data = await scan_market("CLOSE_SCAN")
            await send_message(format_scan_message(data))
            
        # 3. 15:30 ~ 15:59 구간 (복기)
        elif now.hour == 15 and now.minute >= 30:
            results = validate_candidates()
            await send_message(format_validate_message(results))
            
        # 4. 그 외 시간 (정기 점검 메시지 제거, 로그만 남김)
        else:
            print(f"대기 모드 {now.strftime('%H:%M')}")

        git_push_db()
        
    except Exception as e:
        error_msg = f"🚨 V8.4.2 시스템 장애: {str(e)}"
        print(error_msg)
        await send_message(error_msg)
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run())
