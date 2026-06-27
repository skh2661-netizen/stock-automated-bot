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
    
    survival_count = sum(1 for c in candidates if "리더" in c["decision"]["action"] or "감시" in c["decision"]["action"])
    
    msg_list = []
    header = f"🎯 <b>V8.8.18 DAILY QUANT REPORT ({run_type})</b>\n\n"
    header += f"📊 <b>시장 지표 ({regime} 국면)</b>\n"
    header += f"KOSPI: {market.get('kospi', 0.0)}% | KOSDAQ: {market.get('kosdaq', 0.0)}%\n"
    header += f"전체 스캔 후보: {len(candidates)}개\n"
    header += f"주도(방어) 리더 포착: {survival_count}개\n"
    header += "━" * 20 + "\n\n"
    current_msg = header
    
    # [교정] 상위 10개로 출력 개수 하드 리미트
    for idx, c in enumerate(candidates[:10], 1):
        is_leader = c["decision"].get("is_prime_leader", False)
        icon = "👑 [PRIME WATCH]" if is_leader else f"🔹 {idx}위"
        
        block = f"{icon} <b>{c['name']}</b> ({c['code']})\n"
        block += f"등급: {c['decision']['action']}\n"
        block += f"Final: {c['scores']['prime_final']} | Prime: {c['scores']['prime_score']}\n"
        block += f"RS20D: {'+' if c['features']['rs_20d']>0 else ''}{c['features']['rs_20d']}% | Conv: {c['features']['conviction']}\n\n"
        
        # [교정] 연결이 복구된 지속성 분석 출력
        t10 = c['decision'].get('top10_stability', {})
        block += f"📌 <b>지속성 분석</b>\n"
        block += f"오늘 누적 포착: {t10.get('top10_count', 0)}회\n"
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
            
    if current_msg:
        msg_list.append(current_msg)
    return msg_list
