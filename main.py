import asyncio
from scanner import generate_raw_candidates
from decision_engine import evaluate_candidates
from telegram_bot import format_scan_messages, send_message

async def main():
    run_type = "OPEN_SCAN"
    print(f"🚀 V8.8.17 Quant Engine 가동 ({run_type})...")
    
    # 1. Scanner 가동
    raw_data = await generate_raw_candidates(run_type=run_type)
    if not raw_data or raw_data.get("stats", {}).get("data_error"):
        await send_message("🚨 <b>스캐너 데이터 추출 실패</b>")
        return

    # 2. Decision Engine 가동
    final_results = evaluate_candidates(raw_data)
    
    # 3. Telegram Report 포맷팅 (인자 2개 규격 준수)
    messages = format_scan_messages(run_type, final_results)
    
    # 4. 비동기 발송
    for msg in messages:
        await send_message(msg)
        await asyncio.sleep(1) # API Rate Limit 방어
        
    print("✅ 텔레그램 발송 완료 및 사이클 종료.")

if __name__ == "__main__":
    asyncio.run(main())
