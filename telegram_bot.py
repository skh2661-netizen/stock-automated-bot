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
    except Exception: return False

def format_scan_messages(result, holdings_data=None, p_state=None, p_stats=None):
    market = result.get("market", {})
    breadth = market.get("breadth", {})
    alert_cands = result.get("alert_candidates", [])
    drop_stats = result.get("drop_stats", {"actionable": 0, "level": 0})
    
    if not p_stats: p_stats = {}
    
    msg_list = []
    
    # 1. 🌐 시장
    msg = f"🌐 <b>시장</b>\n"
    msg += f"지수 데이터 정상 : {'YES' if market.get('fdr_ok') else 'NO'}\n"
    msg += f"상승/하락 집계 정상 : {'YES' if breadth.get('is_ok') else 'NO'}\n"
    msg += f"출처 : {market.get('source', '알수없음')}\n"
    msg += f"데이터 품질 : {market.get('data_quality', '0')}%\n\n"
    
    msg += f"KOSPI : {market.get('kospi_1d', 0.0)}%\n"
    msg += f"KOSDAQ : {market.get('kosdaq_1d', 0.0)}%\n\n"
    
    up_cnt = breadth.get('kp_up',0) + breadth.get('kd_up',0)
    down_cnt = breadth.get('kp_down',0) + breadth.get('kd_down',0)
    same_cnt = breadth.get('kp_same',0) + breadth.get('kd_same',0)
    
    msg += f"상승 {up_cnt}\n하락 {down_cnt}\n변동없음 {same_cnt}종목\n"
    msg += f"상승 종목 비율 {breadth.get('up_ratio', 0)}% (상승종목 / 상승+하락)\n\n"

    # 2. 💼 포트폴리오
    used_slots = len(holdings_data) if holdings_data else 0
    p_tier = p_state.tier if p_state else "정상"
    buy_status = "가능" if (p_state.allow_new_buy if p_state else True) else "불가"
    
    msg += f"💼 <b>포트폴리오</b>\n"
    msg += f"계좌상태 {p_tier} | 현금 {max(100 - (used_slots * 15), 5)}% | 보유 {used_slots}종목 | 신규매수 {buy_status}\n"
    
    if holdings_data:
        for idx, h in enumerate(holdings_data, 1):
            msg += f" {idx}. {h.name} ({getattr(h, 'pnl', 0)}%) | Conf {getattr(h, 'conf', 0)} | {getattr(h, 'judgment', '보유')}\n"
    
    # 3. 👑 Prime Leader & Observation
    msg += f"\n👑 <b>Prime Leader</b>\n"
    if not alert_cands:
        msg += " 후보 없음\n"
        msg += f" └ 사유: Actionable {drop_stats.get('actionable', 0)}개 제거, LEVEL 부족 {drop_stats.get('level', 0)}개 제거\n"
        obs_start = 0
    else:
        prime = alert_cands[0]
        msg += f" <b>{prime['name']}</b> | {prime['price']:,}원 ({prime['chg']}%)\n"
        msg += f" 매력도 {prime['decision']['composite_rank']} | RS {prime['decision']['rs_20d']}\n"
        obs_start = 1
        
    msg += f"\n📈 <b>Observation</b>\n"
    if len(alert_cands) > obs_start:
        for idx, c in enumerate(alert_cands[obs_start:5], 1):
            msg += f" {idx}. {c['name']} ({c['chg']}%) | 매력도 {c['decision']['composite_rank']}\n"
    else:
        msg += " 관찰 종목 없음\n"
        
    # 4. 📊 Runtime (파이프라인 생존 통계)
    msg += f"\n📊 <b>Runtime</b>\n"
    msg += f" KRX {p_stats.get('krx', 0)}\n"
    msg += f" Filter {p_stats.get('filter', 0)}\n"
    msg += f" Pool {p_stats.get('pool', 0)}\n"
    msg += f" History 성공 {p_stats.get('hist_ok', 0)}\n"
    msg += f" History 실패 {p_stats.get('hist_fail', 0)}\n"
    msg += f" Feature 성공 {p_stats.get('feat_ok', 0)}\n"
    msg += f" Feature 실패 {p_stats.get('feat_fail', 0)}\n"
    msg += f" Decision {p_stats.get('decision', 0)}\n"
    msg += f" Alert {p_stats.get('alert', 0)}\n"
        
    msg_list.append(msg)
    return msg_list
