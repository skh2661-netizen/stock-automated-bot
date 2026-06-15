import telegram, asyncio
import os

async def send_message(text):
    """텔레그램 메시지 안전 전송 (토큰 누락 시 즉사 방지)"""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("🚨 에러: GitHub Secrets에 TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID가 등록되지 않았거나 오타가 있습니다.")
        return

    bot = telegram.Bot(token=token)
    for _ in range(3):
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            break
        except Exception as e: 
            print(f"텔레그램 전송 실패, 3초 후 재시도 중... ({e})")
            await asyncio.sleep(3)

def format_scan_message(results):
    """08:45 시초가 정밀 스캔 결과 양식 (해상도 업그레이드)"""
    msg = "☀️ V8.4 정밀 스캔 보고서\n====================\n"
    if not results: return msg + "조건 만족 종목 없음"
    
    for i, r in enumerate(results, 1):
        msg += f"[{i}위] {r['name']} ({r['code']})\n"
        msg += f" ┣ 📊 종합점수 : {r['score']}점 ({r['grade']})\n"
        msg += f" ┣ 💰 현재가 : {r['price']:,}원 ({r['chg']}%)\n"
        msg += f" ┗ 💸 거래대금 : {r['amount']:,}억 원\n"
        msg += "--------------------\n"
    return msg

def format_validate_message(results):
    """15:00 종가 생존 검사 결과 양식"""
    msg = "⚠️ V8.4 15:00 생존 검사\n====================\n"
    if not results: return msg + "검사 대상 종목 없음"
    
    for r in results:
        status = "🔥 유지" if r["survive"] else "❌ 탈락"
        reason_str = ', '.join(r['reason']) if r['reason'] else "특이사항 없음"
        msg += f"{status} {r['name']} | 수익:{r['change']}% | 사유:{reason_str}\n"
    return msg
