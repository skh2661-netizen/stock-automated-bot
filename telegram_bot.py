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

def format_scan_messages(result, holdings_data=None, p_state=None, p_stats=None):
    market = result.get("market", {})
    breadth = market.get("breadth", {})
    alert_cands = result.get("alert_candidates", [])
    buy_blocked = result.get("buy_blocked", False)
    block_reason = result.get("block_reason", "")
    
    if not p_stats: p_stats = {"krx": 0, "filter": 0, "pool": 0, "history": 0, "feature": 0, "decision": 0, "alert": 0, "time": 0.0}
    
    msg_list = []
    
    # 🌐 1. 시장
    msg = f"🌐 <b>시장</b>\n"
    msg += f"데이터 품질 {market.get('data_quality', '0%')}\n"
    msg += f"출처 {breadth.get('source', 'NONE')}\n"
    msg += f"상승 {breadth.get('kp_up',0)+breadth.get('kd_up',0)} / 하락 {breadth.get('kp_down',0)+breadth.get('kd_down',0)} / 보합 {breadth.get('kp_same',0)+breadth.get('kd_same',0)}\n"
    msg += f"시장 상승비율 {breadth.get('up_ratio', 0)}% ({breadth.get('trend', 'Unknown')})\n\n"

    # 💼 2. 포트폴리오
    used_slots = len(holdings_data) if holdings_data else 0
    cash_ratio = max(100 - (used_slots * 15), 5)
    p_tier = p_state.tier if p_state else "정상"
    buy_status = "불가" if (not p_state.allow_new_buy if p_state else False) else "가능"
    
    msg += f"💼 <b>포트폴리오</b>\n"
    msg += f"계좌상태 {p_tier} | 현금 {cash_ratio}% | 보유 {used_slots}종목 | 신규매수 {buy_status}\n"
    
    if holdings_data:
        for idx, h in enumerate(holdings_data, 1):
            h_judg = getattr(h, 'judgment', '보유')
            msg += f" {idx}. {h.name} ({getattr(h, 'pnl', 0)}%) | Conf {getattr(h, 'conf', 0)} | {h_judg}\n"
    else:
        msg += " 등록된 종목 없음\n"
    
    msg += "\n👑 <b>Prime Leader</b>\n"
    if buy_blocked:
        msg += f" ⚠️ 매수 차단 ({block_reason})\n"
        prime = None
    elif alert_cands:
        prime = alert_cands[0]
        msg += f" <b>{prime['name']}</b> | {prime['price']:,}원 ({prime['chg']}%)\n"
        msg += f" 매력도 {prime['decision']['composite_rank']} | RS {prime['decision']['rs_20d']}\n"
    else:
        msg += " 후보 없음\n"
        prime = None
        
    msg += "\n📈 <b>Observation</b>\n"
    obs_list = alert_cands if buy_blocked else (alert_cands[1:] if prime else alert_cands)
    if obs_list:
        for idx, c in enumerate(obs_list[:4], 1):
            msg += f" {idx}. {c['name']} ({c['chg']}%) | 매력도 {c['decision']['composite_rank']}\n"
    else:
        msg += " 관찰 종목 없음\n"
        
    # 📊 4. Runtime
    msg += f"\n📊 <b>Runtime</b>\n"
    msg += f" KRX {p_stats['krx']} -> Filter {p_stats['filter']} -> Pool {p_stats['pool']} ->\n"
    msg += f" Decision {p_stats['decision']} -> Alert {p_stats['alert']}\n"
    msg += f" Runtime {p_stats['time']} sec\n"
        
    msg_list.append(msg)
    return msg_list
