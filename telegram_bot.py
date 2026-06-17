import telegram, asyncio
import os
import datetime
import pytz

async def send_message(text):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    print("TOKEN 존재:", bool(token))
    print("CHAT 존재:", bool(chat_id))
    
    if not token or not chat_id:
        print("텔레그램 환경변수 없음")
        return

    bot = telegram.Bot(token=token)
    for _ in range(3):
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=None)
            print("텔레그램 발송 성공")
            return
        except Exception as e:
            print("텔레그램 오류:", e)
            await asyncio.sleep(3)

def format_scan_message(data):
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    time_str = now.strftime("%Y-%m-%d %H:%M")
    
    market = data.get("market", {})
    stats = data.get("stats", {})
    fail_stats = data.get("fail_stats", {"ma20":0, "vol":0, "score":0, "etc":0})
    candidates = data.get("candidates", [])
    
    mode_icon = "🟢" if "정상" in market.get("mode", "") else "🚨"
    msg = f"🎯 [V8.4.5 퀀트 시그널 터미널]\n\n기준: {time_str}\n\n"
    
    msg += f"🌎 시장 상태\n {mode_icon} 모드: {market.get('mode', '알 수 없음')}\n • 코스피: {market.get('kospi', 0)}%\n • 위험도: {market.get('risk_pct', 0)}%\n\n"
    msg += f"📊 스캔 결과 통계\n • 전체 종목: {stats.get('total', 0):,}개\n • 1차 통과: {stats.get('pass1', 0):,}개\n • 최종 신호: {stats.get('final', 0)}개\n\n"
    
    hour = now.hour
    if 8 <= hour < 10: time_msg = "☀️ 시초가 돌파 주도주 탐색"
    elif 10 <= hour < 14: time_msg = "🔥 장중 모멘텀 및 수급 탐색"
    elif 14 <= hour < 15: time_msg = "🎯 종가 베팅 후보 정밀 탐색"
    else: time_msg = "🌙 장 마감 결과 복기 모드 (신규 진입 주의)"

    msg += f"⏰ 현재 작전 모드\n 👉 {time_msg}\n\n"
    msg += f"📉 1차 필터 통과자 정밀 탈락 원인\n • MA20 이탈 (역배열): {fail_stats.get('ma20', 0)}개\n • 거래량 유입 부족: {fail_stats.get('vol', 0)}개\n • 종합 점수(RS 등) 미달: {fail_stats.get('score', 0)}개\n=========================\n\n"
    
    if not candidates: return msg + "⚙️ 필터 통과 종목 없음 (시드 보호 모드 정상 가동)"
        
    for i, r in enumerate(candidates, 1):
        rank_icon = "🥇 1순위" if i == 1 else ("🥈 2순위" if i == 2 else f"🏅 {i}순위")
        strong_buy_alert = ""

        if r.get('score', 0) >= 90 and r.get('ma_gap', 0) < 15: 
            sig_grade = "👑 S급 (초강력 매수 / 승률 극대화 구간)"
            strong_buy_alert = "🔥🔥🔥 [무조건 매수: 최우선 진입 타겟] 🔥🔥🔥\n"
        elif r.get('score', 0) >= 85 and r.get('ma_gap', 0) < 15: sig_grade = "A+급 (정석/안정형)"
        elif r.get('score', 0) >= 85 and r.get('ma_gap', 0) >= 15: sig_grade = "A급 (공격/과열존재)"
        elif r.get('score', 0) >= 80: sig_grade = "B+급 (모멘텀 양호)"
        else: sig_grade = "B급 (관찰 대상)"

        if r.get('ma_gap', 0) >= 20: heat_judge, chase_warn = "🚨 초과열", "❌ 추격 매수 절대 금지 (깊은 눌림 대기)"
        elif r.get('ma_gap', 0) >= 15: heat_judge, chase_warn = "⚠️ 과열", "⚠️ 추격 매수 주의 (비중 축소)"
        else: heat_judge, chase_warn = "🟢 안정", "✅ 진입선 도달 시 매수 유효"

        signal_status = "🟢 매수 가능 구간" if r.get('price', 0) <= r.get('buy_p', 0) else "🟡 눌림 대기"
        reward = r.get('target_1', 0) - r.get('buy_p', 0)
        risk = r.get('buy_p', 0) - r.get('stop_p', 0)
        rr_ratio = round(reward / risk, 2) if risk > 0 else 0

        msg += f"{strong_buy_alert}{rank_icon} {r.get('name', '알수없음')} ({r.get('code', '000000')})\n 🎯 등급: {sig_grade}\n 📊 점수: {r.get('score', 0)} / 100\n\n"
        # 수정 지점: [⚠️] 이격도 표기 문구 개선
        msg += f"🛠 핵심 조건 충족: {r.get('cond_count', 0)} / 5\n [{'✅' if r.get('c_vol', False) else '❌'}] 거래량 (평균 대비 2배 이상)\n [{'✅' if r.get('c_rs', False) else '❌'}] 상대강도 (시장 대비 RS 우위)\n [{'✅' if r.get('c_heat', False) else '⚠️'}] 이격도 (15% 초과 시 과열주의)\n [{'✅' if r.get('c_amt', False) else '❌'}] 거래대금 (당일 500억 이상 유입)\n [{'✅' if r.get('c_shadow', False) else '❌'}] 윗꼬리 안정성 (매물대 출회 위험 낮음)\n\n"
        msg += f"📌 현재 상태 및 추격 위험도\n • 현재가: {r.get('price', 0):,}원 ({r.get('chg', 0)}%)\n • 진입선: {r.get('buy_p', 0):,}원 이하\n • 상태: {signal_status}\n • 판정: {chase_warn}\n\n"
        msg += f"📈 시장 상대강도 (RS - 5일 기준)\n • 종목(+{r.get('five_chg', 0)}%) vs 코스피({r.get('kospi_chg', 0)}%)\n • 시장 대비: {r.get('rs', 0):+}% (상대 우위)\n\n"
        msg += f"🔥 과열도 및 손익비\n • MA20 이격: {r.get('ma_gap', 0):+}% ({heat_judge})\n • 1차 R:R: {rr_ratio}\n\n"
        msg += f"🎯 매매 전략\n • 매수: {r.get('buy_p', 0):,}원 부근\n • 익절: {r.get('target_1', 0):,}원 / {r.get('target_2', 0):,}원\n • 손절: {r.get('stop_p', 0):,}원 (변동성 대응)\n\n=========================\n"
    return msg

def format_validate_message(results):
    msg = "⚠️ V8.4.5 15:00 생존 검사\n=========================\n"
    if not results: return msg + "검사 대상 종목 없음"
    for r in results:
        status = "🔥 유지" if r.get("survive") else "❌ 탈락"
        reason_str = ', '.join(r.get('reason', [])) if r.get('reason') else "특이사항 없음"
        msg += f"{status} {r.get('name', '')} | 수익:{r.get('change', 0)}% | 사유:{reason_str}\n"
    return msg

def format_d3_profit_message(results):
    msg = "🚨 [수익 실현 알림] D+3 스윙 타겟 기계적 청산\n=========================\n"
    if not results: return msg + "오늘(D+3) 청산 대상 종목 없음."
    for r in results:
        msg += f"💰 {r.get('name', '')} ({r.get('code', '')})\n • 진입가: {r.get('buy_p', 0):,}원\n • 현재가: {r.get('current', 0):,}원 ({r.get('change', 0)}%)\n 👉 액션: 전량 익절 (통계상 최대 수익 구간 도달)\n\n"
    return msg
