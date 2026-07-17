import os
import requests
import asyncio
import logging

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

async def send_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        await asyncio.to_thread(requests.post, url, json=payload, timeout=10)
        return True
    except Exception as e:
        logging.error(f"Telegram Send Failed: {e}")
        return False

def format_scan_messages(result, holdings_data=None, p_state=None, runtime_stats=None):
    market = result.get("market", {})
    breadth = market.get("breadth", {})
    alert_candidates = result.get("alert_candidates", [])
    buy_blocked = result.get("buy_blocked", False)
    
    if not runtime_stats: runtime_stats = {"pool": 0, "final": 0, "time": 0.0}
    
    msg_list = []
    
    # 1. 🌐 시장 (단순화 및 데이터 출처 명시)
    msg = f"🌐 <b>시장</b>\n"
    msg += f"신뢰도 {market.get('conf_stars', '★☆☆☆☆')}\n"
    msg += f"출처 {breadth.get('source', 'NONE')}\n"
    msg += f"상승 {breadth.get('kp_up',0)+breadth.get('kd_up',0)} / 하락 {breadth.get('kp_down',0)+breadth.get('kd_down',0)} / 보합 {breadth.get('kp_same',0)+breadth.get('kd_same',0)}\n"
    msg += f"Breadth {breadth.get('avg_ratio', 0)}% ({breadth.get('trend', 'Unknown')})\n\n"

    # 2. 💼 포트폴리오
    used_slots = len(holdings_data) if holdings_data else 0
    cash_ratio = max(100 - (used_slots * 15), 5)
    p_score = p_state.phs_score if p_state else 100.0
    p_tier = p_state.tier if p_state else "SURVIVAL"
    
    msg += f"💼 <b>포트폴리오</b>\n"
    msg += f"PHS {p_score} | Tier {p_tier} | Slots {used_slots}/5 | Cash {cash_ratio}%\n\n"
    
    if holdings_data:
        for idx, h in enumerate(holdings_data, 1):
            h_judgment = getattr(h, 'judgment', '보유')
            h_pnl = getattr(h, 'pnl', 0)
            h_conf = getattr(h, 'conf', 0)
            msg += f" {idx}⃝ {h.name} ({h_pnl}%) | Conf: {h_conf} | {h_judgment}\n"
    else:
        msg += " 보유종목 없음\n"
    
    # 3. 👑 Prime Leader & 📈 Observation
    msg += f"\n👑 <b>Prime Leader</b>\n"
    if buy_blocked or not alert_candidates:
        msg += " 없음 (매수 차단 또는 조건 미달)\n"
        obs_start = 0
    else:
        leader = alert_candidates[0]
        msg += f" {leader['name']} | {leader['price']:,}원 ({leader['chg']}%)\n"
        msg += f" 매력도 {leader['decision']['composite_rank']} | RS {leader['decision']['rs_20d']}\n"
        obs_start = 1
        
    msg += f"\n📈 <b>Observation</b>\n"
    if len(alert_candidates) > obs_start:
        for idx, c in enumerate(alert_candidates[obs_start:4], 1):
            msg += f" {idx}. {c['name']} ({c['chg']}%) | 매력도 {c['decision']['composite_rank']}\n"
    else:
        msg += " 관찰 후보 없음\n"
        
    # 4. 📊 Runtime Stats
    msg += f"\n📊 <b>Runtime</b>\n"
    msg += f" Scanner Pool {runtime_stats['pool']}\n"
    msg += f" 최종후보 {runtime_stats['final']}\n"
    msg += f" Runtime {runtime_stats['time']} sec\n"
        
    msg_list.append(msg)
    return msg_list
