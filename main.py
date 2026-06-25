import asyncio
import pytz
import os
import traceback
from datetime import datetime
from scanner import scan_market
from telegram_bot import send_message, format_scan_messages, format_holding_report
from database import mark_telegram_sent
from holding import run_holding_engine

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def get_mode():
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)
    h, m = now.hour, now.minute
    if h == 8 and 35 <= m <= 59: return "PRE_OPEN"
    if h == 9 and 0 <= m <= 30: return "BREAKOUT_1"
    if h == 11 and 0 <= m <= 20: return "BREAKOUT_2"
    if h == 14 and 30 <= m <= 59: return "CLOSE_BET"
    # [V8.7] 15시 30분에는 보유 관리 엔진 가동
    if h == 15 and 30 <= m <= 45: return "HOLDING_CHECK"
    if h == 15 and 46 <= m <= 59: return "REVIEW"
    return "TEST"

async def run_pipeline():
    mode = get_mode()
    print(f"\n▶️ [시스템 가동] 작전 모드: {mode}")

    try:
        if mode == "HOLDING_CHECK":
            print("⏳ HOLDING 점검 진행 중...")
            # 시장 점수를 추출하기 위해 빈 스캔 1회 구동
            scan_result = await scan_market(run_type="TEST")
            kp_1d = scan_result.get("market", {}).get("kospi", 0)
            kd_1d = scan_result.get("market", {}).get("kosdaq", 0)
            
            holding_results = run_holding_engine(kp_1d, kd_1d)
            messages = format_holding_report(holding_results)
            
        else:
            print("⏳ SCAN 진행 중...")
            scan_result = await scan_market(run_type=mode)
            candidates = scan_result.get("candidates", [])
            print(f"✅ SCAN 완료 (생존 후보군: {len(candidates)}개)")

            print("⏳ MESSAGE 생성 중...")
            messages = format_scan_messages(scan_result)
            
            if candidates:
                mark_telegram_sent([c['code'] for c in candidates])
                print("🎯 당일 데이터 계약 마킹 완료")

        if messages:
            print(f"✅ MESSAGE 생성 완료 (분할 개수: {len(messages)}개)")
            for i, msg in enumerate(messages, 1):
                print(f"⏳ TELEGRAM 발송 중... ({i}/{len(messages)})")
                await send_message(msg)
                await asyncio.sleep(1)
            print("✅ TELEGRAM 발송 완료")
        else:
            print("⚠️ 발송할 메시지 컨텐츠가 존재하지 않습니다.")
            
    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"\n❌ [치명적 파이프라인 오류] 작전 중단:\n{error_msg}")
        
        try:
            alert_text = (
                f"🚨 <b>V8.7 시스템 장애 보고</b>\n\n"
                f"<b>모드:</b> {mode}\n"
                f"<b>오류:</b> {str(e)}\n\n"
                f"<b>위치 요약:</b>\n<pre>{error_msg[-1000:]}</pre>"
            )
            await send_message(alert_text)
        except Exception as tg_err:
            print(f"❌ 장애 보고 텔레그램 발송 실패: {tg_err}")

if __name__ == "__main__":
    asyncio.run(run_pipeline())
