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
    header = f"🎯 <b>V8.8.27 DAILY QUANT REPORT</b>\n\n"
    
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
        
        # [패치] 우량 후보 직관적 타이틀 분리 및 주의 문구 추가
        if is_leader:
            block = f"🏆 <b>품질 1위 후보</b>\n"
            block += f"<b>{c['name']}</b> ({c['code']})\n\n"
            block += f"의미:\n현재 1차 필터 및 품질 평가 점수 최고치 달성\n\n주의:\n품질과 별개로 실제 매수 타이밍은 하단 '매매 판단'을 따를 것\n\n"
        else:
            block = f"🔹 <b>품질 {idx}위 후보</b>\n"
            block += f"<b>{c['name']}</b> ({c['code']})\n\n"
        
        # [패치] 영문 지표 한글화 및 자동 해석 추가
        rs_val = c['features']['rs_20d']
        conv_val = c['features']['conviction']
        
        rs_str = "시장 대비 압도적인 상승 모멘텀" if rs_val >= 30 else ("최근 20일 시장보다 강한 상승 흐름" if rs_val > 0 else "시장 대비 상대적 약세 흐름 (주의)")
        conv_str = "강력한 거래량 및 주도 수급 유입 확인" if conv_val >= 65 else ("기본적인 수급 유입 확인됨" if conv_val >= 50 else "뚜렷한 수급 주체 및 폭발력 부족")
        
        block += f"📈 <b>상승 분석</b>\n"
        block += f"상대강도: {'+' if rs_val>0 else ''}{rs_val}%\n"
        block += f"해석: {rs_str}\n\n"
        
        block += f"수급확신도: {conv_val}점\n"
        block += f"해석: {conv_str}\n\n"
        
        t10 = c['decision'].get('top10_stability', {})
        block += f"📌 <b>지속성 분석</b>\n"
        block += f"오늘 장중 포착: {t10.get('top10_count', 0)}회\n"
        block += f"TOP10 누적: {t10.get('recent_days', 0)}/5일\n"
        block += f"평균 순위: {t10.get('avg_rank', 0.0)}위\n\n"
        
        # [패치] Dict 기반 렌더링 (매매 판단부 구조화)
        ready = c['decision'].get('buy_readiness', {})
        
        block += f"🎯 <b>매매 판단</b>\n\n"
        block += f"{ready.get('level', 'LEVEL 0')} : {ready.get('title', '상태 불명')}\n\n"
        block += f"의미:\n{ready.get('meaning', '-')}\n\n"
        block += f"추천 행동:\n{ready.get('action', '-')}\n\n"
        
        if ready.get("conditions"):
            block += "다음 조건:\n"
            block += "\n".join(ready["conditions"]) + "\n"
            
        block += "\n" + "━" * 20 + "\n\n"
        
        if len(current_msg) + len(block) > 4000:
            msg_list.append(current_msg)
            current_msg = block
        else:
            current_msg += block
            
    if current_msg: msg_list.append(current_msg)
    return msg_list
