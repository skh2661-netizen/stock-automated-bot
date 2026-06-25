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
    if not holding_results: return ["📌 <b>HOLDING ENGINE</b>\n\n등록된 보유 종목 없음"]
        
    msg = "📌 <b>HOLDING ENGINE (보유 종목 점검)</b>\n\n"
    for r in holding_results:
        exit_icon = "🚨" if r['exit_score'] >= 6 else "🛡️"
        msg += f"👑 <b>{escape(r['name'])}</b>\n"
        msg += f"매수가: {r['buy_p']:,}원 | 현재가: {r['curr_p']:,}원\n"
        msg += f"손익: <b>{r['pnl']}%</b>\n\n"
        
        msg += f"기업: {r['corp']} | 차트: {r['chart']} | EXIT: {r['exit_score']}/10\n"
        msg += f"전략: {r['judgment']}\n"
        msg += "-" * 20 + "\n"
        
    return [msg]

def format_scan_messages(scan_result):
    stats = scan_result.get("stats", {})
    candidates = scan_result.get("candidates", [])
    market = scan_result.get("market", {})
    mode_raw = market.get("mode", "UNKNOWN")
    
    if stats.get('data_error', False): return ["🚨 데이터 공급 장애 감지"]

    # [V8.8] 텔레그램 메시지 분할 전송 (List Array 반환)
    messages = []
    
    # 1번 메시지: 시장 판단
    msg_market = f"🎯 <b>V8.8 시장 판단 ({mode_raw})</b>\n\n"
    msg_market += f"코스피: {market.get('kospi', 0)}%\n"
    msg_market += f"코스닥: {market.get('kosdaq', 0)}%\n\n"
    msg_market += f"분석: 총 {stats.get('total', 0)}개 중 {stats.get('final', 0)}개 생존"
    messages.append(msg_market)
    
    leaders = [c for c in candidates if c['type'] == 'LEADER']
    entries = [c for c in candidates if c['type'] == 'ENTRY']
    watches = [c for c in candidates if c['type'] == 'WATCH']
    
    # 2번 메시지: 스캐너 엔진 (장전/장중)
    if mode_raw != "CLOSE_BET":
        msg_scan = f"🔥 <b>SCANNER ENGINE ({mode_raw})</b>\n\n"
        
        msg_scan += "🎯 <b>매수 검토 후보</b>\n"
        if not entries: msg_scan += "없음\n\n"
        for i, c in enumerate(entries[:3], 1):
            msg_scan += f"{i}. <b>{escape(c['name'])}</b> | Score {c['score']}\n"
            msg_scan += f"└ 진입: {c['buy_p']:,}원 부근\n\n"

        msg_scan += "⚠️ <b>시장 주도 감시군</b>\n"
        combined_watch = (leaders + watches)[:2]
        if not combined_watch: msg_scan += "없음\n"
        for i, c in enumerate(combined_watch, 1):
            msg_scan += f"{i}. <b>{escape(c['name'])}</b> | Score {c['score']}\n"
            if c['is_overheated']:
                msg_scan += f"상태: ⚠️ 추세 강하지만 과열\n"
                msg_scan += f"판정: ❌ 신규 진입 금지\n"
                msg_scan += f"이유: MA20 +{c['ma_gap']}% (단기 기대감 선반영)\n\n"
            else:
                msg_scan += f"상태: 추세 관찰\n\n"
                
        messages.append(msg_scan)
        
    # 3번 메시지: 종가 베팅 모드일 경우 별도 분리
    if mode_raw == "CLOSE_BET":
        msg_close = f"🌙 <b>CLOSE BET (종가 후보)</b>\n\n"
        
        if not entries: msg_close += "없음\n\n"
        for i, c in enumerate(entries[:3], 1):
            msg_close += f"{i}. <b>{escape(c['name'])}</b> | Score {c['score']}\n"
            msg_close += f"└ 진입: {c['buy_p']:,}원 부근 분할 매수\n\n"
            
        msg_close += "📌 <b>내일 관심 예약</b>\n"
        combined_watch = (leaders + watches)[:2]
        if not combined_watch: msg_close += "없음\n"
        for i, c in enumerate(combined_watch, 1):
            msg_close += f"{i}. <b>{escape(c['name'])}</b> | MA20 +{c['ma_gap']}%\n"
            msg_close += f"└ 판정: ❌ 신규 진입 금지 (눌림 대기)\n\n"
            
        messages.append(msg_close)

    return messages
