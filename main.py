import asyncio
from scanner import scan_market
from telegram_bot import send_message, format_scan_messages, format_holding_report
from holding import run_holding_engine
from datetime import datetime

async def run_pipeline():
    # 시간대별 모드 판단
    h = datetime.now().hour
    if h == 8: mode = "PRE_OPEN"
    elif h == 9: mode = "BREAKOUT_1"
    elif h == 14: mode = "CLOSE_BET"
    else: mode = "TEST"
    
    # 1. 시장 및 스캔
    data = await scan_market(run_type=mode)
    if data.get('stats', {}).get('data_error'):
        await send_message("🚨 데이터 공급 장애")
        return
        
    # 2. 리포트 발송
    for msg in format_scan_messages(data.get('candidates', [])):
        await send_message(msg)
        
    # 3. 15시 30분 보유 점검
    if h == 15:
        holdings = run_holding_engine(0, 0)
        for msg in format_holding_report(holdings):
            await send_message(msg)

if __name__ == "__main__":
    asyncio.run(run_pipeline())
