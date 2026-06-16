import asyncio
from scanner import scan_market
from telegram_bot import send_message, format_scan_message
from database import get_today_candidates, mark_telegram_sent, save_log

async def run_pipeline():
    try:
        print("작전 개시: 시장 스캔 중...")
        # 1. 스캔 및 DB 적재 (scanner.py 내부에서 save_candidate 호출됨)
        scan_result = await scan_market("OPEN_SCAN")
        save_log("OPEN_SCAN", "스캔 완료")

        # 2. 정밀 타겟 호출 (DB에서 발송 대기 건만 추출)
        candidates = get_today_candidates()

        if candidates:
            print(f"신규 발송 대상 {len(candidates)}건 발견")

            # 3. 메시지 조립
            msg = format_scan_message({
                "market": scan_result.get("market", {}),
                "stats": scan_result.get("stats", {}),
                "candidates": candidates
            })

            # 4. 텔레그램 발송
            await send_message(msg)

            # 5. 상태 업데이트 (발송된 종목의 PK만 추출하여 마킹)
            unique_keys = [c["unique_key"] for c in candidates]
            mark_telegram_sent(unique_keys)

            print("발송 및 DB 마킹 완료")
            save_log("OPEN_SCAN", f"{len(candidates)}건 발송 완료")
        else:
            print("발송할 신규 후보가 없습니다.")
            save_log("OPEN_SCAN", "신규 후보 없음")

    except Exception as e:
        error_msg = f"작전 오류 발생: {str(e)}"
        print(error_msg)
        save_log("ERROR", error_msg)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_pipeline())
