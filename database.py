import sqlite3, os
from datetime import datetime
import pytz

DB_PATH = "candidates.db"

def connect(): 
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row 
    return conn

def get_now_kst():
    return datetime.now(pytz.timezone("Asia/Seoul"))

def save_candidate(run_type, code, name, score, buy_p, target1_p, target2_p, stop_p):
    conn = connect()
    now = get_now_kst()
    today = now.strftime("%Y-%m-%d")
    unique_key = f"{today}_{code}_{run_type}"
    
    try:
        conn.execute("""
            INSERT OR IGNORE INTO candidates 
            (unique_key, date, timestamp, run_type, strategy_version, score_version, code, name, score, buy_p, target1_p, target2_p, stop_p) 
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (unique_key, today, now.strftime("%H:%M:%S"), run_type, "V8.4.2", "SCORE_A", code, name, score, buy_p, target1_p, target2_p, stop_p))
        conn.commit()
    except Exception as e: print(f"DB 오류: {e}")
    finally: conn.close()
