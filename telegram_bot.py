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
    
    # 1. 헤더 (시장 상태 및 리스크 요약)
    header = f"🎯 <b>퀀트 시그널 ({mode})</b>\n\n"
    header += f"🚨 <b>MARKET RISK</b>\n"
    header += f"KOSPI: {kp_1d}%\n"
    header += f"KOSDAQ: {kd_1d}%\n"
    header += f"위험등급: {risk_level}\n"
    header += f"시장 상태: {market_score}/100\n"
    header += f"생존 후보: {stats.get('final', 0)} / {stats.get('total', 0)}\n"
    header += "─" * 20
    messages.append(header)
    
    if not candidates:
        messages.append("🔥 <b>발견된 핵심 후보 없음</b>\n폭락 또는 수급 이탈 장세입니다.")
        return messages
        
    # 2. 후보 종목 상세 리포트
    for idx, c in enumerate(candidates, 1):
        name = escape(c.get('name', ''))
        c_type = c.get('type', 'WATCH')
        
        # 타이틀 및 아이콘 매핑
        if c.get('is_prime_leader'):
            title = f"👑 PRIME LEADER\n{idx}) {name}"
        elif c_type == "LEADER":
            title = f"🚀 LEADER\n{idx}) {name}"
        elif c_type == "ENTRY":
            title = f"🟢 ENTRY\n{idx}) {name}"
        else:
            title = f"👀 WATCH\n{idx}) {name}"
            
        msg = f"<b>{title}</b>\n\n"
        
        msg += f"⭐ <b>PRIME FINAL : {c.get('prime_final', 0)}</b>\n"
        msg += f"Score : {c.get('score', 0)}\n"
        msg += f"Prime : {c.get('prime_score', 0)}\n"
        msg += f"Conviction : {c.get('conviction', 0)}\n\n"
        
        msg += f"💰 <b>현재가</b>\n"
        msg += f"{c.get('price', 0):,}원 ({c.get('chg', 0)}%)\n\n"
        
        msg += f"🎯 <b>전략</b>\n"
        msg += f"관심 : {c.get('pullback_price', 0):,}\n"
        msg += f"목표1 : {c.get('target_1', 0):,}\n"
        msg += f"목표2 : {c.get('target_2', 0):,}\n"
        msg += f"손절 : {c.get('stop_p', 0):,}\n\n"
        
        msg += f"📊 <b>수급</b>\n"
        amount_100m = int(c.get('amount', 0) // 100000000)
        msg += f"거래대금 : {amount_100m:,}억\n"
        msg += f"거래량강도 : {c.get('amount_strength', 0)}배\n\n"
        
        msg += f"💪 <b>상대강도</b>\n"
        msg += f"1D {'+' if c.get('rs_1d', 0)>0 else ''}{c.get('rs_1d', 0)}%\n"
        msg += f"5D {'+' if c.get('rs_5d', 0)>0 else ''}{c.get('rs_5d', 0)}%\n"
        msg += f"20D {'+' if c.get('rs_20d', 0)>0 else ''}{c.get('rs_20d', 0)}%\n\n"
        
        msg += f"📏 <b>위치</b>\n"
        msg += f"20MA {'+' if c.get('ma_gap', 0)>0 else ''}{c.get('ma_gap', 0)}%\n\n"
        
        # 판단 근거 출력
        reasons = c.get('reason', [])
        if not reasons:
            if c.get('prime_score', 0) >= 70: reasons.append("시장 대비 상대강도 우위")
            if c.get('amount_strength', 0) >= 1.5: reasons.append("안정적 수급 유입")
            if not reasons: reasons.append("특이사항 없음")
            
        reason_text = "\n- ".join(reasons)
        msg += f"🧠 <b>판단:</b>\n- {reason_text}\n"
        
        messages.append(msg)
        
    return messages

def format_holding_report(h):
    if not h: return ["📊 <b>보유 현황</b>\n보유 중인 종목이 없습니다."]
    return ["📊 <b>보유 현황</b>\n" + "\n".join([f"- {i[1]}" for i in h])]
