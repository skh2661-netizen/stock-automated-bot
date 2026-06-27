import os
import requests

# GitHub Secrets 또는 환경 변수에서 토큰과 챗 아이디 호출
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_message(text):
    """텔레그램 채널/방으로 메세지를 전송하는 핵심 통신 함수입니다."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ 텔레그램 토큰(TELEGRAM_TOKEN) 또는 방 번호(TELEGRAM_CHAT_ID)가 설정되지 않았습니다.")
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ 텔레그램 메세지 전송 실패: {e}")
        return False

def format_scan_messages(run_type, result):
    """의사결정 엔진이 산출한 데이터를 텔레그램 보고서 양식으로 렌더링합니다."""
    if not result or "candidates" not in result: 
        return ["⚠️ 데이터 추출 실패"]
    
    market = result.get("market", {})
    candidates = result.get("candidates", [])
    
    risk_level = market.get("risk_level", 1)
    risk_text = "위험도 0/100 (안정)" if risk_level == 1 else ("위험도 50/100 (조정)" if risk_level == 2 else "위험도 100/100 (극단적 약세)")
    
    # 텍스트 매칭으로 생존 후보 판독
    survival_count = sum(1 for c in candidates if "폭락장 상대강도 리더" in c["decision"]["action"] or "생존 감시 대상" in c["decision"]["action"])
    
    msg_list = []
    header = f"🎯 <b>V8.8.17 DAILY QUANT REPORT ({run_type})</b>\n\n"
    header += f"📊 <b>시장 지표</b>\n"
    header += f"KOSPI: {market.get('kospi', 0.0)}% | KOSDAQ: {market.get('kosdaq', 0.0)}%\n"
    header += f"시장 진단: {risk_text}\n"
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
        
        # 지속성 분석 출력
        t10 = c['decision'].get('top10_stability', {})
        block += f"📌 <b>지속성 분석</b>\n"
        block += f"오늘 TOP10 유지: {t10.get('top10_count', 0)}시간\n"
        block += f"평균 순위: {t10.get('avg_rank', 0.0)}위\n\n"
        
        # 4단계 매매 준비도 엔진 판단 결과 투하
        block += f"🎯 <b>매매 준비도</b>\n"
        block += f"{c['decision'].get('buy_readiness', '👀 LEVEL 0: 관찰')}\n"
        block += "━" * 20 + "\n\n"
        
        # 텔레그램 글자 수 제한(4096자) 방어 로직
        if len(current_msg) + len(block) > 4000:
            msg_list.append(current_msg)
            current_msg = block
        else:
            current_msg += block
            
    if current_msg:
        msg_list.append(current_msg)
        
    return msg_list
