import os
from telegram import Bot
from html import escape

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

async def send_message(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("텔레그램 토큰/CHAT_ID 누락")
        return
    bot = Bot(token=TELEGRAM_TOKEN)
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='HTML')
    except Exception as e:
        print(f"텔레그램 발송 오류: {e}")

def get_decision_text(ma_gap, current_price, buy_price):
    if ma_gap >= 20: return "❌ 초과열 (깊은 눌림 대기)"
    elif ma_gap >= 15: return "⚠️ 과열 주의 (비중 축소)"
    else:
        if current_price <= buy_price:
            return "🟢 진입 가능 구간"
        else:
            return "🟡 진입선 대기"

def format_scan_messages(scan_result):
    market = scan_result.get("market", {})
    stats = scan_result.get("stats", {})
    candidates = scan_result.get("candidates", [])
    
    mode_raw = market.get("mode", "UNKNOWN")
    mode_text_map = {
        "PRE_OPEN": "☀️ 장 시작 전 갭 상승 후보 정찰",
        "BREAKOUT_1": "🚀 장초반 돌파 1군 탐색",
        "BREAKOUT_2": "🔥 장중 모멘텀 및 수급 탐색",
        "CLOSE_BET": "🎯 종가 베팅 후보 압축",
        "REVIEW": "📘 당일 복기",
        "TEST": "🛠️ 시스템 검증용 (매매 제외)"
    }
    mode_desc = mode_text_map.get(mode_raw, mode_raw)
    
    kp_str = f"+{market.get('kospi', 0)}%" if market.get('kospi', 0) > 0 else f"{market.get('kospi', 0)}%"
    kd_str = f"+{market.get('kosdaq', 0)}%" if market.get('kosdaq', 0) > 0 else f"{market.get('kosdaq', 0)}%"
    
    msg1 = f"🎯 <b>V8.4.7 퀀트 시그널</b>\n\n"
    msg1 += f"[{mode_raw}]\n"
    msg1 += f"👉 {mode_desc}\n\n"
    
    msg1 += f"🌎 <b>시장 해석</b>\n"
    msg1 += f"코스피: {kp_str} | 코스닥: {kd_str}\n"
    msg1 += f"해석: {market.get('bias', '보합 / 혼조세')}\n\n"
    
    msg1 += f"📊 <b>스캔 결과</b>\n"
    msg1 += f"전체: {stats.get('total', 0)} -> 최종 후보: {stats.get('final', 0)}\n\n"
    
    msg1 += f"🚨 <b>필터 탈락 분석</b>\n"
    msg1 += f"MA20 이탈: {stats.get('fail_ma20', 0)} | 거래량 부족: {stats.get('fail_vol', 0)}\n"
    msg1 += f"점수 미달: {stats.get('fail_score', 0)} | 과열 이격: {stats.get('fail_heat', 0)}\n"
    msg1 += "=" * 20 + "\n\n"
    
    msg1 += "🔥 <b>핵심 후보 TOP 3</b>\n\n"
    top3 = candidates[:3]
    medals = ["🥇", "🥈", "🥉"]
    for i, c in enumerate(top3):
        safe_name = escape(c['name'])
        decision = get_decision_text(c.get('ma_gap', 0), c['price'], c['buy_p'])
        
        msg1 += f"{medals[i]} <b>{safe_name}</b>\n"
        msg1 += f"점수 {c['score']} | 조건 {c.get('cond_count', 0)}/5\n"
        # [수정] 수급 데이터 추가 보고
        msg1 += f"수급: 거래량 {c.get('vr', 0)}배 | 거래대금 {c.get('amount', 0)//100000000}억\n\n"
        msg1 += f"현재: {c['price']:,}원\n"
        msg1 += f"진입: {c['buy_p']:,}원 이하\n"
        msg1 += f"목표: {c['target_1']:,}원\n"
        msg1 += f"판정: {decision}\n"
        msg1 += "-" * 15 + "\n\n"
        
    msg2 = ""
    watch_interest = candidates[3:5]
    watch_observe = candidates[5:10]
    
    if watch_interest or watch_observe:
        if watch_interest:
            msg2 += "⭐ <b>관심 후보</b>\n\n"
            for i, c in enumerate(watch_interest, 4):
                safe_name = escape(c['name'])
                decision = get_decision_text(c.get('ma_gap', 0), c['price'], c['buy_p'])
                msg2 += f"⭐ {i}위. <b>{safe_name}</b>\n"
                msg2 += f"점수 {c['score']} | 조건 {c.get('cond_count', 0)}/5\n"
                msg2 += f"판정: {decision}\n\n"
        
        if watch_observe:
            msg2 += "👀 <b>관찰 후보</b>\n\n"
            for i, c in enumerate(watch_observe, 4 + len(watch_interest)):
                safe_name = escape(c['name'])
                msg2 += f"{i}. <b>{safe_name}</b>\n"
                msg2 += f"점수 {c['score']} | 조건 {c.get('cond_count', 0)}/5\n"
                msg2 += f"등락 +{c['chg']}% | MA20 이격 {c['ma_gap']}%\n\n"
    
    messages = [msg1]
    if msg2.strip():
        messages.append(msg2)
        
    return messages
