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
    header = f"🎯 <b>V8.8.22 DAILY QUANT REPORT</b>\n\n"
    
    header += f"📌 <b>투자 판단 요약</b>\n"
    header += f"시장 상태: {regime} ({direction})\n"
    header += f"매수 허용도: <b>{market.get('buy_tolerance', '0%')}</b>\n"
    header += f"최대 관심 후보: <b>{market.get('max_level_code', '없음')}</b>\n"
    header += f"현재 최고 단계: <b>{market.get('max_level', 'LEVEL 0')}</b>\n"
    header += f"추천 행동: {market.get('recommended_action', '관망')}\n"
    header += "━" * 20 + "\n\n"
    current_msg = header
    
    for idx, c in enumerate(candidates[:10], 1):
        is_leader = c["decision"].get("is_prime_leader", False)
        
        icon = f"👑 <b>[PRIME WATCH] ({idx}위)</b>" if is_leader else f"🔹 {idx}위"
        
        block = f"{icon}\n<b>{c['name']}</b> ({c['code']})\n"
        block += f"판단: {c['decision']['action']}\n"
        block += f"RS20D: {'+' if c['features']['rs_20d']>0 else ''}{c['features']['rs_20d']}% | Conv: {c['features']['conviction']}\n\n"
        
        t10 = c['decision'].get('top10_stability', {})
        block += f"📌 <b>지속성 분석</b>\n"
        block += f"오늘 장중 포착: {t10.get('top10_count', 0)}회\n"
        block += f"최근 출현 일수: {t10.get('recent_days', 0)}일\n"
        block += f"평균 순위: {t10.get('avg_rank', 0.0)}위\n\n"
        
        block += f"🎯 <b>매매 준비도</b>\n"
        block += f"상태: {c['decision'].get('buy_readiness', '👀 LEVEL 0: 관찰')}\n"
        
        next_conds = c['decision'].get('next_conditions', [])
        if next_conds:
            block += "다음 단계 조건:\n" + "\n".join(next_conds) + "\n"
            
        block += "\n" + "━" * 20 + "\n\n"
        
        if len(current_msg) + len(block) > 4000:
            msg_list.append(current_msg)
            current_msg = block
        else:
            current_msg += block
            
    if current_msg: msg_list.append(current_msg)
    return msg_list
