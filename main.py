import asyncio, datetime, pytz, traceback, sys, subprocess, os
from scanner import scan_market
from validator import validate_candidates
from database import init_db
from telegram_bot import send_message, format_scan_message, format_validate_message

def git_push_db():
    try:
        # DB 저장 및 강제 Push
        subprocess.run(["git", "config", "--global", "user.name", "github-actions"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "add", "candidates.db"], check=True)
        subprocess.run(["git", "commit", "-m", "Auto-update DB"], check=True)
        subprocess.run(["git", "push"], check=True)
    except Exception as e:
        print(f"Git Push 생략: {e}")

async def run():
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    init_db()
    
    try:
        if 8 <= now.hour < 10:
            data = await scan_market()
            await send_message(format_scan_message(data))
        elif now.hour == 15 and now.minute <= 20:
            results = validate_candidates()
            await send_message(format_validate_message(results))
        else:
            await send_message(f"🌙 V8.4 정기 점검 모드 ({now.strftime('%H:%M')})")
        
        git_push_db()
    except Exception as e:
        # 에러 발생 시 즉시 상세 스택트레이스 출력
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run())
