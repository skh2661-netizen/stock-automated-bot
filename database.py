import sqlite3
import os
from datetime import datetime
import pytz

DB_PATH = "quant_data.db"

def migrate_db():
    # [수정 1] 기존 DB 파괴 없이 신규 컬럼 9개를 안전하게 동적 추가하는 엔진
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
        
        # 기존 테이블이 존재할 때만 ALTER TABLE 실행
        if existing_cols:
            for col, dtype in columns.items():
                if col not in existing_cols:
                    print(f"🔧 [DB MIGRATION] candidates 테이블에 {col} 컬럼을 추가합니다.")
                    c.execute(f"ALTER TABLE candidates ADD COLUMN {col} {dtype}")
        conn.commit()
    except Exception as e:
        print(f"⚠️ [DB MIGRATION 경고] 컬럼 추가 중 예외 발생 (최초 생성 시 무시 가능): {e}")
    finally:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        run_type TEXT,
        code TEXT,
        name TEXT,
        score INTEGER,
        buy_p INTEGER,
        target_1 INTEGER,
        target_2 INTEGER,
        stop_p INTEGER,
        price INTEGER,
        chg REAL,
        ma_gap REAL,
        prime_score INTEGER,
        final_rank REAL,
        conviction INTEGER,
        amount_strength REAL,
        rs_1d REAL,
        rs_5d REAL,
        rs_20d REAL,
        defense INTEGER,
        risk_level INTEGER,
        sent_telegram INTEGER DEFAULT 0
    )''')
    conn.commit()
    conn.close()
    
    # 테이블 생성 후 반드시 마이그레이션 연동
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
    # [수정 3] 키 매핑 붕괴를 예방하기 위해 코드 리스트 직접 매칭 방식으로 안전하게 교정
    if not target_codes: return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        for code in target_codes:
            c.execute("UPDATE candidates SET sent_telegram = 1 WHERE code = ? AND sent_telegram = 0", (code,))
        conn.commit()
    except Exception as e:
        print(f"⚠️ 텔레그램 마킹 실패 로그: {e}")
    finally:
        conn.close()
