import telegram, asyncio
import os
import datetime
import pytz

async def send_message(text):
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
            await asyncio.sleep(3)

def format_scan_message(data):
    kst = pytz.timezone('Asia/Seoul')
    time_str = datetime.datetime.now(kst).strftime("%Y-%m-%d %H:%M")
    
    market = data["market"]
    stats = data["stats"]
    candidates = data["candidates"]
    
    mode_icon = "🟢" if "정상" in market["mode"] else "🚨"
    msg = f"🎯 [V8.4 무인 요새 정밀 타격 리포트]\n\n"
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
    msg += "=========================\n\n"
    
    if not candidates:
        return msg + "⚙️ 필터 통과 종목 없음 (시드 보호 모드 가동)"
        
    for i, r in enumerate(candidates, 1):
        buy_p = int(r['price'] * 0.985)
        target_1 = int(r['price'] * 1.023)
        target_2 = int(r['price'] * 1.063)
        stop_p = int(r['price'] * 0.970)
        
        # 1. 랭킹 아이콘 세팅
        if i == 1: rank_icon = "🥇 1순위"
        elif i == 2: rank_icon = "🥈 2순위"
        elif i == 3: rank_icon = "🥉 3순위"
        else: rank_icon = f"🏅 {i}순위"

        # 2. 신호 등급 판독
        if r['score'] >= 90: sig_grade = "S급 (조건 충족 95%+)"
        elif r['score'] >= 85: sig_grade = "A+급 (조건 충족 90%+)"
        elif r['score'] >= 80: sig_grade = "A급 (조건 충족 85%+)"
        else: sig_grade = "B급 (표준 타겟)"

        # 3. 이격도 기반 단기 과열도 판정
        if r['ma_gap'] >= 20: heat_judge = "🚨 주의: 단기 초과열 구간"
        elif r['ma_gap'] >= 15: heat_judge = "⚠️ 단기 상승 과열"
        else: heat_judge = "🟢 안정적 이격도"

        if r['price'] <= buy_p: signal_status = "🟢 매수 가능 구간"
        else: signal_status = "🟡 눌림 대기 (추격 매수 금지)"

        reward = target_1 - buy_p
        risk = buy_p - stop_p
        rr_ratio = round(reward / risk, 2) if risk > 0 else 0
        rr_judge = "✅ 우수 (진입 유리)" if rr_ratio >= 1.5 else ("⚠️ 보통" if rr_ratio >= 1.0 else "🚨 보수적 접근")

        msg += f"{rank_icon} {r['name']} ({r['code']})\n"
        msg += f" 🎯 신호 등급: {sig_grade}\n"
        msg += f" 📊 종합 점수: {r['score']} / 100\n\n"
        
        msg += f"📌 현재 상태\n"
        msg += f" • 현재가: {r['price']:,}원\n"
        msg += f" • 진입선: {buy_p:,}원 이하\n"
        msg += f" • 상태: {signal_status}\n\n"
        
        msg += f"📈 시장 상대강도 (RS - 5거래일 기준)\n"
        msg += f" • 종목(+{r['five_chg']}%) vs 코스피({r['kospi_chg']}%)\n"
        msg += f" • 시장 대비: +{r['rs']}% (상대 우위)\n\n"

        msg += f"🔥 과열도 및 손익비\n"
        msg += f" • MA20 이격: +{r['ma_gap']}% ({heat_judge})\n"
        msg += f" • 1차 R:R 비율: {rr_ratio} ({rr_judge})\n\n"

        msg += f"💰 수급 현황\n"
        msg += f" • 거래대금: {r['amount']:,}억 원\n"
        msg += f" • 거래량: 평균 대비 {r['vol_ratio']}배\n\n"
        
        msg += f"🎯 매매 전략\n"
        msg += f" • 진입타점: {buy_p:,}원 부근\n"
        msg += f" • 1차 익절: {target_1:,}원\n"
        msg += f" • 2차 익절: {target_2:,}원\n"
        msg += f" • 칼 손 절: {stop_p:,}원 (-3% 엄수)\n\n"
        
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
