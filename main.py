import FinanceDataReader as fdr
import pandas as pd
import datetime
import telegram
import asyncio
import os

# GitHub Secrets 금고에서 마스터키 안전하게 디코딩
TOKEN = os.environ['TELEGRAM_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

async def main():
    now = datetime.datetime.now()
    weekday = now.weekday()
    
    # [실전 방어 연산] 주말 가동 2중 차단막 복구
    if weekday >= 5:
        print("⚠️ 주말 휴장일입니다. 실전 연산을 중단합니다.")
        return

    print("🚀 [실전 가동] 단타 특화 분석 엔진 점화 완료.")
    
    # 1. 글로벌 거시 경제 시황 수집
    try:
        kospi_df = fdr.DataReader('KS11', (now - datetime.timedelta(days=5)).strftime('%Y-%m-%d'))
        kosdaq_df = fdr.DataReader('KQ11', (now - datetime.timedelta(days=5)).strftime('%Y-%m-%d'))
        ndx_df = fdr.DataReader('IXIC', (now - datetime.timedelta(days=5)).strftime('%Y-%m-%d'))
        
        k_change = round(kospi_df['Change'].iloc[-1] * 100, 2)
        kq_change = round(kosdaq_df['Change'].iloc[-1] * 100, 2)
        n_change = round(ndx_df['Change'].iloc[-1] * 100, 2)
    except:
        k_change, kq_change, n_change = 0.0, 0.0, 0.0

    # 2. 한국거래소(KRX) 전 종목 수집 및 거래대금 산출
    krx_df = fdr.StockListing('KRX')
    ratio_col = 'ChangesRatio' if 'ChangesRatio' in krx_df.columns else ('ChagesRatio' if 'ChagesRatio' in krx_df.columns else 'Change')
    krx_df['Amount'] = krx_df['Close'] * krx_df['Volume']
    
    # 3. [위험군 필터링] 스팩, ETF, ETN, 우선주 원천 제거
    safe_target = ~krx_df['Name'].str.contains('스팩|ETF|ETN|우$|우[A-Z]$|제[0-9]+호', regex=True)
    krx_df = krx_df[safe_target].copy()

    # 4. [단타 수급 조건] 종가 2,000원 이상, 당일 상승률 5%~25%, 거래량 100만 주 이상
    cond_price = krx_df['Close'] >= 2000
    cond_ratio = (krx_df[ratio_col] >= 5.0) & (krx_df[ratio_col] <= 25.0)
    cond_vol = krx_df['Volume'] >= 1000000
    
    filtered_df = krx_df[cond_price & cond_ratio & cond_vol].copy()
    top_10 = filtered_df.sort_values(by='Amount', ascending=False).head(10)
    
    # 5. 모바일 전용 초정밀 리포트 작성 (실전용 포맷)
    report_msg = f"🎯 [실전 단타 타점 보고서 - {now.strftime('%m/%d')}]\n"
    report_msg += "=========================\n"
    report_msg += "🌐 [글로벌 & 국내 시황]\n"
    report_msg += f"🇺🇸 나스닥(전일): {n_change}%\n"
    report_msg += f"🇰🇷 코스피(당일): {k_change}%\n"
    report_msg += f"🇰🇷 코스닥(당일): {kq_change}%\n"
    report_msg += "=========================\n\n"
    
    for idx, row in top_10.iterrows():
        close_p = int(row['Close'])
        ratio = row[ratio_col]
        vol = int(row['Volume'])
        
        # 단타용 타이트한 타점 공식
        estimated_atr = close_p * (ratio / 100) * 0.3
        buy_target = int(close_p * 0.985)        
        profit_target = int(close_p + estimated_atr) 
        loss_cut = int(close_p * 0.97)           
        
        star_rating = "★★★"
        if ratio >= 15.0 and vol >= 3000000: star_rating = "★★★★★ (강력)"
        elif ratio >= 10.0 or vol >= 2000000: star_rating = "★★★★ (우수)"
            
        report_msg += f"📈 [{row['Name']}] 매력도: {star_rating}\n"
        report_msg += f"   • 현재종가: {close_p:,}원 ({ratio}%)\n"
        report_msg += f"   • 🛒 단타매수: {buy_target:,}원 부근\n"
        report_msg += f"   • 🛑 칼손절선: {loss_cut:,}원 엄수\n"
        report_msg += f"   • 🎯 1차익절: {profit_target:,}원\n\n"
        
    report_msg += "=========================\n"
    report_msg += "형님, 금일장 타점 보고를 완료했습니다."
    
    bot = telegram.Bot(token=TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text=report_msg)

if __name__ == "__main__":
    asyncio.run(main())
