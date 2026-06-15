import sqlite3
from datetime import datetime
import os

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
            date TEXT,
            timestamp TEXT,
            run_type TEXT,
            strategy_version TEXT,
            code TEXT,
            name TEXT,
            score INTEGER,
            buy_p INTEGER,
            target1_p INTEGER,
            target2_p INTEGER,
            stop_p INTEGER,
            entry_success INTEGER DEFAULT NULL,
            d1_high INTEGER DEFAULT NULL, d1_low INTEGER DEFAULT NULL, d1_close INTEGER DEFAULT NULL,
            d3_high INTEGER DEFAULT NULL, d3_low INTEGER DEFAULT NULL, d3_close INTEGER DEFAULT NULL,
            d5_high INTEGER DEFAULT NULL, d5_low INTEGER DEFAULT NULL, d5_close INTEGER DEFAULT NULL,
            result_status TEXT DEFAULT '대기'
        )
    """)
    conn.commit()
    conn.close()

def save_candidate(run_type, code, name, score, buy_p, target1_p, target2_p, stop_p):
    """
    scanner.py와 완벽히 호환되는 8개 인자 수신부
    """
    conn = connect()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    # run_type(OPEN/CLOSE)을 키에 포함하여 데이터 충돌 방지
    unique_key = f"{today}_{code}_{run_type}"
    
    try:
        conn.execute("""
            INSERT OR IGNORE INTO candidates 
            (unique_key, date, timestamp, run_type, strategy_version, code, name, score, buy_p, target1_p, target2_p, stop_p) 
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (unique_key, today, time_str, run_type, "V8.4.2", code, name, score, buy_p, target1_p, target2_p, stop_p))
        conn.commit()
    except sqlite3.Error as e:
        print(f"DB 저장 오류: {e}")
    finally:
        conn.close()

def get_today_candidates():
    if not os.path.exists(DB_PATH): 
        return []
    conn = connect()
    today = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute("SELECT * FROM candidates WHERE date=?", (today,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]
