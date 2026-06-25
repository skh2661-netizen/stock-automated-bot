import sqlite3
import os
from datetime import datetime
import pytz

DB_PATH = "quant_data.db"

def migrate_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    columns = {
        "prime_score": "INTEGER DEFAULT 0",
        "final_rank": "REAL DEFAULT 0",
        "conviction": "INTEGER DEFAULT 0",
        "amount_strength": "REAL DEFAULT 0",
        "rs_1d": "REAL DEFAULT 0",
        "rs_5d": "REAL DEFAULT 0",
        "rs_20d": "REAL DEFAULT 0",
        "defense": "INTEGER DEFAULT 0",
        "risk_level": "INTEGER DEFAULT 1"
    }
    try:
        c.execute("PRAGMA table_info(candidates)")
        existing_cols = [x[1] for x in c.fetchall()]
        if existing_cols:
            for col, dtype in columns.items():
                if col not in existing_cols:
                    c.execute(f"ALTER TABLE candidates ADD COLUMN {col} {dtype}")
        conn.commit()
    except Exception: pass
    finally: conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT, run_type TEXT, code TEXT, name TEXT, score INTEGER,
        buy_p INTEGER, target_1 INTEGER, target_2 INTEGER, stop_p INTEGER,
        price INTEGER, chg REAL, ma_gap REAL, prime_score INTEGER,
        final_rank REAL, conviction INTEGER, amount_strength REAL,
        rs_1d REAL, rs_5d REAL, rs_20d REAL, defense INTEGER,
        risk_level INTEGER, sent_telegram INTEGER DEFAULT 0
    )''')
    
    # HOLDING ENGINE 전용 포트폴리오 테이블
    c.execute('''CREATE TABLE IF NOT EXISTS holding_table (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        name TEXT,
        buy_price INTEGER,
        quantity INTEGER,
        weight REAL,
        buy_date TEXT,
        sector TEXT,
        theme TEXT
    )''')
    conn.commit()
    conn.close()
    migrate_db()

def save_candidate(run_type, code, name, score, buy_p, t1, t2, stop, price, chg, ma_gap, prime_score, final_rank, conviction, amount_strength, rs_1d, rs_5d, rs_20d, defense, risk_level):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    kst = pytz.timezone("Asia/Seoul")
    date_str = datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO candidates 
        (date, run_type, code, name, score, buy_p, target_1, target_2, stop_p, price, chg, ma_gap, prime_score, final_rank, conviction, amount_strength, rs_1d, rs_5d, rs_20d, defense, risk_level) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (date_str, run_type, code, name, score, buy_p, t1, t2, stop, price, chg, ma_gap, prime_score, final_rank, conviction, amount_strength, rs_1d, rs_5d, rs_20d, defense, risk_level))
    conn.commit()
    conn.close()

def mark_telegram_sent(target_codes):
    if not target_codes: return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        for code in target_codes:
            c.execute("UPDATE candidates SET sent_telegram = 1 WHERE code = ? AND sent_telegram = 0", (code,))
        conn.commit()
    except Exception: pass
    finally: conn.close()

def add_holding(code, name, buy_price, quantity, weight, sector, theme):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    kst = pytz.timezone("Asia/Seoul")
    buy_date = datetime.now(kst).strftime("%Y-%m-%d")
    try:
        c.execute('''INSERT OR REPLACE INTO holding_table 
            (code, name, buy_price, quantity, weight, buy_date, sector, theme) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (code, name, buy_price, quantity, weight, buy_date, sector, theme))
        conn.commit()
    except Exception as e: print(f"⚠️ 보유 종목 저장 실패: {e}")
    finally: conn.close()

def get_all_holdings():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT code, name, buy_price, quantity, weight, buy_date, sector, theme FROM holding_table")
    rows = c.fetchall()
    conn.close()
    return rows
