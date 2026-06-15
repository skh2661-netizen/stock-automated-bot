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
    # 1. 후보 적재용 테이블
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
    # 2. 시스템 운영 로그 테이블 추가
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            run_type TEXT,
            message TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_candidate(run_type, code, name, score, buy_p, target1_p, target2_p, stop_p):
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

# [추가] main.py 에러 해결을 위한 가변형 시스템 로그 저장 함수
def save_log(*args):
    conn = connect()
    now = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
    
    # main.py에서 넘기는 인자 수에 상관없이 유연하게 대처 (에러 원천 방어)
    try:
        if len(args) == 1:
            run_type, message = "SYSTEM", str(args[0])
        elif len(args) >= 2:
            run_type, message = str(args[0]), str(args[1])
        else:
            return

        conn.execute("INSERT INTO logs (timestamp, run_type, message) VALUES (?,?,?)", (now, run_type, message))
        conn.commit()
    except Exception as e:
        print(f"로그 저장 오류: {e}")
    finally:
        conn.close()
