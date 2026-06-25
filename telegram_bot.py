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
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try: await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='HTML')
    except Exception as e: print(f"❌ 텔레그램 발송 세션 실패: {e}")

def get_decision_text(ma_gap, current_price, buy_price, pullback_price):
    if ma_gap >= 35: 
        return f"❌ 초과열\n⚠️ <b>위험 사유:</b> MA20 이격 +{ma_gap}%\n🚫 단기 상승 과속 (추격 금지)\n대기: {pullback_price:,}원 부근 눌림"
    elif ma_gap >= 25: 
        return f"⚠️ 과열 주의\n⚠️ <b>위험 사유:</b> MA20 이격 +{ma_gap}%\n대기: {buy_price:,}원 부근 눌림"
    else: 
        return "🟢 공략 1순위 구간" if current_price <= buy_price else "🟡 진입선 대기"

def format_scan_messages(scan_result):
    market = scan_result.get("market", {})
    stats = scan_result.get("stats", {})
    candidates = scan_result.get("candidates", [])
    mode_raw = market.get("mode", "UNKNOWN")
    regime = market.get("regime", "NORMAL")
    
    if stats.get('data_error', False):
        return [f"🚨 <b>데이터 공급 장애 감지</b>\n- KRX Universe: 0개\n- 필터 분석 불가\n- 매매 판단 보류\n{'='*20}\n"]
    
    if mode_raw == "PRE_OPEN":
        header_title = "🌅 <b>PRE_OPEN (장전 모드)</b>\n"
        prime_title = "🔥 <b>오늘 관심 후보 (장전)</b>\n\n"
    elif "BREAKOUT" in mode_raw:
        header_title = f"🔥 <b>{mode_raw} (장중 돌파 모드)</b>\n"
        prime_title = "🚀 <b>돌파 주도 후보</b>\n\n"
    elif mode_raw == "CLOSE_BET":
        header_title = "🌙 <b>CLOSE_BET (종가베팅 모드)</b>\n"
        prime_title = "🎯 <b>익일 보유 최우선 후보</b>\n\n"
    else:
        header_title = f"🛠️ <b>{mode_raw} (시스템 검증)</b>\n"
        prime_title = "🔥 <b>Prime 검증 후보</b>\n\n"

    msg1 = f"🎯 <b>V8.4.27 퀀트 시그널</b>\n\n{header_title}"
    msg1 += f"🌎 <b>시장 해석 [{regime}]</b>\n해석: {market.get('bias', '보합')}\n\n"
    msg1 += f"📊 <b>스캔 결과</b>\n전체: {stats.get('total', 0)} -> 1차 통과: {stats.get('pass1', 0)} -> 최종 후보: {stats.get('final', 0)}\n"
    msg1 += "=" * 20 + "\n\n"
    
    if not candidates:
        msg1 += "🔥 <b>발견된 핵심 후보 없음</b>\n\n"
        msg1 += "📉 <b>필터 단계별 탈락 상세 분석</b>\n"
        msg1 += f"- 운영 모드 탈락 (등락률): {stats.get('fail_mode', 0)}개\n"
        msg1 += f"- 과열 컷오프 (MA20 이격): {stats.get('fail_heat', 0)}개\n"
        msg1 += f"- 캔들 위치 탈락 (윗꼬리): {stats.get('fail_position', 0)}개\n"
        msg1 += f"- 역배열 탈락 (MA20 하회): {stats.get('fail_ma20', 0)}개\n"
        msg1 += f"- 거래량 기준 미달: {stats.get('fail_vol', 0)}개\n"
        msg1 += f"- 스코어 컷 미달: {stats.get('fail_score', 0)}개\n"
        msg1 += "=" * 20 + "\n"
        return [msg1]

    msg1 += prime_title
    all_candidates = candidates.copy()
    prime = next((c for c in candidates if c.get('is_prime_leader')), None)
    
    if prime:
        p_score = prime.get('prime_score', 0)
        display_candidates = [c for c in candidates if c['code'] != prime['code']]
        safe_name = escape(prime['name'])
        decision = get_decision_text(prime.get('ma_gap', 0), prime['price'], prime['buy_p'], prime.get('pullback_price', 0))
        
        msg1 += f"👑 <b>{safe_name}</b>\n"
        msg1 += f"종합 {prime['score']}점 | 확신도 {prime.get('conviction', 0)}점 | Prime {p_score}점\n\n"
        
        if mode_raw == "TEST":
            msg1 += f"<b>[가상 시뮬레이션 결과]</b>\n"
            msg1 += f"🌅 PRE_OPEN : {prime.get('test_pre_open', 'N/A')}\n"
            msg1 += f"🔥 BREAKOUT : {prime.get('test_breakout', 'N/A')}\n"
            msg1 += f"🌙 CLOSE_BET: {prime.get('test_close', 'N/A')}\n\n"
        else:
            msg1 += "<b>[선정 이유]</b>\n"
            if mode_raw == "PRE_OPEN":
                msg1 += f"✅ 전일 수급 유지 확인 (평균 대비 {prime.get('amount_strength', 0)}배)\n"
                msg1 += f"✅ 갭 상승 가능성 유효 (RS 강세)\n"
            elif "BREAKOUT" in mode_raw:
                msg1 += f"✅ 폭발적 거래량 터짐 ({prime.get('vr', 0)}배 급증)\n"
                msg1 += f"✅ 강력한 돌파 모멘텀 (1D RS: {prime.get('rs', 0)}%)\n"
            else:
                msg1 += f"✅ MA20 지지선 상단 안정적 구조 (과열 없음)\n"
                msg1 += f"✅ 종가 수급 유지 (강도: {prime.get('amount_strength', 0)}배)\n"
            
        msg1 += f"현재: {prime['price']:,}원\n판정: {decision}\n"
        msg1 += "=" * 20 + "\n\n"
    else:
        msg1 += "👑 <b>Prime Leader : 조건 충족 종목 부재</b>\n"
        msg1 += "=" * 20 + "\n\n"
        display_candidates = candidates

    msg1 += "🔥 <b>핵심 추적 후보 TOP 3</b>\n\n"
    top3 = display_candidates[:3]
    medals = ["🥇", "🥈", "🥉"]
    for i, c in enumerate(top3):
        safe_name = escape(c['name'])
        decision = get_decision_text(c.get('ma_gap', 0), c['price'], c['buy_p'], c.get('pullback_price', 0))
        msg1 += f"{medals[i]} <b>{safe_name}</b>\n"
        msg1 += f"점수 {c['score']} | 확신 {c.get('conviction',0)} | Prime {c.get('prime_score', 0)}\n"
        
        if mode_raw == "TEST":
            msg1 += f"🌅 PRE: {c.get('test_pre_open', 'N/A')} | 🔥 BRK: {c.get('test_breakout', 'N/A')} | 🌙 CLS: {c.get('test_close', 'N/A')}\n"
        elif "BREAKOUT" in mode_raw:
            msg1 += f"수급: 거래량 {c.get('vr', 0)}배 | 1D RS: 강세 ({c.get('rs', 0)}%)\n"
        else:
            msg1 += f"수급: 대금 {c.get('amount', 0)//100000000}억 | 1D RS: {c.get('rs', 0)}%\n"
            
        msg1 += f"현재: {c['price']:,}원\n"
        if "초과열" not in decision and "과열 주의" not in decision:
            msg1 += f"진입: {c['buy_p']:,}원 이하\n목표: {c['target_1']:,}원\n"
        msg1 += f"판정: {decision}\n"
        msg1 += "-" * 15 + "\n\n"
        
    return [msg1]
