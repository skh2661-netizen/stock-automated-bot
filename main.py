import asyncio, datetime, pytz, traceback, sys, subprocess
from scanner import scan_market
from validator import validate_candidates, validate_d3_targets
from database import init_db, save_log
from market_check import is_market_open
from telegram_bot import send_message, format_scan_message, format_validate_message, format_d3_profit_message
from custom_checker import analyze_single_stock  # 와이씨 감시용 모듈

def git_push_db():
    try:
        res = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not res.stdout.strip(): return
        subprocess.run(["git", "config", "--global", "user.name", "github-actions"], check=True)
        subprocess.run(["git", "add", "candidates.db"], check=True)
        subprocess.run(["git", "commit", "-m", "DB Update"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
    except Exception as e: print(f"Git 작업 생략: {e}")

async def run():
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    init_db()

    if not is_market_open():
        await send_message("🌙 V8.4.5 자율주행 엔진 - 휴장일 보호 모드 종료")
        return

    try:
        # [기존 로직 100% 보존]
        if 8 <= now.hour < 10:
            data = await scan_market("OPEN_SCAN")
            await send_message(format_scan_message(data))
            save_log("OPEN_SCAN", "SUCCESS")
            
        elif now.hour == 15 and now.minute < 25:
            data = await scan_market("CLOSE_SCAN")
            await send_message(format_scan_message(data))
            save_log("CLOSE_SCAN", "SUCCESS")
            
        elif now.hour == 15 and 30 <= now.minute <= 59:
            # 1. 기존 장 마감 생존 검사
            results = validate_candidates()
            await send_message(format_validate_message(results))
            save_log("REVIEW", "SUCCESS")
            
            # 2. D+3 스윙 타겟 기계적 익절 알림
            d3_results = validate_d3_targets()
            if d3_results:
                await send_message(format_d3_profit_message(d3_results))
                save_log("D3_PROFIT_ALERT", "SUCCESS")

        # [V8.4.5 핵심 추가: 와이씨(232140) 보유 종목 특별 감시]
        # 위 스케줄 작업이 모두 끝난 후, 와이씨 현황을 정밀 분석하여 보고
        try:
            yc_report = analyze_single_stock("232140", "와이씨")
            await send_message("🚨 [보유 종목 특별 감시]\n" + yc_report)
        except Exception as e:
            print(f"와이씨 보고 오류: {e}")
                
    except Exception as e:
        await send_message(f"🚨 V8.4.5 장애 발생: {str(e)}")
        save_log("ERROR", str(e))
        traceback.print_exc()
        sys.exit(1)
    finally:
        git_push_db()

if __name__ == "__main__":
    asyncio.run(run())
