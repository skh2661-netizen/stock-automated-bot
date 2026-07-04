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
    candidates = result.get("candidates", []) # 디버그 모드: 전체 후보 수신
    alert_candidates = result.get("alert_candidates", [])
    alert_codes = [c['code'] for c in alert_candidates]
    
    regime = market.get("regime", "NORMAL")
    direction = market.get("direction", "🟢 시장 안정")
    max_obj = market.get("max_level_obj", {})
    
    if not candidates: return []
        
    msg_list = []
    header = f"🛠️ <b>[DEBUG MODE] V8.8.34 TRANSPARENT AUDIT</b>\n\n"
    header += f"📌 <b>파이프라인 통과 현황</b>\n"
    header += f"전체 DB 기록: {len(candidates)}개\n"
    header += f"알림 조건 통과: {len(alert_candidates)}개\n\n"
    
    header += f"📌 <b>오늘 투자 결론</b>\n\n"
    header += f"시장: <b>{regime}</b>\n{direction}\n\n"
    header += f"오늘 핵심 매매 후보:\n👑 <b>{market.get('max_level_code', '없음')}</b>\n"
    header += f"매매 단계: {max_obj.get('level', 'LEVEL 0')} {max_obj.get('title', '').split(' ')[0]}\n"
    header += "━" * 20 + "\n\n"
    current_msg = header
    
    for idx, c in enumerate(candidates[:10], 1):
        is_alert = c['code'] in alert_codes
        badge = "🔔 [필터 통과]" if is_alert else "🔇 [필터 차단]"
        
        block = f"📊 <b>순위 {idx}위</b> {badge}\n"
        block += f"<b>{c['name']}</b> ({c['code']})\n\n"
        
        rs_val = c['features']['rs_20d']
        conv_val = c['features']['conviction']
        
        block += f"상대강도(RS20D): {'+' if rs_val>0 else ''}{rs_val}%\n"
        block += f"수급확신도: {conv_val}점\n\n"
        
        t10 = c['decision'].get('top10_stability', {})
        block += f"📌 <b>TOP10 상태</b>\n"
        block += f"{t10.get('top10_count', 0)}회 출현 / 평균 {round(t10.get('avg_rank', 0.0), 1)}위\n\n"
        
        ready = c['decision'].get('buy_readiness', {})
        block += f"🎯 <b>매매 판단: {ready.get('level', 'LEVEL 0')}</b>\n"
        
        if ready.get("conditions"):
            block += "다음 단계 조건:\n"
            block += "\n".join(ready["conditions"]) + "\n\n"
            
        block += "━" * 20 + "\n\n"
        
        if len(current_msg) + len(block) > 4000:
            msg_list.append(current_msg)
            current_msg = block
        else: current_msg += block
            
    if current_msg: msg_list.append(current_msg)
    return msg_list
