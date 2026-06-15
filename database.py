Python
import sqlite3
from datetime import datetime
import os
import pytz

DB_PATH = "candidates.db"

def connect(): 
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row 
    return conn

def init_db():
    conn = connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            unique_key TEXT PRIMARY KEY,
            date TEXT, timestamp TEXT, run_type TEXT,
            strategy_version TEXT, score_version TEXT,
            code TEXT, name TEXT, score INTEGER,
            buy_p INTEGER, target1_p INTEGER, target2_p INTEGER, stop_p INTEGER,
            entry_price INTEGER DEFAULT NULL, entry_success INTEGER DEFAULT NULL,
            exit_type TEXT DEFAULT '대기',
            d1_high INTEGER, d1_low INTEGER, d1_close INTEGER,
            d3_high INTEGER, d3_low INTEGER, d3_close INTEGER,
            d5_high INTEGER, d5_low INTEGER, d5_close INTEGER,
            result_status TEXT DEFAULT '대기'
        )
    """)
    conn.commit()
    conn.close()

def save_candidate(run_type, code, name, score, buy_p, target1_p, target2_p, stop_p):
    # [수정 1] 불필요한 init_db() 호출 제거 (SQLite Lock 리스크 원천 차단)
    conn = connect()
    now = datetime.now(pytz.timezone("Asia/Seoul"))
    today = now.strftime("%Y-%m-%d")
    unique_key = f"{today}_{code}_{run_type}"
    try:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO candidates 
            (unique_key, date, timestamp, run_type, strategy_version, score_version, code, name, score, buy_p, target1_p, target2_p, stop_p) 
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (unique_key, today, now.strftime("%H:%M:%S"), run_type, "V8.4.2", "SCORE_A", code, name, score, buy_p, target1_p, target2_p, stop_p))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"DB 오류: {e}")
        return False
    finally:
        conn.close()

def get_today_candidates():
    if not os.path.exists(DB_PATH): return []
    conn = connect()
    today = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d")
    rows = conn.execute("SELECT * FROM candidates WHERE date=?", (today,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]
