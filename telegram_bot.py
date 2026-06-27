import os
import requests
import asyncio

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# [수정] main.py의 await 호출 규격에 맞춘 비동기 처리
async def send_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ 텔레그램 설정 오류")
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    
    try:
        # 비동기 환경에서 requests 블로킹 방지
        response = await asyncio.to_thread(requests.post, url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ 텔레그램 메세지 전송 실패: {e}")
        return False

# [수정] main.py가 호출하는 run_type, result 인자 구조 확립
def format_scan_messages(run_type, result):
    if not result or "candidates" not in result: 
        return ["⚠️ 데이터 추출 실패"]
    
    market = result.get("market", {})
    candidates = result.get("candidates", [])
    risk_level = market.get("risk_level", 1)
    risk_text = "위험도 0/100 (안정)" if risk_level == 1 else ("위험도 50/100 (조정)" if risk_level == 2 else "위험도 100/100 (극단적 약세)")
    
    survival_count = sum(1 for c in candidates if "폭락장 상대강도 리더" in c["decision"]["action"] or "생존 감시 대상" in c["decision"]["action"])
    
    msg_list = []
    header = f"🎯 <b>V8.8.17 DAILY QUANT REPORT ({run_type})</b>\n\n"
    header += f"📊 <b>시장 지표</b>\n"
    header += f"KOSPI: {market.get('kospi', 0.0)}% | 시장 진단: {risk_text}\n"
    header += f"폭락장 생존 후보 포착: {survival_count} / {len(candidates)}\n"
    header += "━" * 20 + "\n\n"
    current_msg = header
    
    for idx, c in enumerate(candidates, 1):
        is_leader = c["decision"].get("is_prime_leader", False)
        icon = "👑 [PRIME WATCH]" if is_leader else f"🔹 {idx}위"
        
        block = f"{icon} <b>{c['name']}</b> ({c['code']})\n"
        block += f"등급: {c['decision']['action']}\n"
        block += f"Final: {c['scores']['prime_final']} | Prime: {c['scores']['prime_score']}\n"
        block += f"RS20D: {'+' if c['features']['rs_20d']>0 else ''}{c['features']['rs_20d']}% | Conv: {c['features']['conviction']}\n\n"
        
        t10 = c['decision'].get('top10_stability', {})
        block += f"📌 <b>지속성 분석</b>\n"
        block += f"TOP10 유지: {t10.get('top10_count', 0)}회 | 최근 {t10.get('days', 0)}일 출현\n"
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
