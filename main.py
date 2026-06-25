import asyncio
import traceback
from datetime import datetime
from scanner import scan_market
from telegram_bot import send_message, format_scan_messages, format_holding_report
from holding import run_holding_engine

async def run_pipeline():
    h = datetime.now().hour
    if h == 8: mode = "PRE_OPEN"
    elif h == 9: mode = "BREAKOUT_1"
    elif h == 14: mode = "CLOSE_BET"
    else: mode = "TEST"
    
    try:
        data = await scan_market(run_type=mode)
        # 스캔 리포트 전송
        for msg in format_scan_messages(data):
            await send_message(msg)
            
        # 15시 30분 보유 관리
        if h == 15:
            holdings = run_holding_engine(0, 0)
            for msg in format_holding_report(holdings):
                await send_message(msg)
    except Exception:
        await send_message("🚨 파이프라인 치명적 오류 발생")

if __name__ == "__main__":
    asyncio.run(run_pipeline())
