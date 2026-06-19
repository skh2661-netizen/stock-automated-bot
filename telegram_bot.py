import os
from telegram import Bot
from html import escape # [수정 5: HTML 특수문자 에러 방지]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

async def send_message(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("텔레그램 토큰 또는 CHAT_ID가 없습니다.")
        return
    bot = Bot(token=TELEGRAM_TOKEN)
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='HTML')
    except Exception as e:
        print(f"텔레그램 오류: {e}")

def get_decision_text(ma_gap):
    # [추가] 과열도 기반 판정 텍스트 산출
    if ma_gap >= 20: return "❌ 초과열 (깊은 눌림 대기)"
    elif ma_gap >= 15: return "⚠️ 과열 주의 (비중 축소)"
    else: return "✅ 눌림 진입 가능"

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
        "TEST": "🛠️ 시스템 테스트 모드"
    }
    mode_desc = mode_text_map.get(mode_raw, mode_raw)
    
    kp_str = f"+{market.get('kospi', 0)}%" if market.get('kospi', 0) > 0 else f"{market.get('kospi', 0)}%"
    kd_str = f"+{market.get('kosdaq', 0)}%" if market.get('kosdaq', 0) > 0 else f"{market.get('kosdaq', 0)}%"
    
    # --- [메시지 1: 메인 브리핑 + TOP 3] ---
    msg1 = f"🎯 <b>V8.4.6 퀀트 시그널</b>\n\n"
    msg1 += f"[{mode_raw}]\n"
    msg1 += f"👉 {mode_desc}\n\n"
    
    msg1 += f"🌎 <b>시장 상태</b>\n"
    msg1 += f"코스피: {kp_str}\n"
    msg1 += f"코스닥: {kd_str}\n"
    msg1 += f"위험도: LOW\n\n"
    
    msg1 += f"📊 <b>스캔 결과</b>\n"
    msg1 += f"전체: {stats.get('total', 0)}\n"
    msg1 += f"1차 통과: {stats.get('pass1', 0)}\n"
    msg1 += f"최종 후보: {stats.get('final', 0)}\n\n"
    
    msg1 += f"🚨 <b>필터 탈락 분석</b>\n"
    msg1 += f"MA20 이탈: {stats.get('fail_ma20', 0)}개\n"
    msg1 += f"거래량 부족: {stats.get('fail_vol', 0)}개\n"
    msg1 += f"점수 미달: {stats.get('fail_score', 0)}개\n"
    msg1 += f"과열 이격 초과: {stats.get('fail_heat', 0)}개\n" # [수정 3 반영]
    msg1 += "=" * 20 + "\n\n"
    
    msg1 += "🔥 <b>핵심 후보 TOP 3</b>\n\n"
    top3 = candidates[:3]
    medals = ["🥇", "🥈", "🥉"]
    for i, c in enumerate(top3):
        safe_name = escape(c['name'])
        decision = get_decision_text(c.get('ma_gap', 0))
        
        msg1 += f"{medals[i]} <b>{safe_name}</b>\n"
        msg1 += f"점수 {c['score']} | 조건 {c.get('cond_count', 0)}/5\n\n"
        msg1 += f"현재: {c['price']:,}원\n"
        msg1 += f"진입: {c['buy_p']:,}원\n"
        msg1 += f"목표: {c['target_1']:,}원\n"
        msg1 += f"판정: {decision}\n"
        msg1 += "-" * 15 + "\n\n"
        
    # --- [메시지 2: 관심 및 관찰] ---
    msg2 = ""
    watch_interest = candidates[3:5]
    watch_observe = candidates[5:10]
    
    if watch_interest or watch_observe:
        if watch_interest:
            msg2 += "⭐ <b>관심 후보</b>\n\n"
            for i, c in enumerate(watch_interest, 4):
                safe_name = escape(c['name'])
                decision = get_decision_text(c.get('ma_gap', 0))
                msg2 += f"⭐ {i}위. <b>{safe_name}</b>\n"
                msg2 += f"점수 {c['score']} | 조건 {c.get('cond_count', 0)}/5\n"
                msg2 += f"판정: {decision}\n\n"
        
        if watch_observe:
            msg2 += "👀 <b>관찰 후보</b>\n\n"
            for i, c in enumerate(watch_observe, 4 + len(watch_interest)):
                safe_name = escape(c['name'])
                msg2 += f"{i}. {safe_name} (+{c['chg']}%)\n"
    
    messages = [msg1]
    if msg2.strip():
        messages.append(msg2)
        
    return messages
