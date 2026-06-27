import asyncio
import traceback
from scanner import generate_raw_candidates
from decision_engine import evaluate_candidates
from telegram_bot import format_scan_messages, send_message

async def main():
    try:
        print("🔍 [STEP 1] Scanner Engine 가동 (데이터 수집 및 팩트 생성 중...)")
        # 1. 눈 (Scanner): 판단 없이 순수 Raw Data만 생성
        raw_data = await generate_raw_candidates("OPEN_SCAN")
        
        if raw_data.get("stats", {}).get("data_error"):
            print("🚨 데이터 공급 장애 발생")
            await send_message("🚨 <b>데이터 공급 장애 발생</b>\n점검이 필요합니다.")
            return

        print("🧠 [STEP 2] Decision Engine 가동 (매매 판단 및 타점 산출 중...)")
        # 2. 뇌 (Decision Engine): Raw Data와 시장 리스크를 종합하여 액션 결정
        final_results = evaluate_candidates(raw_data)

        print("📲 [STEP 3] Telegram Interface 가동 (리포트 발송 중...)")
        # 3. 입 (Telegram): 최종 판결문을 포맷팅하여 전송
        messages = format_scan_messages(final_results)
        
        for msg in messages:
            await send_message(msg)
            
        print("✅ 전체 프로세스 완료")

    except Exception as e:
        print(f"❌ 시스템 치명적 오류 발생: {e}")
        traceback.print_exc()
        await send_message("🚨 <b>시스템 치명적 오류 발생</b>\n로그를 확인하십시오.")

if __name__ == "__main__":
    asyncio.run(main())
