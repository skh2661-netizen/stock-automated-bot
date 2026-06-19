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

def get_decision_text(ma_gap, current_price, buy_price, pullback_price):
    if ma_gap >= 20: 
        return f"❌ 초과열\n대기: {pullback_price:,}원 부근 눌림 (ATR 기반)"
    elif ma_gap >= 15: 
        return f"⚠️ 과열 주의\n대기: {buy_price:,}원 부근 눌림"
    else:
        if current_price <= buy_price: return "🟢 진입 가능 구간"
        else: return "🟡 진입선 대기"

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
    
    msg1 = f"🎯 <b>V8.4.9 퀀트 시그널</b>\n\n"
    msg1 += f"[{mode_raw}]\n"
    msg1 += f"👉 {mode_desc}\n\n"
    
    msg1 += f"🌎 <b>시장 해석</b>\n"
    msg1 += f"코스피: {kp_str} | 코스닥: {kd_str}\n"
    msg1 += f"해석: {market.get('bias', '보합 / 혼조세')}\n\n"
    
    msg1 += f"📊 <b>스캔 결과</b>\n"
    msg1 += f"전체: {stats.get('total', 0)} -> 최종: {stats.get('final', 0)}\n\n"
    
    msg1 += f"🚨 <b>필터 탈락 분석</b>\n"
    msg1 += f"MA20 이탈: {stats.get('fail_ma20', 0)} | 거래량 부족: {stats.get('fail_vol', 0)}\n"
    msg1 += f"점수 미달: {stats.get('fail_score', 0)} | 과열 이격: {stats.get('fail_heat', 0)}\n"
    msg1 += "=" * 20 + "\n\n"
    
    msg1 += "🔥 <b>핵심 후보 TOP 3</b>\n\n"
    top3 = candidates[:3]
    medals = ["🥇", "🥈", "🥉"]
    for i, c in enumerate(top3):
        safe_name = escape(c['name'])
        decision = get_decision_text(c.get('ma_gap', 0), c['price'], c['buy_p'], c.get('pullback_price', 0))
        
        msg1 += f"{medals[i]} <b>{safe_name}</b>\n"
        # 테스트 모드 시 통과 기준이 45점이었으므로 구분을 위한 라벨 부착
        score_label = f"점수 {c['score']} 🧪" if c['score'] < 55 and mode_raw == "TEST" else f"점수 {c['score']}"
        msg1 += f"{score_label} | 조건 {c.get('cond_count', 0)}/5\n"
        msg1 += f"수급: 거래량 {c.get('vr', 0)}배 | 거래대금 {c.get('amount', 0)//100000000}억\n\n"
        msg1 += f"현재: {c['price']:,}원\n"
        
        if "초과열" not in decision and "과열 주의" not in decision:
            msg1 += f"진입: {c['buy_p']:,}원 이하\n"
            msg1 += f"목표: {c['target_1']:,}원\n"
            
        msg1 += f"판정: {decision}\n"
        msg1 += "-" * 15 + "\n\n"
        
    msg2 = ""
    watch_interest = [c for c in candidates[3:7] if c['score'] >= 60]
    watch_observe = [c for c in candidates[3:] if c not in watch_interest]
    
    if watch_interest or watch_observe:
        if watch_interest:
            msg2 += "⭐ <b>관심 후보</b>\n\n"
            for c in watch_interest:
                # [수정] 실제 순위값 추적
                rank = candidates.index(c) + 1
                safe_name = escape(c['name'])
                decision = get_decision_text(c.get('ma_gap', 0), c['price'], c['buy_p'], c.get('pullback_price', 0))
                
                score_label = f"점수 {c['score']} 🧪" if c['score'] < 55 and mode_raw == "TEST" else f"점수 {c['score']}"
                msg2 += f"⭐ {rank}위. <b>{safe_name}</b>\n"
                msg2 += f"{score_label} | 조건 {c.get('cond_count', 0)}/5\n"
                msg2 += f"판정: {decision}\n\n"
        
        if watch_observe:
            msg2 += "👀 <b>관찰 후보</b>\n\n"
            for c in watch_observe:
                rank = candidates.index(c) + 1
                safe_name = escape(c['name'])
                score_label = f"점수 {c['score']} 🧪" if c['score'] < 55 and mode_raw == "TEST" else f"점수 {c['score']}"
                msg2 += f"{rank}위. <b>{safe_name}</b>\n"
                msg2 += f"{score_label} | 조건 {c.get('cond_count', 0)}/5\n"
                msg2 += f"등락 +{c['chg']}% | MA20 이격 {c['ma_gap']}%\n\n"
    
    messages = [msg1]
    if msg2.strip():
        messages.append(msg2)
        
    return messages
