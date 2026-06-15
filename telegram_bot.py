import telegram, asyncio
import os

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
            await bot.send_message(chat_id=chat_id, text=text)
            break
        except Exception as e: 
            print(f"텔레그램 전송 실패, 재시도 중... ({e})")
            await asyncio.sleep(3)

def format_scan_message(results):
    """최대 상세 정보 + 자동 타점 연산 보고서"""
    msg = "🎯 [무인 요새 정밀 타격 리포트]\n=========================\n"
    if not results: return msg + "조건 만족 종목 없음"
    
    for i, r in enumerate(results, 1):
        # 기계적 타점 연산 (단기 눌림목 기준)
        buy_p = int(r['price'] * 0.985)   # 현재가 대비 -1.5% 눌림 매수
        stop_p = int(r['price'] * 0.970)  # 현재가 대비 -3.0% 칼손절
        target_p = int(r['price'] * 1.024) # 현재가 대비 +2.4% 1차 익절
        
        # 스코어 기반 매력도 별점 환산
        stars = "★" * 5 if r['score'] >= 90 else ("★" * 4 if r['score'] >= 80 else "★" * 3)

        msg += f"📈 [{r['name']}] 매력도: {stars}\n"
        msg += f"   • 현재종가: {r['price']:,}원 ({r['chg']}%)\n"
        msg += f"   • 🛒 단타매수: {buy_p:,}원 부근\n"
        msg += f"   • 🛑 칼손절선: {stop_p:,}원 엄수\n"
        msg += f"   • 🎯 1차익절: {target_p:,}원\n"
        msg += f"   * (종합점수: {r['score']}점 / 수급: {r['amount']:,}억)\n"
        msg += "=========================\n"
    return msg

def format_validate_message(results):
    """15:00 종가 생존 검사 결과 양식"""
    msg = "⚠️ V8.4 15:00 생존 검사\n=========================\n"
    if not results: return msg + "검사 대상 종목 없음"
    
    for r in results:
        status = "🔥 유지" if r["survive"] else "❌ 탈락"
        reason_str = ', '.join(r['reason']) if r['reason'] else "특이사항 없음"
        msg += f"{status} {r['name']} | 수익:{r['change']}% | 사유:{reason_str}\n"
    return msg
