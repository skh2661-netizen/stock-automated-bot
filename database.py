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
            telegram_sent INTEGER DEFAULT 0,
            price INTEGER DEFAULT 0,
            chg REAL DEFAULT 0.0,
            ma_gap REAL DEFAULT 0.0,
            rs REAL DEFAULT 0.0,
            five_chg REAL DEFAULT 0.0,
            kospi_chg REAL DEFAULT 0.0,
            c_vol INTEGER DEFAULT 0,
            c_rs INTEGER DEFAULT 0,
            c_heat INTEGER DEFAULT 0,
            c_amt INTEGER DEFAULT 0,
            c_shadow INTEGER DEFAULT 0,
            cond_count INTEGER DEFAULT 0
        )
    """)

    # 누락된 상세 지표 12종 컬럼 자동 보정 (마이그레이션)
    columns = [
        "telegram_sent INTEGER DEFAULT 0",
        "price INTEGER DEFAULT 0",
        "chg REAL DEFAULT 0.0",
        "ma_gap REAL DEFAULT 0.0",
        "rs REAL DEFAULT 0.0",
        "five_chg REAL DEFAULT 0.0",
        "kospi_chg REAL DEFAULT 0.0",
        "c_vol INTEGER DEFAULT 0",
        "c_rs INTEGER DEFAULT 0",
        "c_heat INTEGER DEFAULT 0",
        "c_amt INTEGER DEFAULT 0",
        "c_shadow INTEGER DEFAULT 0",
        "cond_count INTEGER DEFAULT 0"
    ]
    existing = [row["name"] for row in conn.execute("PRAGMA table_info(candidates)")]

    for col in columns:
        col_name = col.split()[0]
        if col_name not in existing:
            conn.execute(f"ALTER TABLE candidates ADD COLUMN {col}")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, run_type TEXT, message TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_candidate(run_type, code, name, score, buy_p, target1_p, target2_p, stop_p, price, chg, ma_gap, rs, five_chg, kospi_chg, c_vol, c_rs, c_heat, c_amt, c_shadow, cond_count):
    init_db()
    conn = connect()
    now = datetime.now(pytz.timezone("Asia/Seoul"))
    today = now.strftime("%Y-%m-%d")
    unique_key = f"{today}_{code}_{run_type}"
    try:
        conn.execute("""
            INSERT OR IGNORE INTO candidates 
            (unique_key, date, timestamp, run_type, strategy_version, score_version, code, name, score, buy_p, target1_p, target2_p, stop_p, price, chg, ma_gap, rs, five_chg, kospi_chg, c_vol, c_rs, c_heat, c_amt, c_shadow, cond_count) 
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (unique_key, today, now.strftime("%H:%M:%S"), run_type, "V8.4.5", "SCORE_A", code, name, score, buy_p, target1_p, target2_p, stop_p, price, chg, ma_gap, rs, five_chg, kospi_chg, int(c_vol), int(c_rs), int(c_heat), int(c_amt), int(c_shadow), cond_count))
        conn.commit()
    except Exception as e:
        print(f"DB 오류: {e}")
    finally:
        conn.close()

def get_today_candidates():
    if not os.path.exists(DB_PATH): 
        return []
        
    conn = connect()
    today = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT * FROM candidates 
        WHERE date=? AND telegram_sent=0 
        ORDER BY score DESC
    """, (today,)).fetchall()
    conn.close()
    
    # DB의 target1_p 키를 텔레그램이 요구하는 target_1 키로 파이썬 단에서 자동 변환 보정
    results = []
    for row in rows:
        r_dict = dict(row)
        r_dict['target_1'] = r_dict.get('target1_p', 0)
        r_dict['target_2'] = r_dict.get('target2_p', 0)
        # SQLite는 Boolean을 0/1로 저장하므로 bool 연산자로 원상 복구
        r_dict['c_vol'] = bool(r_dict.get('c_vol', 0))
        r_dict['c_rs'] = bool(r_dict.get('c_rs', 0))
        r_dict['c_heat'] = bool(r_dict.get('c_heat', 0))
        r_dict['c_amt'] = bool(r_dict.get('c_amt', 0))
        r_dict['c_shadow'] = bool(r_dict.get('c_shadow', 0))
        results.append(r_dict)
        
    return results

def mark_telegram_sent(unique_keys):
    if not unique_keys: 
        return
    conn = connect()
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
