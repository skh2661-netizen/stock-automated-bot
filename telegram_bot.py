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
    fail_stats = data.get("fail_stats", {"ma20":0, "vol":0, "score":0, "etc":0})
    candidates = data["candidates"]
    
    mode_icon = "🟢" if "정상" in market["mode"] else "🚨"
    msg = f"🎯 [V8.4.5 퀀트 시그널 터미널]\n\n"
    msg += f"기준: {time_str}\n\n"
    
    msg += f"🌎 시장 상태\n"
    msg += f" {mode_icon} 모드: {market['mode']}\n"
    msg += f" • 코스피: {market['kospi']}%\n"
    msg += f" • 코스닥: {market['kosdaq']}%\n"
    msg += f" • 위험도: {market['risk_pct']}%\n\n"
    
    msg += f"📊 스캔 결과 통계\n"
    msg += f" • 전체 종목: {stats['total']:,}개\n"
    msg += f" • 1차 통과: {stats['pass1']:,}개\n"
    msg += f" • 최종 신호: {stats['final']}개\n\n"
    
    hour = now.hour
    if 8 <= hour < 10:
        time_msg = "☀️ 시초가 돌파 주도주 탐색"
    elif 10 <= hour < 14:
        time_msg = "🔥 장중 모멘텀 및 수급 탐색"
    elif 14 <= hour < 15:
        time_msg = "🎯 종가 베팅 후보 정밀 탐색"
    else:
        time_msg = "🌙 장 마감 결과 복기 모드 (신규 진입 주의)"

    msg += f"⏰ 현재 작전 모드\n"
    msg += f" 👉 {time_msg}\n\n"

    msg += f"📉 1차 필터 통과자 정밀 탈락 원인\n"
    msg += f" • MA20 이탈 (역배열): {fail_stats['ma20']}개\n"
    msg += f" • 거래량 유입 부족: {fail_stats['vol']}개\n"
    msg += f" • 종합 점수(RS 등) 미달: {fail_stats['score']}개\n"
    msg += "=========================\n\n"
    
    if not candidates:
        return msg + "⚙️ 필터 통과 종목 없음 (시드 보호 모드 정상 가동)"
        
    for i, r in enumerate(candidates, 1):
        rank_icon = "🥇 1순위" if i == 1 else ("🥈 2순위" if i == 2 else f"🏅 {i}순위")
        
        strong_buy_alert = ""

        # [신규 추가: 90점 이상 & 단기 과열 없을 시 초강력 매수 추천 시각화]
        if r['score'] >= 90 and r.get('ma_gap', 0) < 15: 
            sig_grade = "👑 S급 (초강력 매수 / 승률 극대화 구간)"
            strong_buy_alert = "🔥🔥🔥 [무조건 매수: 최우선 진입 타겟] 🔥🔥🔥\n"
        elif r['score'] >= 85 and r.get('ma_gap', 0) < 15: sig_grade = "A+급 (정석/안정형)"
        elif r['score'] >= 85 and r.get('ma_gap', 0) >= 15: sig_grade = "A급 (공격/과열존재)"
        elif r['score'] >= 80: sig_grade = "B+급 (모멘텀 양호)"
        else: sig_grade = "B급 (관찰 대상)"

        if r.get('ma_gap', 0) >= 20: 
            heat_judge = "🚨 초과열"
            chase_warn = "❌ 추격 매수 절대 금지 (깊은 눌림 대기)"
        elif r.get('ma_gap', 0) >= 15: 
            heat_judge = "⚠️ 과열"
            chase_warn = "⚠️ 추격 매수 주의 (비중 축소)"
        else: 
            heat_judge = "🟢 안정"
            chase_warn = "✅ 진입선 도달 시 매수 유효"

        if r['price'] <= r.get('buy_p', 0): signal_status = "🟢 매수 가능 구간"
        else: signal_status = "🟡 눌림 대기"

        reward = r.get('target_1', 0) - r.get('buy_p', 0)
        risk = r.get('buy_p', 0) - r.get('stop_p', 0)
        rr_ratio = round(reward / risk, 2) if risk > 0 else 0

        # 초강력 매수 추천 시각화 적용
        msg += f"{strong_buy_alert}"
        msg += f"{rank_icon} {r['name']} ({r['code']})\n"
        msg += f" 🎯 등급: {sig_grade}\n"
        msg += f" 📊 점수: {r['score']} / 100\n\n"

        msg += f"🛠 핵심 조건 충족: {r.get('cond_count', 5)} / 5\n"
        msg += f" [{'✅' if r.get('c_vol', True) else '❌'}] 거래량 (평균 대비 2배 이상)\n"
        msg += f" [{'✅' if r.get('c_rs', True) else '❌'}] 상대강도 (시장 대비 RS 우위)\n"
        msg += f" [{'✅' if r.get('c_heat', True) else '⚠️'}] 이격도 (MA20 단기 과열 방지)\n"
        msg += f" [{'✅' if r.get('c_amt', True) else '❌'}] 거래대금 (당일 500억 이상 유입)\n"
        msg += f" [{'✅' if r.get('c_shadow', True) else '❌'}] 윗꼬리 안정성 (매물대 출회 위험 낮음)\n\n"
        
        msg += f"📌 현재 상태 및 추격 위험도\n"
        msg += f" • 현재가: {r['price']:,}원 ({r.get('chg', 0)}%)\n"
        msg += f" • 진입선: {r.get('buy_p', 0):,}원 이하\n"
        msg += f" • 상태: {signal_status}\n"
        msg += f" • 판정: {chase_warn}\n\n"
        
        msg += f"📈 시장 상대강도 (RS - 5일 기준)\n"
        msg += f" • 종목(+{r.get('five_chg', 0)}%) vs 코스피({r.get('kospi_chg', 0)}%)\n"
        msg += f" • 시장 대비: +{r.get('rs', 0)}% (상대 우위)\n\n"

        msg += f"🔥 과열도 및 손익비\n"
        msg += f" • MA20 이격: +{r.get('ma_gap', 0)}% ({heat_judge})\n"
        msg += f" • 1차 R:R: {rr_ratio}\n\n"
        
        msg += f"🎯 매매 전략\n"
        msg += f" • 매수: {r.get('buy_p', 0):,}원 부근\n"
        msg += f" • 익절: {r.get('target_1', 0):,}원 / {r.get('target_2', 0):,}원\n"
        # [수정: 변동성 대응형 손절 포맷 적용]
        msg += f" • 손절: {r.get('stop_p', 0):,}원 (변동성 대응: 당일 시가 대비 -3% 또는 5일 최저가 이탈 시)\n\n"

        msg += f"📌 사후 관리 규칙\n"
        msg += f" • +3% 도달: 손절선을 진입가로 이동 (본절 방어)\n"
        msg += f" • +6% 도달: 물량 50% 기계적 익절\n"
        msg += f" • 고점 대비 -3%: 잔량 전량 청산 (트레일링)\n\n"

        msg += f"🤖 [백테스트 시스템]\n"
        msg += f" • 표본 상태: 실시간 데이터 적재 중\n"
        msg += f" • 신뢰도 판정: 검증 대기 (통계값 빌드 중)\n"
        msg += "=========================\n"
        
    return msg

def format_validate_message(results):
    msg = "⚠️ V8.4.5 15:00 생존 검사\n=========================\n"
    if not results: return msg + "검사 대상 종목 없음"
    for r in results:
        status = "🔥 유지" if r["survive"] else "❌ 탈락"
        reason_str = ', '.join(r['reason']) if r['reason'] else "특이사항 없음"
        msg += f"{status} {r['name']} | 수익:{r['change']}% | 사유:{reason_str}\n"
    return msg

# [보완] 원격지 ImportError 해결 및 D+3 기계적 익절 알림
def format_d3_profit_message(results):
    msg = "🚨 [수익 실현 알림] D+3 스윙 타겟 기계적 청산\n=========================\n"
    if not results: return msg + "오늘(D+3) 청산 대상 종목 없음."
    
    for r in results:
        msg += f"💰 {r['name']} ({r['code']})\n"
        msg += f" • 진입가: {r['buy_p']:,}원\n"
        msg += f" • 현재가: {r['current']:,}원 ({r['change']}%)\n"
        msg += f" 👉 액션: 전량 익절 (통계상 최대 수익 구간 도달)\n\n"
    return msg
