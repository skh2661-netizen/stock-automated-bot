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
    except Exception as e: print(f"❌ 텔레그램 발송 세션 실패: {e}")

def format_scan_messages(scan_result):
    market = scan_result.get("market", {})
    stats = scan_result.get("stats", {})
    candidates = scan_result.get("candidates", [])
    mode_raw = market.get("mode", "UNKNOWN")
    
    if stats.get('data_error', False):
        return [f"🚨 <b>데이터 공급 장애 감지</b>\n- 필터 분석 불가\n- 매매 판단 보류\n"]

    msg1 = f"🎯 <b>V8.5 퀀트 시그널 ({mode_raw})</b>\n\n"
    
    # 카테고리별 분류
    leaders = [c for c in candidates if c['type'] == 'LEADER']
    entries = [c for c in candidates if c['type'] == 'ENTRY']
    watches = [c for c in candidates if c['type'] == 'WATCH']
    
    # 1. 🔥 시장 주도 감시군 (LEADER)
    msg1 += "🔥 <b>시장 주도 감시군</b>\n\n"
    if not leaders: msg1 += "없음\n\n"
    for i, c in enumerate(leaders[:2], 1):
        status_txt = "과열 진입 대기" if c['is_overheated'] else "추세 관찰"
        msg1 += f"{i}. <b>{escape(c['name'])}</b>\n"
        msg1 += f"Prime {c['prime_score']} | MA20 +{c['ma_gap']}%\n"
        msg1 += f"상태: {status_txt}\n\n"
        
    # 2. 🎯 실제 매수 후보 (ENTRY in PRE_OPEN / BREAKOUT)
    if mode_raw in ["PRE_OPEN", "BREAKOUT_1", "BREAKOUT_2", "TEST"]:
        msg1 += "🎯 <b>실제 매수 후보</b>\n\n"
        if not entries: msg1 += "없음\n\n"
        for i, c in enumerate(entries[:3], 1):
            msg1 += f"{i}. <b>{escape(c['name'])}</b>\n"
            msg1 += f"Score {c['score']} | 확신도 {c['conviction']}\n"
            msg1 += f"판정: 진입 가능 ({c['buy_p']:,}원 이하)\n\n"

    # 3. 🌙 종가 베팅 후보 (ENTRY in CLOSE_BET)
    if mode_raw in ["CLOSE_BET", "TEST"]:
        msg1 += "🌙 <b>종가 베팅 후보</b>\n\n"
        if not entries: msg1 += "없음\n\n"
        for i, c in enumerate(entries[:3], 1):
            msg1 += f"{i}. <b>{escape(c['name'])}</b>\n"
            msg1 += f"Score {c['score']} | MA20 +{c['ma_gap']}%\n"
            msg1 += f"판정: 익일 갭 기대 (안정성 우수)\n\n"

    # 4. 📌 내일 관심 예약 (WATCH)
    msg1 += "📌 <b>내일 관심 예약 (눌림 대기)</b>\n"
    if not watches: msg1 += "없음\n"
    for c in watches[:5]:
        msg1 += f"- {escape(c['name'])} (Prime {c['prime_score']})\n"

    msg1 += f"\n{'='*20}\n스캔 완료: 총 {stats.get('total', 0)} 종목"
    return [msg1]
