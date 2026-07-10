import os
import requests
import asyncio

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

async def send_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        await asyncio.to_thread(requests.post, url, json=payload, timeout=10)
        return True
    except Exception: return False

def format_scan_messages(result, holdings_data=None, p_state=None):
    if not result or "candidates" not in result: return ["⚠️ 시스템 연산 데이터 균열 발생"]
    
    market = result.get("market", {})
    breadth = market.get("breadth", {})
    alert_candidates = result.get("alert_candidates", [])
    slot_full = result.get("slot_full", False)
    
    star_levels = {
        "LEVEL 4": "★★★★★ [즉시 매수 검토]",
        "LEVEL 3": "★★★★☆ [관심]",
        "LEVEL 2": "★★★☆☆ [관찰]",
        "LEVEL 1": "★★☆☆☆ [보류]",
        "LEVEL 0": "★☆☆☆☆ [불가]"
    }
    
    msg = f"━━━━━━━━━━━━━━━━\n"
    msg += f"🌐 <b>시장 모니터링 ({market.get('state', 'NORMAL')})</b>\n"
    msg += f"━━━━━━━━━━━━━━━━\n"
    msg += f"• 코스피 / 코스닥: <b>{market.get('kospi_1d', 0.0)}%</b> / <b>{market.get('kosdaq_1d', 0.0)}%</b>\n"
    
    if breadth.get('trend') == 'Unknown':
        err_msg = breadth.get('error_detail', '수집불가')
        msg += f"• 내부 체력: ⚠️ 시장 폭 데이터 일시 수집 실패 ({err_msg})\n"
    else:
        msg += f"• 내부 체력: <b>{breadth.get('trend', 'Flat')}</b> (AD비율 {breadth.get('avg_ratio', 0)}%)\n"
        msg += f"• 상승/하락 (KP): {breadth.get('kp_up',0)} / {breadth.get('kp_down',0)}\n"
        msg += f"• 상승/하락 (KQ): {breadth.get('kd_up',0)} / {breadth.get('kd_down',0)}\n"
        
    msg += "\n━━━━━━━━━━━━━━━━\n"
    msg += f"💼 <b>포트폴리오 자금 관리</b>\n"
    msg += f"━━━━━━━━━━━━━━━━\n"
    if p_state:
        msg += f"• 계좌 건강도: <b>{p_state.phs_score}점</b> | 태세: <b>{p_state.tier}</b>\n"
        used_slots = len(holdings_data) if holdings_data else 0
        msg += f"• 슬롯 사용현황: <b>{used_slots} / 5 Slots</b>\n"
        msg += f"• 자산 내 현금비중: <b>{max(100 - (used_slots * 15), 5)}%</b>\n\n"
        
    if holdings_data:
        for h in holdings_data:
            h_icon = "🚨" if "청산" in h['judgment'] else "🟢"
            msg += f"{h_icon} <b>{h['name']}</b> | 손익: {h['pnl']}% | 신뢰도: {h['conf']}점\n"
            msg += f" └ 판정: {h['judgment']} | 대피선: {h['stop_p']:,}원\n"
    else:
        msg += "• 보유 현황: <b>등록된 보유종목 없음 (현금 100% 대기)</b>\n"
    
    msg += "\n━━━━━━━━━━━━━━━━\n"
    msg += f"👑 <b>오늘의 진입후보 (Prime Leader)</b>\n"
    msg += f"━━━━━━━━━━━━━━━━\n"
    
    if slot_full:
        msg += "• <b>⚠️ 포트폴리오 슬롯 100% 소진 (신규 매수 발굴 중단)</b>\n"
    elif alert_candidates:
        leader = alert_candidates[0]
        ld = leader["decision"]
        plan = ld["trade_plan"]
        star = star_levels.get(ld['level'], "⚪")
        
        msg += f"<b>{leader['name']}</b> ({leader['code']}) | 현재가 {leader['price']:,}원 ({leader['chg']}%)\n"
        msg += f"• 진입 등급: <b>{star}</b>\n"
        msg += f"• 통합 매수매력도: <b>{ld['composite_rank']}점</b> | 성공확률: {ld['confidence']}점\n"
        msg += f"• 매매 타점: 진입 {plan['entry']:,}원 | 손절 {plan['stop_loss']:,}원 | 목표 {plan['target1']:,}원\n"
        msg += f"• <b>기대 손익비(R:R): {ld['rr_ratio']}</b> | 변동성(ATR): {ld['atr']:,}원\n"
    else:
        msg += "• 당일 매수 기준 통과 종목 없음\n"
        
    msg += "\n━━━━━━━━━━━━━━━━\n"
    msg += f"🚀 <b>실시간 매수대기 TOP 4</b>\n"
    msg += f"━━━━━━━━━━━━━━━━\n"
    if len(alert_candidates) > 1 and not slot_full:
        for idx, c in enumerate(alert_candidates[1:5], 2):
            cd = c["decision"]
            c_star = star_levels.get(cd['level'], "⚪")
            msg += f"{idx}위. <b>{c['name']}</b> | {c['price']:,}원 ({c['chg']}%)\n"
            msg += f" └ {c_star}\n └ 매력도 <b>{cd['composite_rank']}</b> | 성공확률 {cd['confidence']}\n"
    else:
        msg += "• 후순위 매수 대기 후보 없음\n"
    msg += "━━━━━━━━━━━━━━━━\n"
        
    msg_list.append(msg)
    return msg_list
