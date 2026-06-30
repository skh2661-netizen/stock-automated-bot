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
        response = await asyncio.to_thread(requests.post, url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception: return False

def format_scan_messages(run_type, result):
    if not result or "candidates" not in result: return ["⚠️ 데이터 추출 실패"]
    
    market = result.get("market", {})
    candidates = result.get("candidates", [])
    regime = market.get("regime", "NORMAL")
    direction = market.get("direction", "🟢 시장 안정")
    
    msg_list = []
    header = f"🎯 <b>V8.8.19 DAILY QUANT REPORT</b>\n\n"
    header += f"📊 <b>시장 분석 ({regime} 국면)</b>\n"
    header += f"방향: {direction}\n"
    header += f"KOSPI: {market.get('kospi', 0.0)}% | KOSDAQ: {market.get('kosdaq', 0.0)}%\n\n"
    header += f"총 필터 통과 종목: {len(candidates)}개\n"
    header += "━" * 20 + "\n\n"
    current_msg = header
    
    # [교정] 상위 10개만 슬라이싱하여 노이즈 제거
    for idx, c in enumerate(candidates[:10], 1):
        is_leader = c["decision"].get("is_prime_leader", False)
        icon = "👑 [PRIME WATCH]" if is_leader else f"🔹 {idx}위"
        
        block = f"{icon} <b>{c['name']}</b> ({c['code']})\n"
        block += f"판단: {c['decision']['action']}\n"
        block += f"RS20D: {'+' if c['features']['rs_20d']>0 else ''}{c['features']['rs_20d']}% | Conv: {c['features']['conviction']}\n\n"
        
        t10 = c['decision'].get('top10_stability', {})
        block += f"📌 <b>지속성 분석</b>\n"
        block += f"오늘 장중 포착: {t10.get('top10_count', 0)}회\n"
        block += f"최근 출현 일수: {t10.get('recent_days', 0)}일\n"
        block += f"평균 순위: {t10.get('avg_rank', 0.0)}위\n\n"
        
        block += f"🎯 <b>매매 준비도</b>\n"
        block += f"{c['decision'].get('buy_readiness', '👀 LEVEL 0: 관찰')}\n"
        
        block += "━" * 20 + "\n\n"
        
        if len(current_msg) + len(block) > 4000:
            msg_list.append(current_msg)
            current_msg = block
        else:
            current_msg += block
            
    if current_msg: msg_list.append(current_msg)
    return msg_list
