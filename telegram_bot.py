import os
import datetime
import pytz
import telegram

async def send_message(text):
    """텔레그램 메시지 발송 핵심 엔진"""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("🚨 환경변수 누락: TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID가 없습니다.")
        return
        
    bot = telegram.Bot(token=token)
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        print(f"텔레그램 발송 실패: {e}")

def format_scan_message(data):
    """V8.4.5 압도적 정보량 스캔 보고서 포맷"""
    kst = pytz.timezone("Asia/Seoul")
    now_str = datetime.datetime.now(kst).strftime("%Y-%m-%d %H:%M")
    
    market = data.get("market", {})
    stats = data.get("stats", {})
    cands = data.get("candidates", [])
    
    msg = f"🎯 [V8.4.5 퀀트 시그널 터미널]\n\n"
    msg += f"기준: {now_str}\n\n"
    msg += f"🌎 시장 상태\n"
    msg += f" 🟢 모드: {market.get('mode', '알 수 없음')}\n"
    msg += f" • 코스피: {market.get('kospi', 0)}%\n"
    msg += f" • 코스닥: {market.get('kosdaq', 0)}%\n"
    msg += f" • 위험도: {market.get('risk_pct', 0)}%\n\n"
    
    msg += f"📊 스캔 결과 통계\n"
    msg += f" • 전체 종목: {stats.get('total', 0):,}개\n"
    msg += f" • 1차 통과: {stats.get('pass1', 0):,}개\n"
    msg += f" • 최종 신호: {stats.get('final', 0)}개\n\n"
    
    msg += f"📉 1차 필터 통과자 정밀 탈락 원인\n"
    msg += f" • MA20 이탈 (역배열): {stats.get('drop_ma20', 0)}개\n"
    msg += f" • 거래량 유입 부족: {stats.get('drop_vol', 0)}개\n"
    msg += f" • 종합 점수 및 꼬리 미달: {stats.get('drop_score', 0)}개\n"
    msg += f" • 기타(검증 제외 등): {stats.get('drop_etc', 0)}개\n"
    msg += f"=========================\n\n"
    
    if not cands:
        msg += "⚙️ 필터 통과 종목 없음 (시드 보호 모드 정상 가동)\n"
        return msg
        
    for i, c in enumerate(cands):
        grade = "A+급 (🛡️ 정석형)" if c['score'] >= 85 else "A급 (🔥 공격형)"
        rr_ratio = round((c['target_1'] - c['buy_p']) / (c['buy_p'] - c['stop_p']), 2) if c['buy_p'] > c['stop_p'] else 0
        
        msg += f"{['🥇', '🥈', '🥉', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟'][i%10]} {i+1}순위 {c['name']} ({c['code']})\n"
        msg += f" 🎯 등급: {grade}\n"
        msg += f" 📊 종합 점수: {c['score']} / 100\n\n"
        
        msg += f"🛠 핵심 조건 충족: {c['cond_count']} / 5\n"
        msg += f" [{'✅' if c['c_vol'] else '❌'}] 거래량 (평균 대비 2배 이상)\n"
        msg += f" [{'✅' if c['c_rs'] else '❌'}] 상대강도 (시장 대비 RS 우위)\n"
        msg += f" [{'🟢' if c['c_heat'] else '⚠️'}] 이격도 (MA20 과열 방지)\n"
        msg += f" [{'✅' if c['c_amt'] else '❌'}] 거래대금 (당일 500억 이상)\n"
        msg += f" [{'✅' if c['c_shadow'] else '❌'}] 윗꼬리 리스크 (3% 이하 안정)\n\n"
        
        msg += f"📌 현재 상태 및 판정\n"
        msg += f" • 현재가: {c['price']:,}원 ({c['chg']}%)\n"
        msg += f" • 진입선: {c['buy_p']:,}원 이하\n"
        msg += f" • 판정: ✅ 진입선 도달 시 매수 유효\n\n"
        
        msg += f"📈 시장 상대강도 (RS - 5일 기준)\n"
        msg += f" • 종목({c['five_chg']}%) vs 코스피({c['kospi_chg']}%)\n"
        msg += f" • 시장 대비: {c['rs']}% (상대 우위)\n\n"
        
        msg += f"🔥 과열도 및 손익비\n"
        msg += f" • MA20 이격: +{c['ma_gap']}% \n"
        msg += f" • 1차 R:R: {rr_ratio} \n\n"
        
        msg += f"🎯 매매 전략\n"
        msg += f" • 매수: {c['buy_p']:,}원 부근\n"
        msg += f" • 익절: {c['target_1']:,}원 / {c['target_2']:,}원\n"
        msg += f" • 손절: {c['stop_p']:,}원 (-3% 엄수)\n\n"
        
        msg += f"⏱ 예상: 1~5일 모멘텀 스윙\n"
        msg += f"=========================\n\n"
        
    return msg

def format_validate_message(results):
    """장 마감 후 정밀 검증 보고 포맷"""
    if not results:
        return "🔍 [V8.4.5 장 마감 정밀 검증]\n⚙️ 검증 완료: 특이사항 없음"
    
    msg = "🔍 [V8.4.5 장 마감 정밀 검증]\n=========================\n"
    for r in results:
        msg += f"• {r.get('name', '알 수 없음')} ({r.get('code', '000000')}): {r.get('status', '상태 확인 필요')}\n"
    return msg

def format_d3_profit_message(results):
    """D+3 익절/손절 청산 대상 보고 포맷"""
    if not results:
        return ""
