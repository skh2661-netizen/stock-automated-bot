import telegram, asyncio
import os
import datetime
import pytz

async def send_message(text):
    """텔레그램 메시지 안전 전송"""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        return

    bot = telegram.Bot(token=token)
    for _ in range(3):
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=None)
            break
        except Exception as e: 
            await asyncio.sleep(3)

def format_scan_message(data):
    """형님의 V8.4.2 상세 리포트 UI 원본 전체"""
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    time_str = now.strftime("%Y-%m-%d %H:%M")
    
    market = data["market"]
    stats = data["stats"]
    candidates = data["candidates"]
    
    mode_icon = "🟢" if "정상" in market["mode"] else "🚨"
    msg = f"🎯 [V8.4.2 퀀트 시그널 터미널]\n\n"
    msg += f"기준: {time_str}\n\n"
    
    msg += f"🌎 시장 상태\n"
    msg += f" {mode_icon} 모드: {market['mode']}\n"
    msg += f" • 코스피: {market['kospi']}%\n"
    msg += f" • 코스닥: {market['kosdaq']}%\n"
    msg += f" • 위험도: {market['risk_pct']}%\n\n"
    
    msg += f"📊 스캔 결과 통계\n"
    msg += f" • 전체 종목: {stats['total']:,}개\n"
    msg += f" • 1차 필터 통과: {stats['pass1']:,}개\n"
    msg += f" • 최종 검출 신호: {stats['final']}개\n\n"

    msg += f"📉 1차 필터 통과자 정밀 탈락 원인\n"
    msg += f" • MA20 이탈 (역배열): {stats.get('drop_ma20', 0)}개\n"
    msg += f" • 거래량 유입 부족: {stats.get('drop_vol', 0)}개\n"
    msg += f" • 종합 점수(RS 등) 미달: {stats.get('drop_score', 0)}개\n"
    msg += f" • 기타(검증 제외 등): {stats.get('drop_etc', 0)}개\n"
    
    msg += f"\n⏰ 진입 시간 판단\n"
    if now.hour >= 14:
        msg += f" ⚠️ 14:00 이후 신규 진입 주의\n"
        msg += f" 👉 종가 배팅 또는 익일 시초/눌림 대기 권장\n"
    else:
        msg += f" 👉 ☀️ 시초가 돌파 주도주 탐색\n"
    msg += "=========================\n\n"
    
    if not candidates:
        return msg + "⚙️ 필터 통과 종목 없음 (시드 보호 모드 정상 가동)"
        
    for i, r in enumerate(candidates, 1):
        rank_icon = "🥇 1순위" if i == 1 else ("🥈 2순위" if i == 2 else f"🏅 {i}순위")

        if r['score'] >= 85 and r['ma_gap'] < 15: 
            sig_grade = "A+급 (🛡️ 정석형 (안정적 밸런스))"
        elif r['score'] >= 85 and r['ma_gap'] >= 15: 
            sig_grade = "A급 (🔥 공격형 (모멘텀 극대화))"
        elif r['score'] >= 80: 
            sig_grade = "B+급 (모멘텀 양호)"
        else: 
            sig_grade = "B급 (관찰 대상)"

        if r['ma_gap'] >= 20: 
            heat_judge = "🚨 초과열"
            chase_warn = "❌ 추격 매수 절대 금지 (깊은 눌림 대기)"
        elif r['ma_gap'] >= 15: 
            heat_judge = "⚠️ 과열존재"
            chase_warn = "⚠️ 추격 매수 주의 (비중 축소)"
        else: 
            heat_judge = "🟢 안정"
            chase_warn = "✅ 진입선 도달 시 매수 유효"

        if r['price'] <= r['buy_p']: signal_status = "🟢 매수 가능 구간"
        else: signal_status = "🟡 눌림 대기"

        reward = r['target_1'] - r['buy_p']
        risk = r['buy_p'] - r['stop_p']
        rr_ratio = round(reward / risk, 2) if risk > 0 else 0

        msg += f"{rank_icon} {r['name']} ({r['code']})\n"
        msg += f" 🎯 등급: {sig_grade}\n"
        msg += f" 📊 종합 점수: {r['score']} / 100\n\n"

        msg += f"🛠 핵심 조건 충족: {r['cond_count']} / 5\n"
        msg += f" [{'✅' if r['c_vol'] else '❌'}] 거래량 (평균 대비 2배 이상)\n"
        msg += f" [{'✅' if r['c_rs'] else '❌'}] 상대강도 (시장 대비 RS 우위)\n"
        msg += f" [{'🟢' if r['c_heat'] else '⚠️'}] 이격도 (MA20 과열 방지)\n"
        msg += f" [{'✅' if r['c_amt'] else '❌'}] 거래대금 (당일 500억 이상)\n"
        msg += f" [{'✅' if r['c_shadow'] else '❌'}] 윗꼬리 리스크 (2% 미만 안정)\n\n"
        
        msg += f"📌 현재 상태 및 추격 위험도\n"
        msg += f" • 현재가: {r['price']:,}원 ({r['chg']}%)\n"
        msg += f" • 진입선: {r['buy_p']:,}원 이하\n"
        msg += f" • 상태: {signal_status}\n"
        msg += f" • 판정: {chase_warn}\n\n"
        
        msg += f"📈 시장 상대강도 (RS - 5일 기준)\n"
        msg += f" • 종목(+{r['five_chg']}%) vs 코스피({r['kospi_chg']}%)\n"
        msg += f" • 시장 대비: +{r['rs']}% (상대 우위)\n\n"

        msg += f"🔥 과열도 및 손익비\n"
        msg += f" • MA20 이격: +{r['ma_gap']}% ({heat_judge})\n"
        msg += f" • 1차 R:R: {rr_ratio}\n\n"
        
        msg += f"🎯 매매 전략\n"
        msg += f" • 매수: {r['buy_p']:,}원 부근\n"
        msg += f" • 익절: {r['target_1']:,}원 / {r['target_2']:,}원\n"
        msg += f" • 손절: {r['stop_p']:,}원 (-3% 엄수)\n\n"

        msg += f"📌 사후 관리 규칙\n"
        msg += f" • +3% 도달: 손절선을 진입가로 이동 (본절 방어)\n"
        msg += f" • +6% 도달: 물량 50% 기계적 익절\n"
        msg += f" • 고점 대비 -3%: 잔량 전량 청산 (트레일링)\n\n"

        msg += f"⏱ 예상: 1~5일 모멘텀 스윙\n\n"

        msg += f"🤖 [백테스트 시스템]\n"
        msg += f" • 표본 상태: 실시간 데이터 적재 중\n"
        msg += f" • 신뢰도 판정: 검증 대기 (통계값 빌드 중)\n"
        msg += "=========================\n\n"
        
    return msg

def format_validate_message(results):
    msg = "⚠️ V8.4.2 장 마감 생존 검사\n=========================\n"
    if not results: return msg + "검사 대상 종목 없음"
    for r in results:
        status = "🔥 유지" if r["survive"] else "❌ 탈락"
        reason_str = ', '.join(r['reason']) if r['reason'] else "특이사항 없음"
        msg += f"{status} {r['name']} | 수익:{r['change']}% | 사유:{reason_str}\n"
    return msg

def format_d3_profit_message(results):
    if not results: return ""
    msg = "💰 [V8.4.2 D+3 청산 대상 알림]\n=========================\n"
    for r in results:
        msg += f"• {r.get('name')}: 수익률 {r.get('profit', 0)}%\n"
    return msg
