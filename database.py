import sqlite3
import os
from datetime import datetime, timedelta
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

    c.execute('''CREATE TABLE IF NOT EXISTS candidate_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_datetime TEXT,
        run_type TEXT,
        code TEXT,
        name TEXT,
        rank_position INTEGER,
        price INTEGER,
        chg REAL,
        prime_final REAL,
        prime_score REAL,
        conviction REAL,
        rs_1d REAL,
        rs_5d REAL,
        rs_20d REAL,
        ma_gap REAL,
        amount INTEGER,
        amount_strength REAL,
        risk_level INTEGER,
        is_leader INTEGER DEFAULT 0,
        created_at TEXT
    )''')
    
    conn.commit()
    conn.close()
    migrate_db()

init_db()

def save_candidate_history(scan_datetime, run_type, code, name, rank_position, price, chg, 
                           prime_final, prime_score, conviction, rs_1d, rs_5d, rs_20d, 
                           ma_gap, amount, amount_strength, risk_level, is_leader=0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    kst = pytz.timezone("Asia/Seoul")
    created_at = datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")
    try:
        c.execute('''INSERT INTO candidate_history (
                        scan_datetime, run_type, code, name, rank_position, price, chg, 
                        prime_final, prime_score, conviction, rs_1d, rs_5d, rs_20d, 
                        ma_gap, amount, amount_strength, risk_level, is_leader, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (scan_datetime, run_type, code, name, rank_position, price, chg, 
                   prime_final, prime_score, conviction, rs_1d, rs_5d, rs_20d, 
                   ma_gap, amount, amount_strength, risk_level, is_leader, created_at))
        conn.commit()
    except Exception as e:
        print(f"⚠️ 히스토리 저장 실패: {e}")
    finally:
        conn.close()

# [신규 추가] 뇌와 입이 기억을 호출할 수 있는 '신호 지속성 분석 엔진'
def get_signal_persistence(code):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    kst = pytz.timezone("Asia/Seoul")
    today_str = datetime.now(kst).strftime("%Y-%m-%d")
    five_days_ago = (datetime.now(kst) - timedelta(days=5)).strftime("%Y-%m-%d")
    
    analysis = {"today_count": 0, "five_days_days": 0, "max_rank": 99, "leader_count": 0, "avg_final": 0.0}
    try:
        # 1. 오늘 출현 횟수 계산
        c.execute("SELECT COUNT(*) FROM candidate_history WHERE code = ? AND scan_datetime LIKE ?", (code, f"{today_str}%"))
        analysis["today_count"] = c.fetchone()[0]
        
        # 2. 최근 5일간 출현한 '서로 다른 날짜'의 수 계산
        c.execute("SELECT COUNT(DISTINCT SUBSTR(scan_datetime, 1, 10)) FROM candidate_history WHERE code = ? AND scan_datetime >= ?", (code, five_days_ago))
        analysis["five_days_days"] = c.fetchone()[0]
        
        # 3. 최고 순위 및 리더 등극 횟수, 평균 점수 분석
        c.execute("SELECT MIN(rank_position), SUM(is_leader), AVG(prime_final) FROM candidate_history WHERE code = ? AND scan_datetime >= ?", (code, five_days_ago))
        row = c.fetchone()
        if row and row[0] is not None:
            analysis["max_rank"] = row[0]
            analysis["leader_count"] = row[1] if row[1] else 0
            analysis["avg_final"] = round(row[2], 1) if row[2] else 0.0
    except Exception as e:
        print(f"⚠️ 기억 레이어 조회 실패: {e}")
    finally:
        conn.close()
    return analysis

def save_candidate(run_type, code, name, score, buy_p, t1, t2, stop, price, chg, ma_gap, prime_score, final_rank, conviction, amount_strength, rs_1d, rs_5d, rs_20d, defense, risk_level):
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT code, name, buy_price, quantity, weight, buy_date, sector, theme FROM holding_table")
    rows = c.fetchall()
    conn.close()
    return rows
