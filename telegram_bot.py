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
    
    if (not alert_candidates or len(alert_candidates) == 0) and not holdings_data:
        return ["⚠️ 조건 충족 V9.1 종목 없음 (시스템 대기)"]
        
    msg_list = []
    
    # [1] 시장 브리핑 복구 (결측 시에도 KOSPI 지수 강제 출력)
    msg = f"📊 <b>V9.1 실전 퀀트 운용 보고서</b>\n\n"
    msg += f"<b>[1] 🌐 시장 요약 ({market.get('state', 'NORMAL')})</b>\n"
    msg += f"• KOSPI 1D: <b>{market.get('kospi_1d', 0.0)}%</b>\n"
    
    if breadth.get('trend') == 'Unknown':
        msg += f"• 체력 추세: <b>⚠️ 수집 실패 (Unavailable)</b>\n"
    else:
        msg += f"• 체력 추세: <b>{breadth.get('trend', 'Flat')}</b> (AD Ratio: {breadth.get('avg_ratio', 0)}%)\n"
        msg += f"• KOSPI : 상승 {breadth.get('kp_up',0)} / 하락 {breadth.get('kp_down',0)}\n"
        msg += f"• KOSDAQ: 상승 {breadth.get('kd_up',0)} / 하락 {breadth.get('kd_down',0)}\n"
    msg += "━" * 16 + "\n\n"
    
    # [2] Prime Leader 출력 강화 (선정 근거 100% 노출)
    if alert_candidates:
        leader = alert_candidates[0]
        ld = leader["decision"]
        plan = ld["trade_plan"]
        rs20 = leader.get("raw_features").mom.rs_20d if leader.get("raw_features") else 0.0
        
        msg += f"<b>[2] 👑 Prime Leader</b>\n"
        msg += f"<b>{leader['name']}</b> ({leader['code']}) | {leader['chg']}%\n"
        msg += f"▶ 전략: <b>{ld['primary_strategy']}</b> ⭐⭐⭐\n"
        msg += f"• [팩터] Trade: {ld['trade_score']} | RS20: {rs20:.1f}\n"
        msg += f"• [점수] <b>Comp: {ld['composite_rank']}</b> | Conf: {ld['confidence']}\n"
        
        msg += f"\n🎯 <b>[트레이드 플랜]</b>\n"
        msg += f"• 진입: {plan['entry']:,}원\n"
        msg += f"• 목표: {plan['target1']:,}원 (T1)\n"
        msg += f"• 손절: {plan['stop_loss']:,}원 (ATR/Pivot)\n"
        msg += "━" * 16 + "\n\n"
        
        # [3] TOP 5 리스트 동기화 (Composite Rank 기준)
        msg += f"<b>[3] 🚀 실전 운영 TOP 5</b>\n"
        if len(alert_candidates) > 1:
            for idx, c in enumerate(alert_candidates[1:6], 2):
                cd = c["decision"]
                c_rs20 = c.get("raw_features").mom.rs_20d if c.get("raw_features") else 0.0
                msg += f"{idx}위. <b>{c['name']}</b> ({cd['level']})\n"
                msg += f" └ Comp: <b>{cd['composite_rank']}</b> | Conf: {cd['confidence']} | RS20: {c_rs20:.1f}\n"
        else:
            msg += "• 후순위 후보 없음\n"
        msg += "━" * 16 + "\n\n"
    else:
        msg += f"<b>[2] 👑 Prime Leader</b>\n"
        msg += "• 신규 조건 충족 종목 없음 (패스)\n"
        msg += "━" * 16 + "\n\n"
    
    # [4] 포트폴리오 연동
    msg += f"<b>[4] 💼 포트폴리오 및 청산 알림</b>\n"
    if holdings_data:
        for h in holdings_data:
            icon = "🚨" if "청산" in h['judgment'] else "🟢"
            msg += f"{icon} {h['name']} | 수익: {h['pnl']}% | Conf: {h['conf']} | 손절: {h['stop_p']:,}원\n"
    else:
        msg += "• 보유 종목 없음\n"
        
    msg_list.append(msg)
    return msg_list
