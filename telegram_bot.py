import os
from telegram import Bot
from html import escape

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if TELEGRAM_TOKEN: bot = Bot(token=TELEGRAM_TOKEN)
else: bot = None

# [복구] 메인 파이프라인에서 호출하는 send_message 함수 재탑재
async def send_message(text):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try: await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='HTML')
    except Exception as e: print(f"❌ 텔레그램 발송 실패: {e}")

REPORT_ID = "🎯 V8.8.4 DAILY QUANT REPORT"

def format_holding_report(holding_results):
    msg = f"{REPORT_ID} [3/3]\n\n👑 <b>HOLDING ENGINE</b>\n\n"
    if not holding_results:
        msg += "등록된 보유 종목 없음"
        return [msg]
    for r in holding_results:
        exit_icon = "🚨" if r['exit_score'] >= 6 else "🛡️"
        msg += f"<b>{escape(r['name'])}</b>\n"
        msg += f"매수가: {r['buy_p']:,}원 | 현재가: {r['curr_p']:,}원\n"
        msg += f"손익: {'🔴' if r['pnl'] < 0 else '🟢'} {r['pnl']}%\n"
        msg += f"기업: {r['corp']} | 차트: {r['chart']}\n"
        msg += f"EXIT: {r['exit_score']}/10 {exit_icon}\n"
        msg += f"판정: {r['judgment']}\n"
        msg += "-" * 20 + "\n"
    return [msg]

def format_scan_messages(scan_result):
    stats = scan_result.get("stats", {})
    candidates = scan_result.get("candidates", [])
    market = scan_result.get("market", {})
    mode_raw = market.get("mode", "UNKNOWN")
    
    if stats.get('data_error', False): return ["🚨 데이터 공급 장애 감지"]

    messages = []
    msg_market = f"{REPORT_ID} [1/3]\n\n🌎 <b>MARKET ({mode_raw})</b>\n\n"
    msg_market += f"KOSPI  {market.get('kospi', 0)}%\nKOSDAQ {market.get('kosdaq', 0)}%\n\n"
    msg_market += f"분석: {stats.get('total', 0)}개 → {stats.get('final', 0)}개 생존"
    messages.append(msg_market)
    
    leaders = [c for c in candidates if c['type'] == 'LEADER']
    entries = [c for c in candidates if c['type'] == 'ENTRY']
    watches = [c for c in candidates if c['type'] == 'WATCH']
    
    msg_scan = f"{REPORT_ID} [2/3]\n\n🔥 <b>SCANNER ENGINE</b>\n\n"
    msg_scan += "🚀 <b>STRONG BUY</b>\n"
    for i, c in enumerate(entries[:3], 1):
        msg_scan += f"{i}. <b>{escape(c['name'])}</b> (Score:{c['score']})\n  진입:{c['buy_p']:,}원 | 손절:{c['stop_p']:,}\n"
    
    msg_scan += "\n⚠️ <b>WATCH (과열/관심)</b>\n"
    for c in (leaders + watches)[:3]:
        msg_scan += f"- {escape(c['name'])} (MA20 +{c['ma_gap']}%) \n"
        
    messages.append(msg_scan)
    return messages
