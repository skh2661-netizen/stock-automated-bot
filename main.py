import asyncio
from scanner import scan_market
from telegram_bot import send_message, format_scan_message
from database import get_today_candidates, mark_telegram_sent, save_log
import pytz
from datetime import datetime

# 시간대별 모드 결정 함수 (main.py에 추가)
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
    # 1. 모드 결정
    mode = get_mode()
    if mode is None:
        print("작전 시간 아님")
        return

    try:
        print(f"작전 개시: {mode} 모드 시장 스캔 중...")
        
        # 2. REVIEW 모드 처리 (스캔하지 않고 성과 분석만)
        if mode == "REVIEW":
            # 여기에는 형님의 기존 review_performance 함수 호출부 삽입
            print("복기 모드 실행")
            return
            
        # 3. 일반 스캔 모드 (mode를 run_type으로 전달)
        scan_result = await scan_market(run_type=mode)
        save_log(mode, "스캔 완료")

        candidates = get_today_candidates()
        print("DB 조회 결과:", candidates)

        if candidates:
            print(f"신규 발송 대상 {len(candidates)}건 발견")
            msg = format_scan_message({
                "market": scan_result.get("market", {}),
                "stats": scan_result.get("stats", {}),
                "candidates": candidates
            })
            await send_message(msg)
            unique_keys = [c["unique_key"] for c in candidates]
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
