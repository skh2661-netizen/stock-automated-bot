from telegram import Bot
from html import escape
import os
import traceback

bot = Bot(token=os.environ.get("TELEGRAM_TOKEN")) if os.environ.get("TELEGRAM_TOKEN") else None

async def send_message(text):
    if bot: 
        try:
            await bot.send_message(chat_id=os.environ.get("TELEGRAM_CHAT_ID"), text=text, parse_mode='HTML')
        except Exception:
            traceback.print_exc()

def format_scan_messages(data):
    stats = data.get('stats', {})
    candidates = data.get('candidates', [])
    market = data.get('market', {})
    mode = market.get('mode', 'UNKNOWN')
    market_score = market.get('market_score', 100)
    kp_1d = market.get('kospi', 0.0)
    kd_1d = market.get('kosdaq', 0.0)
    risk_level = market.get('risk_level', 1)
    
    if stats.get('data_error'): 
        return ["🚨 <b>데이터 공급 장애 발생</b>\n점검이 필요합니다."]
    
    messages = []
    
    # ---------------------------------------------------------
    # 메시지 1: V8.8.8 DAILY QUANT REPORT (시장 종합)
    # ---------------------------------------------------------
    market_msg = f"🎯 <b>V8.8.8 DAILY QUANT REPORT ({mode})</b>\n\n"
    market_msg += f"📊 <b>시장 종합:</b>\n"
    market_msg += f"KOSPI: {kp_1d}% | KOSDAQ: {kd_1d}%\n"
    market_msg += f"시장점수: {market_score}/100\n\n"
    
    market_msg += f"🧠 <b>시장 판단:</b>\n"
    if risk_level == 3:
        market_msg += "🚨 극단적 약세장\n신규 진입 보수적 대응"
    elif risk_level == 2:
        market_msg += "⚠️ 조정 장세\n비중 축소 및 선별적 접근"
    else:
        market_msg += "✅ 정상 장세\n조건 충족 시 전략 진입"
        
    market_msg += f"\n\n(생존 후보: {stats.get('final', 0)} / {stats.get('total', 0)})"
    messages.append(market_msg)
    
    if not candidates:
        messages.append("🔥 <b>발견된 핵심 후보 없음</b>\n모든 종목이 필터를 통과하지 못했습니다.")
        return messages
        
    # ---------------------------------------------------------
    # 메시지 2: PRIME WATCH (1위 종목 심층 분석)
    # ---------------------------------------------------------
    prime = next((c for c in candidates if c.get('is_prime_leader')), candidates[0])
    
    reasons = prime.get('reason', [])
    if not reasons:
        if prime.get('prime_score', 0) >= 70: reasons.append("시장 대비 상대강도 우위")
        if prime.get('amount_strength', 0) >= 1.5: reasons.append("안정적 수급 유입")
        if not reasons: reasons.append("특이사항 없음")
    reason_text = "\n- ".join(reasons)
    
    top_msg = f"👑 <b>PRIME WATCH (오늘의 최우선 관찰)</b>\n\n"
    
    top_msg += f"<b>1위 {escape(prime.get('name', ''))}</b>\n"
    top_msg += f"등급: {prime.get('type', '👀 관망')}\n"
    top_msg += f"⭐ <b>Final {prime.get('prime_final', 0)}</b>\n\n"
    
    # [수정] 매매 판단 레이어 (시장 리스크 + 종목 상대강도 결합)
    rs20 = prime.get('rs_20d', 0)
    top_msg += f"⚠️ <b>매매 판단:</b>\n"
    if risk_level == 3:
        if rs20 > 20:
            top_msg += "🟡 <b>강한 종목 선별:</b> 시장 급락 속 주도력 유지 (분할 접근)\n\n"
        else:
            top_msg += "🔴 <b>관망:</b> 시장 리스크 과다 (신규 진입 보수적)\n\n"
    elif risk_level == 2:
        if rs20 > 15:
            top_msg += "🟢 <b>조건 충족:</b> 시장 조정 대비 강한 방어력 (전략 진입)\n\n"
        else:
            top_msg += "🟡 <b>관심 유지:</b> 시장 안정 확인 후 눌림 접근\n\n"
    else:
        top_msg += "🟢 <b>조건 충족:</b> 현재 전략에 맞춰 접근 가능\n\n"
    
    top_msg += f"🧠 <b>상태 분석:</b>\n- {reason_text}\n\n"
    
    top_msg += f"💰 <b>가격 전략:</b>\n"
    top_msg += f"현재가: {prime.get('price', 0):,}원 ({prime.get('chg', 0)}%)\n"
    top_msg += f"관심가(1차대기): {prime.get('pullback_price', 0):,}원\n"
    top_msg += f"진입가(주문기준): {prime.get('buy_p', 0):,}원\n"
    top_msg += f"목표가: {prime.get('target_1', 0):,}원 / {prime.get('target_2', 0):,}원\n"
    top_msg += f"손절가(필수): {prime.get('stop_p', 0):,}원\n\n"
    
    top_msg += f"🔥 <b>핵심 수급 및 강도:</b>\n"
    top_msg += f"Prime: {prime.get('prime_score', 0)} | Conviction: {prime.get('conviction', 0)}\n"
    top_msg += f"RS 20D: {'+' if prime.get('rs_20d', 0)>0 else ''}{prime.get('rs_20d', 0)}%\n"
    top_msg += f"MA 이격: {'+' if prime.get('ma_gap', 0)>0 else ''}{prime.get('ma_gap', 0)}%\n"
    top_msg += f"거래대금: {int(prime.get('amount', 0) // 100000000):,}억\n"
    
    messages.append(top_msg)
    
    # ---------------------------------------------------------
    # 메시지 3: 후보 리스트 (TOP 2~10)
    # ---------------------------------------------------------
    if len(candidates) > 1:
        list_msg = "📋 <b>후보 리스트 (TOP 2~10)</b>\n\n"
        display_count = 1
        for c in candidates:
            if c.get('is_prime_leader'): continue
            
            c_type = c.get('type', '')
            icon = "🔥" if "최우선" in c_type else "🟢" if "진입" in c_type else "♻️" if "낙폭" in c_type else "⏳"
            
            # [수정] 순위 번호 버그 픽스
            list_msg += f"{display_count + 1}. {icon} <b>{escape(c.get('name', ''))}</b> (Final {c.get('prime_final', 0)})\n"
            list_msg += f"   ┗ RS20D {'+' if c.get('rs_20d', 0)>0 else ''}{c.get('rs_20d', 0)}% | Conv {c.get('conviction', 0)} | MA {'+' if c.get('ma_gap',0)>0 else ''}{c.get('ma_gap',0)}%\n"
            list_msg += f"   ┗ 판정: {c_type}\n\n"
            
            display_count += 1
            if display_count >= 10: break
            
        list_msg += "상세 데이터 필요시 별도 조회 요망"
        messages.append(list_msg)
        
    return messages

def format_holding_report(h):
    if not h: return ["📊 <b>보유 현황</b>\n보유 중인 종목이 없습니다."]
    return ["📊 <b>보유 현황</b>\n" + "\n".join([f"- {i[1]}" for i in h])]
