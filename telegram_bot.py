import os
from telegram import Bot
from html import escape

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if TELEGRAM_TOKEN: bot = Bot(token=TELEGRAM_TOKEN)
else: bot = None

async def send_message(text):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try: await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='HTML')
    except Exception as e: print(f"❌ 텔레그램 발송 실패: {e}")

def format_holding_report(holding_results):
    if not holding_results: return ["📌 <b>HOLDING REPORT</b>\n\n등록된 종목 없음"]
        
    msg = "📌 <b>HOLDING REPORT</b>\n\n"
    for r in holding_results:
        exit_icon = "🚨" if r['exit_score'] >= 6 else "🛡️"
        msg += f"👑 <b>{escape(r['name'])}</b> ({r['pnl']}%) | {exit_icon} EXIT: {r['exit_score']}/10\n"
        msg += f"└ 종합 {r['total']}점 | 판정: {r['judgment']}\n\n"
    return [msg]

def format_scan_messages(scan_result):
    stats = scan_result.get("stats", {})
    candidates = scan_result.get("candidates", [])
    market = scan_result.get("market", {})
    mode_raw = market.get("mode", "UNKNOWN")
    
    if stats.get('data_error', False): return ["🚨 데이터 공급 장애 감지"]

    msg1 = f"🎯 <b>V8.7 퀀트 시그널 ({mode_raw})</b>\n"
    msg1 += f"🌎 시장: KP {market.get('kospi', 0)}% / KQ {market.get('kosdaq', 0)}%\n\n"
    
    leaders = [c for c in candidates if c['type'] == 'LEADER']
    entries = [c for c in candidates if c['type'] == 'ENTRY']
    watches = [c for c in candidates if c['type'] == 'WATCH']
    
    msg1 += "🔥 <b>시장 주도 감시군</b>\n"
    combined_watch = (leaders + watches)[:2]
    if not combined_watch: msg1 += "없음\n"
    for i, c in enumerate(combined_watch, 1):
        status = "⚠️과열" if c['is_overheated'] else "관찰"
        msg1 += f"{i}. {escape(c['name'])} | Prime {c['prime_score']} | MA20 +{c['ma_gap']}% [{status}]\n"
        
    msg1 += "\n🎯 <b>실제 매수 후보</b>\n"
    if not entries: msg1 += "없음\n"
    for i, c in enumerate(entries[:3], 1):
        msg1 += f"{i}. {escape(c['name'])} | Score {c['score']} | MA20 +{c['ma_gap']}%\n"
        msg1 += f"└ 진입 타점: {c['buy_p']:,}원 부근\n"

    msg1 += "\n📌 <b>내일 관심 예약</b>\n"
    if not watches: msg1 += "없음\n"
    for c in watches[:3]:
        msg1 += f"- {escape(c['name'])} (Prime {c['prime_score']})\n"

    return [msg1]
