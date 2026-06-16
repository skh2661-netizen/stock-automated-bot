import asyncio, datetime, pytz, traceback, sys
from scanner import scan_market
from validator import validate_candidates, validate_d3_targets
from database import init_db, save_log
from market_check import is_market_open
from telegram_bot import send_message, format_scan_message, format_validate_message, format_d3_profit_message

async def run():
    mode = sys.argv[1] if len(sys.argv) > 1 else "REVIEW"

    # DB 초기화 1회 실행으로 병목 해소
    init_db()
    if not is_market_open():
        await send_message("💤 [휴장일 알림] 오늘(주말/공휴일)은 한국 증시 휴장일입니다. 연산을 중지합니다.")
        return

    try:
        if mode == "OPEN_SCAN":
            data = await scan_market("OPEN_SCAN")
            await send_message(format_scan_message(data))
            save_log("OPEN_SCAN", "SUCCESS")
            
        elif mode == "CLOSE_SCAN":
            data = await scan_market("CLOSE_SCAN")
            await send_message(format_scan_message(data))
            save_log("CLOSE_SCAN", "SUCCESS")
            
        elif mode == "REVIEW":
            results = validate_candidates()
            await send_message(format_validate_message(results))
            save_log("REVIEW", "SUCCESS")
            
            d3_results = validate_d3_targets()
            if d3_results:
                await send_message(format_d3_profit_message(d3_results))
                save_log("D3_PROFIT_ALERT", "SUCCESS")

    except Exception as e:
        error_msg = f"🚨 V8.4.5 장애 발생 ({mode} 모드): {str(e)}\n{traceback.format_exc()}"
        await send_message(error_msg)
        save_log("ERROR", str(e))

if __name__ == "__main__":
    asyncio.run(run())
