import FinanceDataReader as fdr
import pandas as pd
import datetime
import pytz
import telegram
import asyncio
import os

TOKEN = os.environ['TELEGRAM_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

async def main():
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    weekday = now.weekday()
    hour = now.hour
    minute = now.minute
    
    if weekday >= 5:
        print("⚠️ 주말 휴장일 차단막 가동.")
        return

    # 한국거래소 전 종목 수집
    krx_df = fdr.StockListing('KRX')
    ratio_col = 'ChangesRatio' if 'ChangesRatio' in krx_df.columns else 'Change'
    krx_df['Amount'] = krx_df['Close'] * krx_df['Volume']
    
    safe_target = ~krx_df['Name'].str.contains('스팩|ETF|ETN|우$|우[A-Z]$|제[0-9]+호', regex=True)
    krx_df = krx_df[safe_target].copy()

    # 기본 필터링 (2천원 이상, 상승률 5~25%, 거래량 100만 이상)
    cond = (krx_df['Close'] >= 2000) & (krx_df[ratio_col] >= 5.0) & (krx_df[ratio_col] <= 25.0) & (krx_df['Volume'] >= 1000000)
    top_10 = krx_df[cond].sort_values(by='Amount', ascending=False).head(10)

    # [시간대별 3방향 리포트 분기 연산]
    if hour == 8:
        title_mode = "☀️ [08:50 시초가 돌파 타격 지시]"
        desc = "당일 아침 강한 수급 쏠림 시 즉각 추격 매수 대기"
    elif hour == 15 and minute < 30:
        title_mode = "⚠️ [15:00 종가 베팅 정찰 (수동 검열)]"
        desc = "지연 데이터 혼재 구간. 반드시 MTS 육안 확인 후 진입할 것"
    else:
        title_mode = "🌙 [15:40 당일 완결 복기 리포트]"
        desc = "금일 주도주 최종 정산 및 내일장 관심 종목"

    report_msg = f"{title_mode}\n"
    report_msg += f"기준: {now.strftime('%m/%d %H:%M')}\n"
    report_msg += f"전술: {desc}\n"
    report_msg += "=========================\n\n"
    
    for idx, row in top_10.iterrows():
        close_p = int(row['Close'])
        ratio = row[ratio_col]
        vol = int(row['Volume'])
        
        report_msg += f"📈 [{row['Name']}] ({ratio}%)\n"
        report_msg += f"   • 현재가: {close_p:,}원\n"
        
        # 15시 정찰 전용 추가 세부 지표
        if hour == 15 and minute < 30:
            report_msg += f"   • 🔍 [육안 검열 지표]\n"
            report_msg += f"     - 거래량: {vol:,}주 터짐\n"
            report_msg += f"     - 지휘관 확인 요망: 현재 차트상 윗꼬리가 길게 달렸다면 즉시 매수 포기할 것.\n\n"
        elif hour == 8:
            report_msg += f"   • 🎯 돌파진입: 아침 시가 대비 +2% 돌파 시 추격\n\n"
        else:
            report_msg += f"   • 💰 거래대금: 최상위권 유지 마감\n\n"
        
    report_msg += "=========================\n"
    report_msg += "형님, 명령하신 시간대별 전술 타격 보고를 완료했습니다."
    
    bot = telegram.Bot(token=TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text=report_msg)

if __name__ == "__main__":
    asyncio.run(main())
