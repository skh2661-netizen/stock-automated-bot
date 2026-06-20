import asyncio
import pytz
from datetime import datetime
from scanner import scan_market
from telegram_bot import send_message, format_scan_messages
from database import mark_telegram_sent

def get_mode():
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)
    h, m = now.hour, now.minute
    if h == 8 and 35 <= m <= 59: return "PRE_OPEN"
    if h == 9 and 0 <= m <= 30: return "BREAKOUT_1"
    if h == 11 and 0 <= m <= 20: return "BREAKOUT_2"
    if h == 15 and 0 <= m <= 25: return "CLOSE_BET"
    if h == 15 and 30 <= m <= 59: return "REVIEW"
    return "TEST"

async def run_pipeline():
    mode = get_mode()
    print(f"\n▶️ [시스템 가동] 작전 모드: {mode}")

    try:
        # 1. 스캐너 엔진 구동
        print("⏳ SCAN 진행 중...")
        scan_result = await scan_market(run_type=mode)
        candidates = scan_result.get("candidates", [])
        print(f"✅ SCAN 완료 (생존 후보군: {len(candidates)}개)")

        # [수정 2] 후보가 0개여도 가차없이 포맷터를 호출하여 시장 브리핑 발송 강제
        print("⏳ MESSAGE 생성 중...")
        messages = format_scan_messages(scan_result)
        
        if messages:
            print(f"✅ MESSAGE 생성 완료 (분할 메시지 개수: {len(messages)}개)")
            
            # 3. 텔레그램 전송 레이어 기동
            for i, msg in enumerate(messages, 1):
                print(f"⏳ TELEGRAM 발송 중... ({i}/{len(messages)})")
                await send_message(msg)
                await asyncio.sleep(1) # 세션 보호
            
            print("✅ TELEGRAM 발송 완료")
            
            # 발송 성공 종목 마킹 처리
            if candidates:
                mark_telegram_sent([c['code'] for c in candidates])
                print("🎯 당일 데이터 계약 마킹 완료")
        else:
            print("⚠️ 발송할 메시지 컨텐츠가 존재하지 않습니다.")
            
    except Exception as e:
        import traceback
        print(f"\n❌ [치명적 파이프라인 오류] 작전 중단:\n{str(e)}")
        print(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(run_pipeline())
