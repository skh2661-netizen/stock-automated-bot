import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from database import DB_PATH, get_signal_persistence

def fetch_pattern_stats(code):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), AVG(after_5d_chg), AVG(max_gain), AVG(max_drawdown) FROM signal_outcome WHERE code=? AND evaluation_status='COMPLETED'", (code,))
    row = c.fetchone()
    if row and row[0] >= 5:
        wins = c.execute("SELECT COUNT(*) FROM signal_outcome WHERE code=? AND after_5d_chg > 0", (code,)).fetchone()[0]
        return (round(wins/row[0]*100,1), round(row[1],2), round(row[2],2), round(row[3],2), row[0])
    return None

async def detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = context.args[0]
    mem = get_signal_persistence(code)
    pat = fetch_pattern_stats(code)
    msg = f"🔎 <b>{code} 분석</b>\n" + f"출현: {mem['today_count']}회\n"
    if pat:
        msg += f"승률: {pat[0]}% ({pat[4]}개 표본)\n"
    else:
        msg += "⚠️ 통계 표본 부족\n"
    await update.message.reply_text(msg, parse_mode='HTML')
