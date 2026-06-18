import asyncio
from scanner import scan_market
from telegram_bot import send_message, format_scan_message
from database import get_today_candidates, mark_telegram_sent, save_log
import pytz
from datetime import datetime
import sys

# [시간별 모드 할당 함수 - main.py 최상단 배치]
def get_mode():
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)
    h, m = now.hour, now.minute
    
    if h == 8 and 35 <= m <= 59: return "PRE_OPEN"
    if h == 9 and 0 <= m <= 30: return "BREAKOUT_1"
    if (h == 10) or (h == 11 and m <= 20): return "BREAKOUT_2"
    if h == 15 and 0 <= m <= 25: return "CLOSE_BET"
    if h == 15 and 30 <= m <= 59: return "REVIEW"
    return None

async def run_pipeline():
    mode = get_mode()
    if mode is None:
        print("작전 시간 아님")
        return

    try:
        print(f"작전 개시: {mode} 모드 시장 스캔 중...")
        
        # [REVIEW 모드일 때]
        if mode == "REVIEW":
            # 여기에는 형님의 기존 review_performance() 함수 호출부 삽입
            print("복기 모드 실행")
            return

        # [일반 스캔 모드]
        scan_result = await scan_market(run_type=mode)
        save_log(mode, "스캔 완료")

        candidates = scan_result.get("candidates", []) # DB 재조회 삭제, scan_result 직접 사용

        if candidates:
            print(f"신규 발송 대상 {len(candidates)}건 발견")
            
            # format_scan_message가 요구하는 데이터 구조 전달
            msg = format_scan_message(scan_result)
            await send_message(msg)

            # DB 마킹 (unique_key가 있을 경우 사용, 없으면 scanner 코드와 계약 유지)
            # candidates에 unique_key가 없으면 name으로 대체 가능
            unique_keys = [c.get("unique_key", c["name"]) for c in candidates]
            mark_telegram_sent(unique_keys)

            print("발송 및 DB 마킹 완료")
            save_log(mode, f"{len(candidates)}건 발송 완료")
        else:
            print("발송할 신규 후보가 없습니다.")
            save_log(mode, "신규 후보 없음")

    except Exception as e:
        error_msg = f"작전 오류 발생 ({mode}): {str(e)}"
        print(error_msg)
        save_log("ERROR", error_msg)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_pipeline())
