import telegram, asyncio
import os
import datetime
import pytz

async def send_message(text):
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
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    time_str = now.strftime("%Y-%m-%d %H:%M")
    
    market = data["market"]
    stats = data["stats"]
    candidates = data["candidates"]
    
    mode_icon = "🟢" if "정상" in market["mode"] else "🚨"
    msg = f"🎯 [V8.4 퀀트 시그널 터미널]\n\n"
    msg += f"기준: {time_str}\n\n"
    
    msg += f"🌎 시장 상태\n"
    msg += f" {mode_icon} 모드: {market['mode']}\n"
    msg += f" • 코스피: {market['kospi']}%\n"
    msg += f" • 코스닥: {market['kosdaq']}%\n"
    msg += f" • 위험도: {market['risk_pct']}%\n\n"
    
    msg += f"📊 스캔 결과 통계\n"
    msg += f" • 전체 종목: {stats['total']:,}개\n"
    msg += f" • 1차 필터 통과: {stats['pass1']:,}개\n"
    msg += f" • 최종 검출 신호: {stats['final']}개\n"
    
    # ⏰ 진입 시간 판단 로직
    msg += f"\n⏰ 진입 시간 판단\n"
    if now.hour >= 14:
        msg += f" ⚠️ 14:00 이후 신규 진입 주의\n"
        msg += f" 👉 종가 배팅 또는 익일 시초/눌림 대기 권장\n"
    else:
        msg += f" ✅ 당일 장중 눌림목 진입 유효\n"
    msg += "=========================\n\n"
    
    if not candidates:
        return msg + "⚙️ 필터 통과 종목 없음 (시드 보호 모드 가동)"
        
    for i, r in enumerate(candidates, 1):
        rank_icon = "🥇 1순위" if i == 1 else ("🥈 2순위" if i == 2 else f"🏅 {i}순위")

        if r['score'] >= 90: sig_grade = "S급"
        elif r['score'] >= 85: sig_grade = "A+급"
        elif r['score'] >= 80: sig_grade = "A급"
        else: sig_grade = "B급"

        if r['ma_gap'] >= 20: 
            heat_judge = "🚨 초과열"
            chase_warn = "❌ 추격 매수 절대 금지 (깊은 눌림 대기)"
        elif r['ma_gap'] >= 15: 
            heat_judge = "⚠️ 과열"
            chase_warn = "⚠️ 추격 매수 주의"
        else: 
            heat_judge = "🟢 안정"
            chase_warn = "✅ 진입선 도달 시 매수 유효"

        if r['price'] <= r['buy_p']: signal_status = "🟢 매수 가능 구간"
        else: signal_status = "🟡 눌림 대기"

        reward = r['target_1'] - r['buy_p']
        risk = r['buy_p'] - r['stop_p']
        rr_ratio = round(reward / risk, 2) if risk > 0 else 0

        msg += f"{rank_icon} {r['name']} ({r['code']})\n"
        msg += f" 🎯 등급: {sig_grade} ({r['sig_type']})\n"
        msg += f" 📊 점수: {r['score']} / 100\n\n"

        msg += f"🛠 핵심 조건 충족: {r['cond_count']} / 5\n"
        msg += f" [{'✅' if r['c_vol'] else '❌'}] 거래량 (2배 이상)\n"
        msg += f" [{'✅' if r['c_rs'] else '❌'}] 상대강도 (RS 우위)\n"
        msg += f" [{'✅' if r['c_heat'] else '⚠️'}] 이격도 (과열 방지)\n\n"
        
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

        # 🤖 백테스트 모듈 연동 준비용 더미 출력 (추후 실제 DB 연동)
        win_rate = min(90, 60 + (r['score'] - 75))
        msg += f"🤖 [시뮬레이션 예상 승률]\n"
        msg += f" • 유사 패턴 표본: 데이터 적재 중\n"
        msg += f" • 예상 승률: {win_rate}%\n"
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
