import asyncio, datetime, pytz, traceback, sys, subprocess, os
from scanner import scan_market
from validator import validate_candidates
from database import init_db
from telegram_bot import send_message, format_scan_message, format_validate_message

def git_push_db():
    """Git 동기화: 변경사항이 있을 때만 Push하며, 오류 발생 시에도 전체 프로세스는 유지"""
    try:
        # 변경사항 확인 (porcelain 모드)
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not result.stdout.strip():
            print("Git: 변경된 DB 파일 없음. 동기화 생략.")
            return
            
        subprocess.run(["git", "config", "--global", "user.name", "github-actions"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "add", "candidates.db"], check=True)
        subprocess.run(["git", "commit", "-m", "Auto-update DB: daily performance record"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Git: DB 동기화 완료.")
    except Exception as e:
        print(f"Git Push 과정에서 경고 발생: {e}")

async def run():
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    init_db()
    
    try:
        # 1. 08:50 ~ 09:50 구간: OPEN_SCAN
        if 8 <= now.hour < 10:
            print("작전 개시: OPEN_SCAN")
            data = await scan_market(run_type="OPEN_SCAN")
            await send_message(format_scan_message(data))
            
        # 2. 15:30 ~ 15:59 구간: REVIEW (장 마감 복기)
        elif now.hour == 15 and 30 <= now.minute <= 59:
            print("작전 개시: REVIEW")
            results = validate_candidates()
            await send_message(format_validate_message(results))
            
        # 3. 그 외 시간: 정기 점검 모드
        else:
            print(f"정기 점검 모드 ({now.strftime('%H:%M')})")
            await send_message(f"🕒 [정기 점검] 현재 시간 {now.strftime('%H:%M')} - 대기 중입니다.")

        # 4. Git DB 동기화 (텔레그램 발송 후 독립적으로 수행)
        git_push_db()
        
    except Exception as e:
        # 치명적 에러 발생 시 텔레그램 비상 보고 후 종료
        error_msg = f"🚨 V8.4.2 시스템 치명적 장애\n원인: {str(e)}"
        print(error_msg)
        await send_message(error_msg)
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    # 비동기 실행 루프
    asyncio.run(run())
