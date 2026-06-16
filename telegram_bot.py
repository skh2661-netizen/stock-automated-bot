import telegram, asyncio, os, datetime, pytz

async def send_message(text):
    """텔레그램 메시지 안전 전송"""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    bot = telegram.Bot(token=token)
    for _ in range(3):
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=None)
            break
        except Exception: await asyncio.sleep(3)

def format_scan_message(data):
    """V8.4.2 원본 상세 리포트 UI (KeyError 방지 적용)"""
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    time_str = now.strftime("%Y-%m-%d %H:%M")
    
    market = data.get("market", {})
    stats = data.get("stats", {})
    candidates = data.get("candidates", [])
    
    mode_icon = "🟢" if "정상" in market.get("mode", "") else "🚨"
    
    msg = f"🎯 [V8.4.2 퀀트 시그널 터미널]\n\n기준: {time_str}\n\n"
    msg += f"🌎 시장 상태\n {mode_icon} 모드: {market.get('mode', '알 수 없음')}\n"
    msg += f" • 코스피: {market.get('kospi', 0)}%\n • 코스닥: {market.get('kosdaq', 0)}%\n"
    msg += f" • 위험도: {market.get('risk_pct', 0)}%\n\n" # KeyError 방지 적용
    
    msg += f"📊 스캔 결과 통계\n • 전체 종목: {stats.get('total', 0):,}개\n • 최종 검출 신호: {stats.get('final', 0)}개\n"
    msg += "=========================\n"
    
    for r in candidates:
        msg += f"• {r['name']} | 점수: {r['score']}\n"
    return msg

def format_validate_message(results):
    msg = "⚠️ V8.4.2 장 마감 생존 검사\n=========================\n"
    for r in results:
        msg += f"{'🔥' if r.get('survive') else '❌'} {r.get('name')} | 사유:{','.join(r.get('reason', []))}\n"
    return msg

def format_d3_profit_message(results):
    return "💰 D+3 청산 알림\n" + "\n".join([f"• {r.get('name')}: {r.get('profit', 0)}%" for r in results])
