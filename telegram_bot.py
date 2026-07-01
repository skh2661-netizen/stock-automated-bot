import os
import requests
import asyncio

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

async def send_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: 
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        response = await asyncio.to_thread(requests.post, url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception: 
        return False

def format_scan_messages(run_type, result):
    if not result or "candidates" not in result: return ["⚠️ 데이터 추출 실패"]
    
    market = result.get("market", {})
    candidates = result.get("candidates", [])
    regime = market.get("regime", "NORMAL")
    direction = market.get("direction", "🟢 시장 안정")
    max_obj = market.get("max_level_obj", {})
    
    msg_list = []
    header = f"🎯 <b>V8.8.32 DAILY QUANT REPORT</b>\n\n"
    
    header += f"📌 <b>오늘 투자 결론</b>\n\n"
    header += f"시장: <b>{regime}</b>\n{direction}\n\n"
    header += f"시장 투자 환경: <b>{market.get('buy_tolerance', '0점 / 100점')}</b>\n"
    header += f"의미: {'방향성이 약해 공격적인 매수보다 선별적 접근 필요' if '40점' in market.get('buy_tolerance', '') or '60점' in market.get('buy_tolerance', '') else ('하방 리스크가 커 신규 매수 금지' if '10점' in market.get('buy_tolerance', '') or '20점' in market.get('buy_tolerance', '') else '추세가 살아있어 조건 부합 시 매수 유리')}\n\n"
    
    header += f"오늘 핵심 매매 후보:\n👑 <b>{market.get('max_level_code', '없음')}</b>\n"
    header += f"선정 이유: {market.get('max_lvl_reason', '-')}\n\n"
    header += f"매매 단계: {max_obj.get('level', 'LEVEL 0')} {max_obj.get('title', '').split(' ')[0]}\n"
    header += f"추천: {max_obj.get('action', '-')}\n"
    header += "━" * 20 + "\n\n"
    current_msg = header
    
    for idx, c in enumerate(candidates[:10], 1):
        is_trade_leader = c["decision"].get("is_trade_leader", False)
        
        if is_trade_leader: block = f"👑 <b>오늘의 매매 관심 1순위</b>\n"
        else: block = f"📊 <b>매매 후보군 {idx}위</b>\n"
            
        block += f"<b>{c['name']}</b> ({c['code']})\n\n"
        
        rs_val = c['features']['rs_20d']
        conv_val = c['features']['conviction']
        rs_str = "시장 대비 압도적인 상승 모멘텀" if rs_val >= 30 else ("최근 20일 시장보다 강한 상승 흐름" if rs_val > 0 else "시장 대비 상대적 약세 흐름 (주의)")
        conv_str = "강력한 거래량 및 매수 주체 확인" if conv_val >= 65 else ("기본적인 수급 유입 확인됨" if conv_val >= 50 else "뚜렷한 수급 주체 및 폭발력 부족")
        
        block += f"상대강도(RS20D): {'+' if rs_val>0 else ''}{rs_val}%\n"
        block += f"{rs_str}\n\n"
        
        block += f"수급확신도: {conv_val}점\n"
        block += f"{conv_str}\n\n"
        
        t10 = c['decision'].get('top10_stability', {})
        top10_count = t10.get('top10_count', 0)
        avg_rank = t10.get('avg_rank', 0.0)
        
        block += f"📌 <b>TOP10 상태</b>\n"
        if top10_count >= 5: block += f"강한 유지력 ({top10_count}회 출현 / 평균 {round(avg_rank, 1)}위)\n"
        elif top10_count >= 2: block += f"관심 유지 ({top10_count}회 출현 / 평균 {round(avg_rank, 1)}위)\n"
        elif avg_rank <= 3.0 and top10_count == 1: block += f"신규 포착\n상위권 진입 유지력 확인 ({top10_count}회 출현 / 평균 {round(avg_rank, 1)}위)\n"
        else: block += f"신규 진입 후보 ({top10_count}회 출현 / 평균 {round(avg_rank, 1)}위)\n"
        block += "\n"
        
        ready = c['decision'].get('buy_readiness', {})
        
        block += f"🎯 <b>매매 판단</b>\n\n"
        block += f"<b>{ready.get('level', 'LEVEL 0')} / 4단계</b>\n"
        block += f"{ready.get('title', '상태 불명')}\n\n"
        block += f"추천: {ready.get('action', '-')}\n\n"
        
        if ready.get("conditions"):
            block += "다음 단계 조건:\n"
            block += "\n".join(ready["conditions"]) + "\n\n"
            
        if ready.get("level") in ["LEVEL 3", "LEVEL 4"]:
            plan = c['decision'].get('trade_plan', {})
            if plan:
                block += f"💰 <b>예상 매매 계획</b>\n"
                block += f"진입: {plan.get('entry', '-')}\n"
                block += f"손절: {plan.get('stop_loss', '-')}\n"
                block += f"1차 목표: {plan.get('target1', '-')}\n"
                block += f"2차 목표: {plan.get('target2', '-')}\n\n"
        elif ready.get("level") == "LEVEL 2":
            block += f"📌 <b>관찰 계획</b>\n"
            block += f"조건 충족 시 매매 계획 공개\n\n"
            
        block += "━" * 20 + "\n\n"
        
        if len(current_msg) + len(block) > 4000:
            msg_list.append(current_msg)
            current_msg = block
        else: current_msg += block
            
    if current_msg: msg_list.append(current_msg)
    return msg_list
