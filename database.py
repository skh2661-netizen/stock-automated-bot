import sqlite3
from datetime import datetime
import os
import pytz

DB_PATH = "data/candidates.db"

def connect(): 
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row 
    return conn

def init_db():
    os.makedirs("data", exist_ok=True)
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
            result_status TEXT DEFAULT '대기',
            telegram_sent INTEGER DEFAULT 0
        )
    """)
    # 하위 호환 및 마이그레이션 방어 로직
    try:
        conn.execute("ALTER TABLE candidates ADD COLUMN telegram_sent INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
        
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, run_type TEXT, message TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_candidate(run_type, code, name, score, buy_p, target1_p, target2_p, stop_p):
    init_db()
    conn = connect()
    now = datetime.now(pytz.timezone("Asia/Seoul"))
    today = now.strftime("%Y-%m-%d")
    unique_key = f"{today}_{code}_{run_type}"
    try:
        conn.execute("""
            INSERT OR IGNORE INTO candidates 
            (unique_key, date, timestamp, run_type, strategy_version, score_version, code, name, score, buy_p, target1_p, target2_p, stop_p) 
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (unique_key, today, now.strftime("%H:%M:%S"), run_type, "V8.4.5", "SCORE_A", code, name, score, buy_p, target1_p, target2_p, stop_p))
        conn.commit()
    except Exception as e:
        print(f"DB 오류: {e}")
    finally:
        conn.close()

def get_today_candidates():
    if not os.path.exists(DB_PATH): 
        return []
        
    conn = connect()
    # KST 동기화 및 순수 DB 레벨 필터링 (파이썬 메모리 부하 원천 차단)
    today = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT * FROM candidates 
        WHERE date=? AND telegram_sent=0 
        ORDER BY score DESC
    """, (today,)).fetchall()
    
    conn.close()
    return [dict(row) for row in rows]

def mark_telegram_sent(unique_keys):
    if not unique_keys: 
        return
        
    conn = connect()
    # 종목 코드(code)가 아닌 고유 키(unique_key)로 단일 데이터 강제 타격
    conn.executemany("UPDATE candidates SET telegram_sent=1 WHERE unique_key=?", [(k,) for k in unique_keys])
    conn.commit()
    conn.close()

def save_log(run_type, message):
    init_db()
    conn = connect()
    now = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn.execute("INSERT INTO logs (timestamp, run_type, message) VALUES (?,?,?)", (now, str(run_type), str(message)))
        conn.commit()
    finally:
        conn.close()
