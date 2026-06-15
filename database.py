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
    # 후보 테이블
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
    # 시스템 로그 테이블 신설
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_log (
            id INTEGER PRIMARY KEY,
            timestamp TEXT, event TEXT, status TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_log(event, status):
    conn = connect()
    conn.execute("INSERT INTO system_log (timestamp, event, status) VALUES (?,?,?)", 
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event, status))
    conn.commit()
    conn.close()

def save_candidate(run_type, code, name, score, buy_p, target1_p, target2_p, stop_p):
    conn = connect()
    now = datetime.now()
    # 시간까지 반영하여 같은 종목의 다른 세션 데이터 보호
    unique_key = f"{now.strftime('%Y-%m-%d')}_{code}_{run_type}_{now.strftime('%H%M')}"
    try:
        conn.execute("""
            INSERT OR IGNORE INTO candidates 
            (unique_key, date, timestamp, run_type, strategy_version, score_version, code, name, score, buy_p, target1_p, target2_p, stop_p) 
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (unique_key, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), run_type, "V8.4.2", "SCORE_A", code, name, score, buy_p, target1_p, target2_p, stop_p))
        conn.commit()
    except Exception as e: print(f"DB 오류: {e}")
    finally: conn.close()
