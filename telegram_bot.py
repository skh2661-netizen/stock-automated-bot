import telegram, asyncio
import os
import datetime
import pytz

async def send_message(text):
    """텔레그램 메시지 안전 전송"""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("🚨 에러: GitHub Secrets에 토큰이 누락되었습니다.")
        return

    bot = telegram.Bot(token=token)
    for _ in range(3):
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=None)
            break
        except Exception as e: 
            print(f"텔레그램 전송 실패, 재시도 중... ({e})")
            await asyncio.sleep(3)

def format_scan_message(data):
    """[V8.5] 무인 요새 정밀 타격 리포트 서식"""
    kst = pytz.timezone('Asia/Seoul')
    time_str = datetime.datetime.now(kst).strftime("%Y-%m-%d %H:%M")
    
    market = data["market"]
    candidates = data["candidates"]
    
    # 1. 시장 상태 출력 레이어
    mode_icon = "🟢" if "정상" in market["mode"] else "🚨"
    msg = f"🎯 [V8.4 무인 요새 정밀 타격]\n\n"
    msg += f"기준: {time_str}\n\n"
    msg += f"🌎 시장 상태\n"
    msg += f" {mode_icon} 모드: {market['mode']}\n"
    msg += f" • 코스피: {market['kospi']}% \n"
    msg += f" • 코스닥: {market['kosdaq']}% \n"
    msg += f" • 위험도: {market['risk_pct']}%\n"
    msg += "=========================\n\n"
    
    if not candidates:
        return msg + "⚙️ 필터 통과 종목 없음 (시드 보호 모드 가동)"
        
    for i, r in enumerate(candidates, 1):
        # [우선순위 3] 익절 및 타점의 2단계 다변화 연산
        buy_p = int(r['price'] * 0.985)     # -1.5% 눌림 진입
        target_1 = int(r['price'] * 1.023)  # +2.3% 1차 방어 익절
        target_2 = int(r['price'] * 1.063)  # +6.3% 2차 폭발 익절
        stop_p = int(r['price'] * 0.970)    # -3.0% 시스템 손절선
        
        stars = "★" * 5 if r['score'] >= 90 else ("★" * 4 + "☆" if r['score'] >= 80 else "★" * 3 + "☆☆")

        # 2. 종목 정보 및 선정 이유 레이어
        msg += f"🥇 {r['name']} ({r['code']})\n"
        msg += f" 매력도: {stars}\n"
        msg += f" 점수: {r['score']} / 100\n"
        msg += f" 현재가: {r['price']:,}원 (📊 변동률: {r['chg']}%)\n\n"
        
        msg += f"📊 선정 이유\n"
        msg += f" ✅ 거래대금: {r['amount']:,}억 원\n"
        msg += f" ✅ 거래량: 평균 대비 {r['vol_ratio']}배\n"
        msg += f" ✅ MA20 이격: +{r['ma_gap']}%\n"
        msg += f" ✅ 수급 등급: {r['grade']}형 주도세력 유입\n\n"
        
        # 3. 매매 계획 및 전략 레이어
        msg += f"🎯 매매 계획\n"
        msg += f" • 진입타점: {buy_p:,}원 부근\n"
        msg += f" • 1차 익절: {target_1:,}원 (+2.3%)\n"
        msg += f" • 2차 익절: {target_2:,}원 (+6.3%)\n"
        msg += f" • 시스템손절: {stop_p:,}원 (-3% 엄수)\n\n"
        
        msg += f"⏱ 예상 보유: 1~5일 모멘텀 스윙\n\n"
        
        msg += f"🚫 매수 취소 조건\n"
        msg += f" - 시장 위험 모드 진입 시 즉시 취소\n"
        msg += f" - 진입 전 거래량 급감 시 무효화\n"
        msg += f" - {stop_p:,}원 이탈 시 즉각 대응\n"
        msg += "=========================\n"
        
    return msg

def format_validate_message(results):
    msg = "⚠️ V8.4 15:00 생존 검사\n=========================\n"
    if not results: return msg + "검사 대상 종목 없음"
    for r in results:
        status = "🔥 유지" if r["survive"] else "❌ 탈락"
        reason_str = ', '.join(r['reason']) if r['reason'] else "특이사항 없음"
        msg += f"{status} {r['name']} | 수익:{r['change']}% | 사유:{reason_str}\n"
    return msg
