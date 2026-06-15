import asyncio, datetime, pytz, traceback, sys, subprocess, os
from scanner import scan_market
from validator import validate_candidates
from database import init_db
from telegram_bot import send_message, format_scan_message, format_validate_message

def git_push_db():
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "add", "candidates.db"], check=True)
        subprocess.run(["git", "commit", "-m", "Auto-update DB: daily performance record"], check=True)
        subprocess.run(["git", "push"], check=True)
    except Exception as e:
        print(f"Git Push 실패: {e}")

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
        elif now.hour >= 15:
            await send_message("🌙 일일 데이터 적재 완료")
        
        # 🚨 작업 완료 후 DB 변경사항 클라우드에 영구 저장
        git_push_db()
    except Exception as e:
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run())
