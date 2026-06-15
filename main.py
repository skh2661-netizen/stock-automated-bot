import asyncio, datetime, pytz, traceback, sys, subprocess, os
from scanner import scan_market
from validator import validate_candidates
from database import init_db
from telegram_bot import send_message, format_scan_message, format_validate_message

def git_push_db():
    try:
        # 안전한 동기화
        subprocess.run(["git", "config", "--global", "user.name", "github-actions"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=False)
        subprocess.run(["git", "add", "candidates.db"], check=True)
        subprocess.run(["git", "commit", "-m", "Auto-update DB: daily performance record"], check=False)
        subprocess.run(["git", "push", "origin", "main"], check=False)
        print("Git: 동기화 시도 완료.")
    except Exception as e:
        print(f"Git 작업 중 경고: {e}")

async def run():
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    init_db()
    
    try:
        status_info = f"⚙️ V8.4.2 실행 로그\n시간: {now.strftime('%H:%M')}\n"
        
        # 1. 시초 탐색 (08:50 ~ 09:50)
        if 8 <= now.hour < 10:
            data = await scan_market("OPEN_SCAN")
            await send_message(format_scan_message(data))
            
        # 2. 종가 배팅 (15:00 ~ 15:25, 지연 감안)
        elif now.hour == 15 and now.minute < 25:
            data = await scan_market("CLOSE_SCAN")
            await send_message(format_scan_message(data))
            
        # 3. 복기 및 결과 저장 (15:30 ~ 15:59)
        elif now.hour == 15 and now.minute >= 30:
            results = validate_candidates()
            await send_message(format_validate_message(results))
            status_info += f"작업: REVIEW\nDB 상태: 저장 완료"
            await send_message(status_info)
        
        else:
            print(f"대기 모드 {now.strftime('%H:%M')}")

        git_push_db()
        
    except Exception as e:
        error_msg = f"🚨 V8.4.2 시스템 치명적 장애\n원인: {str(e)}"
        await send_message(error_msg)
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run())
