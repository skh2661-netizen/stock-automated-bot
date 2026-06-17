import asyncio
from scanner import scan_market
from telegram_bot import send_message, format_scan_message
from database import get_today_candidates, mark_telegram_sent, save_log

async def run_pipeline():
    try:
        print("작전 개시: 시장 스캔 중...")
        scan_result = await scan_market("OPEN_SCAN")
        save_log("OPEN_SCAN", "스캔 완료")

        candidates = get_today_candidates()
        
        # 디버깅: DB에서 넘겨받은 상태값 강제 노출
        print("DB 조회 결과:", candidates)

        if candidates:
            print(f"신규 발송 대상 {len(candidates)}건 발견")
            
            # fail_stats 누락 방어
            msg = format_scan_message({
                "market": scan_result.get("market", {}),
                "stats": scan_result.get("stats", {}),
                "fail_stats": scan_result.get("fail_stats", {}),
                "candidates": candidates
            })

            await send_message(msg)

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
