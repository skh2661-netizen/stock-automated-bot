import os
from telegram import Bot
from html import escape

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if TELEGRAM_TOKEN:
    bot = Bot(token=TELEGRAM_TOKEN)
else:
    bot = None

async def send_message(text):
    if not TELEGRAM_TOKEN or not CHAT_ID: 
        print("❌ [환경변수 탈락] TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID 값이 유실되었습니다.")
        return
    try: 
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='HTML')
        print("🟢 텔레그램 통신 세션 발송 성공")
    except Exception as e: 
        print(f"❌ 텔레그램 발송 세션 실패: {e}")

def get_decision_text(ma_gap, current_price, buy_price, pullback_price):
    if ma_gap >= 20: return f"❌ 초과열\n대기: {pullback_price:,}원 부근 눌림 (ATR)"
    elif ma_gap >= 15: return f"⚠️ 과열 주의\n대기: {buy_price:,}원 부근 눌림"
    else: return "🟢 공략 1순위 구간" if current_price <= buy_price else "🟡 진입선 대기"

def format_scan_messages(scan_result):
    market = scan_result.get("market", {})
    stats = scan_result.get("stats", {})
    candidates = scan_result.get("candidates", [])
    mode_raw = market.get("mode", "UNKNOWN")
    regime = market.get("regime", "NORMAL")
    
    mode_text_map = {
        "PRE_OPEN": "☀️ 장 시작 전 갭 상승 후보 정찰", "BREAKOUT_1": "🚀 장초반 돌파 1군 탐색",
        "BREAKOUT_2": "🔥 장중 모멘텀 및 수급 탐색", "CLOSE_BET": "🎯 종가 베팅 후보 압축",
        "REVIEW": "📘 당일 복기", "TEST": "🛠️ 시스템 검증용 (매매 제외)"
    }
    
    kp_str = f"+{market.get('kospi', 0)}%" if market.get('kospi', 0) > 0 else f"{market.get('kospi', 0)}%"
    kd_str = f"+{market.get('kosdaq', 0)}%" if market.get('kosdaq', 0) > 0 else f"{market.get('kosdaq', 0)}%"
    
    msg1 = f"🎯 <b>V8.4.22 퀀트 시그널</b>\n\n[{mode_raw}]\n👉 {mode_text_map.get(mode_raw, mode_raw)}\n\n"
    msg1 += f"🌎 <b>시장 해석 [{regime}]</b>\n코스피: {kp_str} | 코스닥: {kd_str}\n해석: {market.get('bias', '보합')}\n\n"
    msg1 += f"📊 <b>스캔 결과</b>\n최종 후보: {stats.get('final', 0)}개\n"
    if regime == "PANIC": msg1 += f"패닉장 탈락: {stats.get('fail_panic', 0)}개\n"
    msg1 += "=" * 20 + "\n\n"
    
    if not candidates:
        msg1 += "🔥 <b>오늘의 시장 주도 후보 : 없음</b>\n\n"
        msg1 += "🚨 <b>[전술 지침] 자산 보호 및 공격 보류</b>\n"
        msg1 += f"1. <b>상태 요약:</b> 시장 심리 위축 및 임계 타점 충족군 전멸\n"
        msg1 += f"2. <b>리스크 요인:</b> 코스닥 변동성 이격 및 주도 세력 유입 부재\n"
        msg1 += "3. <b>운용 전략:</b> <b>현금 비중 100% 유지</b> 후 안전선 대기\n"
        msg1 += "=" * 20 + "\n"
        return [msg1]

    msg1 += "🔥 <b>Prime 후보 탐색 결과</b>\n\n"
    all_candidates = candidates.copy()
    prime = next((c for c in candidates if c.get('is_prime_leader')), None)
    
    if prime:
        p_score = prime.get('prime_score', 0)
        if p_score >= 80: grade = "🔥🔥 <b>오늘의 프라임 리더 (Prime Leader)</b>"
        elif p_score >= 65: grade = "⭐ <b>오늘의 프라임 워치 (Prime Watch)</b>"
        else: grade = "👀 <b>오늘의 프라임 모니터 (Prime Monitor)</b>"
        
        msg1 += f"{grade}\n\n"
        display_candidates = [c for c in candidates if c['code'] != prime['code']]
        safe_name = escape(prime['name'])
        decision = get_decision_text(prime.get('ma_gap', 0), prime['price'], prime['buy_p'], prime.get('pullback_price', 0))
        
        msg1 += f"👑 <b>{safe_name}</b>\n"
        msg1 += f"종합 {prime['score']}점 | 확신도 {prime.get('conviction', 0)}점 | Prime {p_score}점\n\n"
        msg1 += "<b>[선정 이유]</b>\n"
        msg1 += f"✅ 최근 5일 대금 유입 강도 (평균 대비 {prime.get('amount_strength', 0)}배 지속)\n"
        msg1 += f"✅ 3중 시계열 상대강도(RS 1D/5D/20D) 다차원 돌파\n"
        msg1 += f"✅ 차트 구조적 안전 마진 확인 (MA20 +{prime.get('ma_gap', 0)}%)\n\n"
        msg1 += f"현재: {prime['price']:,}원\n판정: {decision}\n"
        msg1 += "=" * 20 + "\n\n"
    else:
        msg1 += "👑 <b>Prime Leader : 없음 (조건 충족 종목 부재)</b>\n"
        msg1 += "=" * 20 + "\n\n"
        display_candidates = candidates

    msg1 += "🔥 <b>현재 최고 핵심 후보 TOP 3</b>\n\n"
    top3 = display_candidates[:3]
    medals = ["🥇", "🥈", "🥉"]
    for i, c in enumerate(top3):
        safe_name = escape(c['name'])
        decision = get_decision_text(c.get('ma_gap', 0), c['price'], c['buy_p'], c.get('pullback_price', 0))
        msg1 += f"{medals[i]} <b>{safe_name}</b>\n"
        msg1 += f"점수 {c['score']} | 확신 {c.get('conviction',0)} | Prime {c.get('prime_score', 0)}\n"
        msg1 += f"수급: 대금 {c.get('amount', 0)//100000000}억 | 1D RS: {c.get('rs', 0)}%\n\n"
        msg1 += f"현재: {c['price']:,}원\n"
        if "초과열" not in decision and "과열 주의" not in decision:
            msg1 += f"진입: {c['buy_p']:,}원 이하\n목표: {c['target_1']:,}원\n"
        msg1 += f"판정: {decision}\n"
        msg1 += "-" * 15 + "\n\n"
        
    msg2 = ""
    risk_level = market.get('risk_pct', 1)
    interest_cut = 55 if risk_level >= 2 else 60
    watch_interest = [c for c in display_candidates[3:] if c['score'] >= interest_cut]
    watch_observe = [c for c in display_candidates[3:] if c not in watch_interest]
    
    if watch_interest or watch_observe:
        if watch_interest:
            msg2 += "⭐ <b>관심 후보</b>\n\n"
            for c in watch_interest:
                abs_rank = all_candidates.index(c) + 1
                msg2 += f"⭐ {abs_rank}위. <b>{escape(c['name'])}</b>\n"
                msg2 += f"점수 {c['score']} | Prime {c.get('prime_score', 0)} | 조건 {c.get('cond_count', 0)}/5\n\n"
        if watch_observe:
            msg2 += "👀 <b>관찰 후보</b>\n\n"
            for c in watch_observe:
                abs_rank = all_candidates.index(c) + 1
                msg2 += f"{abs_rank}위. <b>{escape(c['name'])}</b>\n"
                msg2 += f"점수 {c['score']} | 등락 +{c['chg']}%\n\n"
    
    messages = [msg1]
    if msg2.strip(): messages.append(msg2)
    return messages
