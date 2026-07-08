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

def format_scan_messages(result, holdings_data=None):
    if not result or "candidates" not in result: return ["⚠️ 데이터 추출 실패"]
    
    market = result.get("market", {})
    breadth = market.get("breadth", {})
    alert_candidates = result.get("alert_candidates", [])
    
    # ✅ 에러 해결: 신규 종목과 보유 종목이 모두 없을 때만 대기 모드 진입
    if (not alert_candidates or len(alert_candidates) == 0) and not holdings_data:
        return ["⚠️ 조건 충족 V9.0 종목 없음 (시스템 대기)"]
        
    msg_list = []
    
    msg = f"📊 <b>V9.0 실전 퀀트 운용 보고서</b>\n\n"
    msg += f"<b>[1] 🌐 시장 요약 ({market.get('state', 'NORMAL')})</b>\n"
    msg += f"• 체력 추세: <b>{breadth.get('trend', 'Flat')}</b> (AD Ratio: {breadth.get('avg_ratio', 0)}%)\n"
    msg += f"• KOSPI: 상승 {breadth.get('kp_up',0)} / 하락 {breadth.get('kp_down',0)}\n"
    msg += f"• KOSDAQ: 상승 {breadth.get('kd_up',0)} / 하락 {breadth.get('kd_down',0)}\n"
    msg += "━" * 16 + "\n\n"
    
    if alert_candidates:
        leader = alert_candidates[0]
        ld = leader["decision"]
        plan = ld["trade_plan"]
        
        msg += f"<b>[2] 👑 Prime Leader</b>\n"
        msg += f"<b>{leader['name']}</b> ({leader['code']}) | {leader['chg']}%\n"
        msg += f"▶ 전략: <b>{ld['primary_strategy']}</b> ⭐⭐⭐\n"
        if ld.get('secondary_strategy'): msg += f"▶ 보조: {ld['secondary_strategy']}\n"
        
        msg += f"\n🎯 <b>[트레이드 플랜]</b>\n"
        msg += f"• 진입: {plan['entry']:,}원\n"
        msg += f"• 목표: {plan['target1']:,}원 (T1)\n"
        msg += f"• 손절: {plan['stop_loss']:,}원 (ATR/Pivot)\n"
        msg += f"• V9 확신도: <b>{ld['confidence']}점</b>\n"
        msg += "━" * 16 + "\n\n"
        
        msg += f"<b>[3] 🚀 실전 운영 TOP 5</b>\n"
        for idx, c in enumerate(alert_candidates[1:6], 2):
            cd = c["decision"]
            msg += f"{idx}위. <b>{c['name']}</b> | {cd['confidence']}점 | {cd['primary_strategy']}\n"
        msg += "━" * 16 + "\n\n"
    else:
        msg += f"<b>[2] 👑 Prime Leader</b>\n"
        msg += "• 신규 조건 충족 종목 없음 (패스)\n"
        msg += "━" * 16 + "\n\n"
    
    msg += f"<b>[4] 💼 포트폴리오 및 청산 알림</b>\n"
    if holdings_data:
        for h in holdings_data:
            # ✅ 에러 해결: 안전하게 래핑된 딕셔너리에서 데이터 추출
            icon = "🚨" if "청산" in h['judgment'] else "🟢"
            msg += f"{icon} {h['name']} | 수익: {h['pnl']}% | Conf: {h['conf']} | 손절: {h['stop_p']:,}원\n"
    else:
        msg += "• 보유 종목 없음\n"
        
    msg_list.append(msg)
    return msg_list
