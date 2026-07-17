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
    diag = market.get("diag", {})
    dec_stats = result.get("dec_stats", {})
    alert_cands = result.get("alert_candidates", [])
    buy_blocked = result.get("buy_blocked", False)
    
    # KeyError 완벽 차단을 위한 get 메서드 활용
    if not p_stats: p_stats = {}
    stat_pool = p_stats.get('pool', 0)
    stat_hist = p_stats.get('history_ok', 0)
    stat_dec = p_stats.get('decision', 0)
    
    msg_list = []
    
    # 1. 🌐 시장
    msg = f"🌐 <b>시장 데이터 진단</b>\n"
    msg += f"Index: {diag.get('FDR Index', 'FAIL')} | Breadth: {diag.get('FDR', 'FAIL')}\n"
    msg += f"API: {diag.get('API', 'FAIL')} | DOM: {diag.get('DOM', 'FAIL')} | YAHOO: {diag.get('YAHOO', 'FAIL')}\n"
    msg += f"데이터 품질: {market.get('data_quality', '0%')} (출처: {market.get('source', 'NONE')})\n\n"
    
    msg += f"KOSPI  | 상승 {breadth.get('kp_up',0)} / 하락 {breadth.get('kp_down',0)} / 보합 {breadth.get('kp_same',0)}\n"
    msg += f"KOSDAQ | 상승 {breadth.get('kd_up',0)} / 하락 {breadth.get('kd_down',0)} / 보합 {breadth.get('kd_same',0)}\n"
    msg += f"시장 상승비율: {breadth.get('up_ratio', 0)}% ({market.get('state', 'UNKNOWN')})\n\n"

    # 2. 💼 포트폴리오
    used_slots = len(holdings_data) if holdings_data else 0
    p_tier = p_state.tier if p_state else "정상"
    buy_status = "가능" if (p_state.allow_new_buy if p_state else True) else "불가"
    
    msg += f"💼 <b>포트폴리오</b>\n"
    msg += f"계좌상태: {p_tier} | 현금: {max(100 - (used_slots * 15), 5)}% | 보유: {used_slots}종목 | 신규매수: {buy_status}\n"
    
    if holdings_data:
        for idx, h in enumerate(holdings_data, 1):
            msg += f" {idx}. {h.name} ({getattr(h, 'pnl', 0)}%) | Conf {getattr(h, 'conf', 0)} | {getattr(h, 'judgment', '보유')}\n"
    else:
        msg += " 등록된 보유종목 없음\n"
    
    # 3. 👑 Prime Leader & Observation
    msg += f"\n👑 <b>Prime Leader</b>\n"
    if not alert_cands:
        msg += " 후보 없음\n"
        msg += " └ 원인: "
        if stat_pool == 0: msg += "스캐너 통과 종목 0개\n"
        elif stat_hist == 0: msg += "차트 로드 전멸\n"
        elif stat_dec == 0: msg += "엔진 필터 전멸\n"
        else: msg += "LEVEL 3/4 도달 실패 (전부 LEVEL 1/2)\n"
        obs_start = 0
    elif buy_blocked:
        msg += f" ⚠️ 매수 차단 ({result.get('block_reason')})\n"
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
        
    # 4. 📊 Runtime & Pipeline Health
    msg += f"\n📊 <b>Pipeline Diagnostics</b>\n"
    msg += f" KRX 전체: {p_stats.get('krx', 0)}\n"
    msg += f" Base Filter 통과: {p_stats.get('filter', 0)}\n"
    msg += f" Multi-Pool 통과: {stat_pool}\n"
    msg += f" History & Feature: {p_stats.get('feature_ok', 0)}\n"
    msg += f" 엔진 최종 판정: {stat_dec} (LEVEL4: {dec_stats.get('levels',{}).get('LEVEL 4',0)}, L3: {dec_stats.get('levels',{}).get('LEVEL 3',0)})\n"
    
    msg += f"\n⏱ <b>소요 시간</b> (총 {round(sum(v for k,v in p_stats.items() if k.startswith('time_')), 1)}s)\n"
    msg += f" Market {p_stats.get('time_market', 0)}s | Port {p_stats.get('time_port', 0)}s | Scan {p_stats.get('time_scan', 0)}s\n"
    msg += f" Hist {p_stats.get('time_hist', 0)}s | Feat {p_stats.get('time_feat', 0)}s | Dec {p_stats.get('time_dec', 0)}s\n"
        
    msg_list.append(msg)
    return msg_list
