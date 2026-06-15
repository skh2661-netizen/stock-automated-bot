import asyncio, datetime
from scanner import scan_market
from validator import validate_candidates
from database import init_db
from telegram_bot import send_message, format_scan_message, format_validate_message

async def run():
    init_db()
    n = datetime.datetime.now()
    if 8 <= n.hour < 9: await send_message(format_scan_message(await scan_market()))
    elif n.hour == 15 and n.minute <= 20: await send_message(format_validate_message(validate_candidates()))
    elif n.hour == 15 and n.minute >= 35: await send_message("🌙 V8.4 DAILY REPORT: 오늘분 기록 완료")

if __name__ == "__main__": asyncio.run(run())
