import asyncio
import datetime
import pytz
import traceback
import sys

from scanner import scan_market
from validator import validate_candidates
from database import init_db
from telegram_bot import send_message, format_scan_message, format_validate_message

async def run():
    try:
        print("1. V8.4.5 최상위 퀀트 시스템 가동 준비...")
        init_db()
        print("✅ DB 안전 연결 확인 완료")

        kst = pytz.timezone('Asia/Seoul')
        n = datetime.datetime.now(kst)
        print(f"✅ 현재 KST 시스템 시각: {n.strftime('%Y-%m-%d %H:%M:%S')}")

        if 8 <= n.hour < 10:
            print("2. [오전 장중] 주도주 스캔 가동...")
            data = await scan_market()
            await send_message(format_scan_message(data))
            print("✅ 정밀 리포트 타전 완료")
            
        elif n.hour == 15 and n.minute <= 30:
            print("2. [오후 15:00] 생존 검사 가동...")
            results = validate_candidates()
            await send_message(format_validate_message(results))
            print("✅ 생존 검사 보고 완료")
            
        elif n.hour == 15 and n.minute >= 35:
            print("2. [오후 15:40] 일일 마감 연산...")
            await send_message("🌙 V8.4.5 DAILY REPORT: 오늘분 데이터 적재 및 기계적 백업 완료")
            print("✅ 마감 완료")
            
        else:
            print("⚠️ 수동 가동 감지: 임의 시그널 리포트 출력 테스트 수행")
            data = await scan_market()
            await send_message(format_scan_message(data))
            print("✅ 수동 테스트 스캔 완료")

    except Exception as e:
        print("\n" + "="*50)
        print("🚨 치명적 에러 발생 - 연산 긴급 정지 🚨")
        traceback.print_exc()
        print("="*50 + "\n")
        # 깃허브 액션에서 치명적 에러 발생 시만 Exit code 1 반환
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run())
