import sqlite3
from datetime import datetime

DB_PATH = "candidates.db"

def connect(): 
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row 
    return conn

def init_db():
    conn = connect()
    # 4대 추가 수정사항 반영: entry_price, OHLC 필드 추가, entry_success NULL화
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
            entry_price INTEGER DEFAULT NULL,
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
    conn = connect()
    today = datetime.now().strftime("%Y-%m-%d")
    # unique_key: 시간 제거 (중복 방지)
    unique_key = f"{today}_{code}_{run_type}"
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    try:
        conn.execute("""
            INSERT OR IGNORE INTO candidates 
            (unique_key, date, timestamp, run_type, strategy_version, code, name, score, buy_p, target1_p, target2_p, stop_p) 
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (unique_key, today, timestamp, run_type, "V8.4.2", code, name, score, buy_p, target1_p, target2_p, stop_p))
        conn.commit()
    except sqlite3.Error as e:
        print(f"DB 저장 오류: {e}")
    conn.close()
