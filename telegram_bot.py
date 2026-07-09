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
    
    msg = f"📊 <b>V9.1 실전 퀀트 운용 보고서</b>\n\n"
    msg += f"<b>[1] 🌐 시장 요약 ({market.get('state', 'NORMAL')})</b>\n"
    msg += f"• KOSPI 1D: <b>{market.get('kospi_1d', 0.0)}%</b>\n"
    
    # 교정 1: Breadth 수집 실패(Unknown) 시에도 직관적인 에러 표출 후 브리핑 유지
    if breadth.get('trend') == 'Unknown':
        msg += f"• 시장 폭(Breadth): <b>⚠️ 데이터 수집 실패 (Unavailable)</b>\n"
    else:
        msg += f"• 시장 폭(Breadth): <b>{breadth.get('trend', 'Flat')}</b> (AD Ratio: {breadth.get('avg_ratio', 0)}%)\n"
        msg += f"• KOSPI 종목: 상승 {breadth.get('kp_up',0)} / 하락 {breadth.get('kp_down',0)}\n"
        msg += f"• KOSDAQ 종목: 상승 {breadth.get('kd_up',0)} / 하락 {breadth.get('kd_down',0)}\n"
    msg += "━" * 16 + "\n\n"
    
    if alert_candidates:
        leader = alert_candidates[0]
        ld = leader["decision"]
        plan = ld["trade_plan"]
        rf = leader["raw_features"]
        rs_val = round(rf.mom.rs_20d, 2)
        
        # 교정 2: Prime Leader 퀀트 핵심 지표 전면 개방
        msg += f"<b>[2] 👑 Prime Leader</b>\n"
        msg += f"<b>{leader['name']}</b> ({leader['code']}) | {leader['chg']}%\n"
        msg += f"▶ <b>{ld['level']}</b> | 전략: <b>{ld['primary_strategy']}</b> ⭐⭐⭐\n\n"
        
        msg += f"📊 <b>[핵심 퀀트 스코어]</b>\n"
        msg += f"• Composite Rank: <b>{ld['composite_rank']}점</b>\n"
        msg += f"• Confidence: {ld['confidence']}점\n"
        msg += f"• Trade Score: {ld['trade_score']}점\n"
        msg += f"• RS20 상대강도: {rs_val}\n\n"
        
        msg += f"🎯 <b>[트레이드 플랜]</b>\n"
        msg += f"• 진입: {plan['entry']:,}원\n"
        msg += f"• 목표: {plan['target1']:,}원 (T1)\n"
        msg += f"• 손절: {plan['stop_loss']:,}원\n"
        msg += "━" * 16 + "\n\n"
        
        # 교정 3: TOP5 리스트에 계층(LEVEL)과 랭킹(Comp/Conf/RS) 출력 지표 통일
        msg += f"<b>[3] 🚀 실전 운영 TOP 5</b>\n"
        if len(alert_candidates) > 1:
            for idx, c in enumerate(alert_candidates[1:6], 2):
                cd = c["decision"]
                crf = c["raw_features"]
                crs_val = round(crf.mom.rs_20d, 2)
                msg += f"{idx}위. <b>{c['name']}</b> ({cd['level']}) | {cd['primary_strategy']}\n"
                msg += f" └ Comp <b>{cd['composite_rank']}</b> | Conf {cd['confidence']} | RS20 {crs_val}\n"
        else:
            msg += "• 후순위 후보 없음\n"
        msg += "━" * 16 + "\n\n"
    else:
        msg += f"<b>[2] 👑 Prime Leader</b>\n"
        msg += "• 신규 조건 충족 종목 없음 (패스)\n"
        msg += "━" * 16 + "\n\n"
    
    # 교정 4: 포트폴리오 UI 가독성 강화 및 부재 시 명확한 사유 표시
    msg += f"<b>[4] 💼 포트폴리오 관제</b>\n"
    if holdings_data:
        for h in holdings_data:
            icon = "🚨" if "청산" in h['judgment'] else "🟢"
            msg += f"{icon} {h['name']} | 수익: {h['pnl']}% | Conf: {h['conf']}점\n"
            msg += f" └ 판정: {h['judgment']} | 손절가: {h['stop_p']:,}원\n"
    else:
        msg += "• 보유 종목 없음 (holdings.json Empty)\n"
        
    msg_list.append(msg)
    return msg_list
