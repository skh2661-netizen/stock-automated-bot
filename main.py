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
        print("1. V8.4 퀀트 엔진 가동 준비...")
        init_db()
        print("✅ DB 연결 완료")

        # 🚨 핵심: 서버 시간이 아닌 한국 시간(KST)으로 강제 고정
        kst = pytz.timezone('Asia/Seoul')
        n = datetime.datetime.now(kst)
        print(f"✅ 현재 KST 시각: {n.strftime('%Y-%m-%d %H:%M:%S')}")

        # 시간대에 따른 로직 분기
        if 8 <= n.hour < 9:
            print("2. [오전 08:45] 주도주 스캔 시작...")
            results = await scan_market()
            await send_message(format_scan_message(results))
            print("✅ 스캔 및 보고 완료")
            
        elif n.hour == 15 and n.minute <= 20:
            print("2. [오후 15:00] 생존 검사 시작...")
            results = validate_candidates()
            await send_message(format_validate_message(results))
            print("✅ 생존 검사 및 보고 완료")
            
        elif n.hour == 15 and n.minute >= 35:
            print("2. [오후 15:40] 일일 마감 보고...")
            await send_message("🌙 V8.4 DAILY REPORT: 오늘분 기록 완료")
            print("✅ 마감 보고 완료")
            
        else:
            print("⚠️ 스케줄된 시간이 아닙니다. (수동 가동 감지: 강제 스캔 테스트 진행)")
            results = await scan_market()
            await send_message(format_scan_message(results))
            print("✅ 수동 테스트 스캔 완료")

    except Exception as e:
        # 에러 발생 시 로그에 원인을 정확히 출력하는 블랙박스 장치
        print("\n" + "="*50)
        print("🚨 치명적 에러 발생 (아래 메시지를 확인하십시오) 🚨")
        traceback.print_exc()
        print("="*50 + "\n")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run())
