import os
import sqlite3
import pytz
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from database import DB_PATH, get_signal_persistence

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

def fetch_latest_candidate_data(keyword):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        if keyword.isdigit() and len(keyword) == 6:
            query_str = "code = ?"
        else:
            query_str = "name = ?"
            
        c.execute(f'''
            SELECT code, name, price, chg, prime_final, prime_score, conviction, 
                   rs_20d, ma_gap, risk_level, scan_datetime 
            FROM candidate_history 
            WHERE {query_str} 
            ORDER BY scan_datetime DESC LIMIT 1
        ''', (keyword,))
        return c.fetchone()
    except Exception as e:
        print(f"조회 에러: {e}")
        return None
    finally:
        conn.close()

def fetch_pattern_stats(code):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""
            SELECT 
                COUNT(*), 
                AVG(after_5d_chg), 
                AVG(max_gain), 
                AVG(max_drawdown)
            FROM signal_outcome 
            WHERE code = ? AND evaluation_status = 'COMPLETED'
        """, (code,))
        row = c.fetchone()
        
        if row and row[0] > 0:
            total = row[0]
            avg5 = row[1]
            avg_gain = row[2]
            avg_dd = row[3]
            
            c.execute("""
                SELECT COUNT(*) 
                FROM signal_outcome 
                WHERE code = ? AND evaluation_status = 'COMPLETED' AND after_5d_chg > 0
            """, (code,))
            wins = c.fetchone()[0]
            
            return (round(wins/total*100, 1), round(avg5, 2), round(avg_gain, 2), round(avg_dd, 2), total, 1)
    except Exception as e:
        print(f"통계 집계 에러: {e}")
    finally:
        conn.close()
    return None

async def detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ 종목명이나 코드를 입력하십시오. (예: /detail 금호타이어)")
        return
        
    keyword = context.args[0]
    data = fetch_latest_candidate_data(keyword)
    
    if not data:
        await update.message.reply_text(f"❌ 최근 60일 내 [{keyword}]에 대한 스캔 기록이 없습니다.")
        return
        
    (code, name, price, chg, p_final, p_score, conv, rs20, ma_gap, risk, scan_dt) = data
    memory = get_signal_persistence(code)
    
    msg = f"🔎 <b>{name} ({code}) 상세 분석</b>\n"
    msg += f"마지막 포착: {scan_dt}\n\n"
    
    msg += f"📊 <b>현재 상태 팩트:</b>\n"
    msg += f"현재가: {price:,}원 ({chg}%)\n"
    msg += f"Prime: {p_score} | Final: {p_final}\n"
    msg += f"Conviction: {conv} | RS20D: {'+' if rs20>0 else ''}{rs20}%\n\n"
    
    msg += f"🧠 <b>기억 분석 (최근 5일):</b>\n"
    msg += f"출현: {memory['today_count']}회 (오늘) / 총 {memory['five_days_days']}일\n"
    msg += f"리더 선정: {memory['leader_count']}회 | 최고 순위: {memory['max_rank']}위\n\n"
    
    pattern = fetch_pattern_stats(code)
    msg += f"🤖 <b>과거 본 종목 패턴 성적표:</b>\n"
    
    if pattern and pattern[4] > 0:
        (win_rate, avg_5d, max_gain, mdd, matches, search_lvl) = pattern
        msg += f"완료된 추적 표본: {matches}회\n"
        msg += f"역사적 승률: {win_rate}%\n"
        msg += f"평균 5일 수익: {'+' if avg_5d>0 else ''}{avg_5d}%\n"
        msg += f"평균 최대 상승폭: {'+' if max_gain>0 else ''}{max_gain}%\n"
        msg += f"평균 최대 낙폭: {mdd}%\n"
    else:
        msg += "⚠️ 본 종목의 완료(COMPLETED)된 T+5 성적표 표본이 부족합니다.\n"

    await update.message.reply_text(msg, parse_mode='HTML')

if __name__ == '__main__':
    if not TELEGRAM_TOKEN:
        print("⚠️ 환경 변수에 TELEGRAM_TOKEN이 설정되지 않았습니다.")
    else:
        print("🤖 [STEP 4] Telegram Command 리스너 가동 중...")
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler("detail", detail_command))
        app.run_polling()
