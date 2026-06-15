Python
import telegram, asyncio
import os
TOKEN, CHAT_ID = os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]

async def send_message(text):
    bot = telegram.Bot(token=TOKEN)
    for _ in range(3):
        try:
            await bot.send_message(chat_id=CHAT_ID, text=text)
            break
        except: await asyncio.sleep(3)

def format_scan_message(results):
    msg = "☀️ V8.4 MORNING SCAN\n====================\n"
    if not results: return msg + "조건 만족 종목 없음"
    for i, r in enumerate(results, 1):
        msg += f"{i}위 {r['name']} | 등급:{r['grade']} | 점수:{r['score']} | {r['price']:,}원\n"
    return msg

def format_validate_message(results):
    msg = "⚠️ V8.4 15:00 생존 검사\n====================\n"
    for r in results:
        status = "🔥 유지" if r["survive"] else "❌ 탈락"
        msg += f"{status} {r['name']} | 수익:{r['change']}% | 사유:{','.join(r['reason'])}\n"
    return msg
