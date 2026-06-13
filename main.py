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

    # [1. 얌체 정찰] 1초 만에 가볍게 전체 데이터 스캔
    krx_df = fdr.StockListing('KRX')
    ratio_col = 'ChangesRatio' if 'ChangesRatio' in krx_df.columns else 'Change'
    krx_df['Amount'] = krx_df['Close'] * krx_df['Volume']
    
    safe_target = ~krx_df['Name'].str.contains('스팩|ETF|ETN|우$|우[A-Z]$|제[0-9]+호', regex=True)
    krx_df = krx_df[safe_target].copy()

    # [2. 썩은 사과 버리기] 고점 대비 7% 이하로 밀린(설거지 아닌) 종목만 살림
    krx_df['Upper_Shadow'] = (krx_df['High'] - krx_df['Close']) / krx_df['Close'] * 100
    cond = (krx_df['Close'] >= 2000) & (krx_df[ratio_col] >= 5.0) & (krx_df[ratio_col] <= 25.0) & \
           (krx_df['Volume'] >= 1000000) & (krx_df['Upper_Shadow'] <= 7.0)
           
    filtered_df = krx_df[cond].sort_values(by='Amount', ascending=False)

    # [3. 편식 방지] 업종(Sector) 쏠림 방지. 같은 업종은 최대 2개까지만 바구니에 담음
    final_top_10 = []
    sector_counts = {}
    for idx, row in filtered_df.iterrows():
        sector = str(row.get('Sector', '기타'))
        if sector == 'nan' or sector == 'None': sector = '기타 테마'
        
        count = sector_counts.get(sector, 0)
        if count < 2:
            final_top_10.append(row)
            sector_counts[sector] = count + 1
        if len(final_top_10) == 10:
            break
            
    top_10_df = pd.DataFrame(final_top_10)

    # 시간에 따른 보고 포맷
    if hour == 8:
        title_mode = "☀️ [08:50 시초가 돌파 타격 지시]"
    elif hour == 15 and minute < 30:
        title_mode = "⚠️ [15:00 종가 베팅 정찰 (서버 우회 및 육안 검열)]"
    else:
        title_mode = "🌙 [15:40 당일 완결 복기 리포트]"

    report_msg = f"{title_mode}\n"
    report_msg += f"기준: {now.strftime('%m/%d %H:%M')}\n"
    report_msg += "=========================\n\n"
    
    if top_10_df.empty:
        report_msg += "조건을 만족하는 방어 대상 종목이 없습니다.\n"
    else:
        for idx, row in top_10_df.iterrows():
            close_p = int(row['Close'])
            ratio = round(row[ratio_col], 2)
            upper_s = round(row['Upper_Shadow'], 1)
            sector_name = str(row.get('Sector', '기타 테마'))
            
            # [4. 자동 브레이크] 종목의 위아래 흔들림(변동성)을 계산하여 시드머니 투입 비중 조절
            volatility = (row['High'] - row['Low']) / row['Close'] * 100
            if volatility >= 15.0:
                weight = "3% (초고위험)"
            elif volatility >= 10.0:
                weight = "5% (고위험)"
            else:
                weight = "10% (표준 안전)"
            
            report_msg += f"📈 [{row['Name']}] ({ratio}%) - {sector_name}\n"
            report_msg += f"   • 현재가: {close_p:,}원 (고점대비 -{upper_s}% 밀림)\n"
            report_msg += f"   • 🛡️ 진입비중: 시드머니의 {weight}\n\n"
        
    report_msg += "=========================\n"
    report_msg += "형님, V8 철벽 방어 엔진 기반 전술 보고를 완료했습니다."
    
    bot = telegram.Bot(token=TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text=report_msg)

if __name__ == "__main__":
    asyncio.run(main())
