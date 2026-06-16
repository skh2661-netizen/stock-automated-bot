import asyncio
import datetime
import pytz
from scanner import scan_market
from telegram_bot import send_message, format_scan_message
from database import get_today_candidates, mark_telegram_sent, save_log

async def run_pipeline():
    try:
        # 1. 스캔 실행 및 DB 저장
        print("작전 개시: 시장 스캔 중...")
        scan_result = await scan_market("OPEN_SCAN")
        save_log("OPEN_SCAN", "스캔 완료")
        
        # 2. 발송되지 않은 오늘 후보 조회
        candidates = get_today_candidates()
        
        if candidates:
            print(f"발송 대상 후보 {len(candidates)}건 발견")
            
            # 3. 텔레그램 메시지 생성
            # format_scan_message에 전달하기 위해 데이터 구조 재구성
            msg = format_scan_message({
                "market": scan_result.get("market", {}),
                "stats": scan_result.get("stats", {}),
                "candidates": candidates
            })
            
            # 4. 발송
            await send_message(msg)
            
            # 5. 발송 성공 시 DB 업데이트 (중복 방지)
            unique_keys = [c["unique_key"] for c in candidates]
            mark_telegram_sent(unique_keys)
            
            save_log("OPEN_SCAN", f"{len(candidates)}건 발송 완료")
            print("발송 및 DB 마킹 완료")
        else:
            print("발송할 신규 후보가 없습니다.")
            save_log("OPEN_SCAN", "신규 후보 없음")
            
    except Exception as e:
        error_msg = f"작전 오류 발생: {str(e)}"
        print(error_msg)
        save_log("ERROR", error_msg)

if __name__ == "__main__":
    # 실행 루프
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_pipeline())
