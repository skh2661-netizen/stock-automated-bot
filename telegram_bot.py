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

REPORT_ID = "🎯 V8.8.1 DAILY QUANT REPORT"

def format_holding_report(holding_results):
    if not holding_results: return [f"{REPORT_ID} [3/3]\n\n👑 <b>HOLDING CHECK</b>\n\n등록된 보유 종목 없음"]
        
    msg = f"{REPORT_ID} [3/3]\n\n👑 <b>HOLDING CHECK</b>\n\n"
    for r in holding_results:
        exit_icon = "🚨" if r['exit_score'] >= 6 else "🛡️"
        msg += f"<b>{escape(r['name'])}</b>\n"
        msg += f"매수가: {r['buy_p']:,}원\n현재가: {r['curr_p']:,}원\n"
        
        pnl_icon = "🔴" if r['pnl'] < 0 else "🟢"
        msg += f"손익: {pnl_icon} {r['pnl']}%\n\n"
        
        msg += f"기업: {r['corp']} | 차트: {r['chart']}\n"
        msg += f"EXIT: {r['exit_score']}/10 {exit_icon}\n\n"
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
    
    # [1/3] 시장 보고서
    msg_market = f"{REPORT_ID} [1/3]\n\n"
    msg_market += f"🌎 <b>MARKET ({mode_raw})</b>\n\n"
    msg_market += f"KOSPI  {market.get('kospi', 0)}%\n"
    msg_market += f"KOSDAQ {market.get('kosdaq', 0)}%\n\n"
    
    status_icon = "🟢" if market.get('kospi', 0) > 0 and market.get('kosdaq', 0) > 0 else ("🔴" if market.get('kospi', 0) < 0 and market.get('kosdaq', 0) < 0 else "🟡")
    msg_market += f"시장 상태: {status_icon} 혼조 / 단기 모멘텀 탐색\n\n"
    msg_market += f"분석:\n{stats.get('total', 0)}개 → {stats.get('final', 0)}개 생존"
    messages.append(msg_market)
    
    leaders = [c for c in candidates if c['type'] == 'LEADER']
    entries = [c for c in candidates if c['type'] == 'ENTRY']
    watches = [c for c in candidates if c['type'] == 'WATCH']
    
    # [2/3] 스캐너 엔진 보고서
    msg_scan = f"{REPORT_ID} [2/3]\n\n"
    msg_scan += f"🔥 <b>SCANNER ENGINE</b>\n\n"
    
    msg_scan += "🎯 <b>ENTRY 후보</b>\n\n"
    if not entries: msg_scan += "없음\n\n"
    for i, c in enumerate(entries[:3], 1):
        msg_scan += f"{i}. <b>{escape(c['name'])}</b>\n"
        msg_scan += f"Score {c['score']}\n\n"
        msg_scan += f"진입:\n{c['buy_p']:,}원 이하\n\n"
        msg_scan += f"상태:\n🟢 눌림 가능 (안정권)\n\n"

    msg_scan += "⚠️ <b>WATCH (감시군)</b>\n\n"
    combined_watch = (leaders + watches)[:3]
    if not combined_watch: msg_scan += "없음\n"
    for i, c in enumerate(combined_watch, 1):
        msg_scan += f"{escape(c['name'])}\n"
        msg_scan += f"Prime {c['prime_score']} | MA20 +{c['ma_gap']}%\n\n"
        msg_scan += "판정:\n❌ 신규 진입 금지\n\n"
                
    messages.append(msg_scan)
    return messages
