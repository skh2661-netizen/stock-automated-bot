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
    # 1. 테이블 생성
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            unique_key TEXT PRIMARY KEY,
            date TEXT, timestamp TEXT, run_type TEXT,
            strategy_version TEXT, score_version TEXT,
            code TEXT, name TEXT, score INTEGER,
            buy_p INTEGER, target1_p INTEGER, target2_p INTEGER, stop_p INTEGER,
            entry_price INTEGER DEFAULT NULL, entry_success INTEGER DEFAULT NULL,
            exit_type TEXT DEFAULT '대기',
            result_status TEXT DEFAULT '대기',
            telegram_sent INTEGER DEFAULT 0
        )
    """)
    # 2. 컬럼 확인 및 추가 (마이그레이션 보강)
    try:
        conn.execute("ALTER TABLE candidates ADD COLUMN telegram_sent INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def get_today_candidates():
    if not os.path.exists(DB_PATH): return []
    conn = connect()
    # 시간대 강제 동기화 (ISOformat 사용)
    today = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d")
    
    # 3. 디버그 로그 추가 (형님 요청)
    rows = conn.execute("SELECT * FROM candidates WHERE date=? AND telegram_sent=0 ORDER BY score DESC", (today,)).fetchall()
    conn.close()
    
    # 디버깅: 조회 결과 확인
    print(f"DEBUG: 조회된 후보 건수: {len(rows)}")
    return [dict(row) for row in rows]

def mark_telegram_sent(unique_keys):
    if not unique_keys: return
    conn = connect()
    # 4. PK(unique_key) 기반 업데이트로 변경 (정확성 확보)
    conn.executemany("UPDATE candidates SET telegram_sent=1 WHERE unique_key=?", [(k,) for k in unique_keys])
    conn.commit()
    conn.close()
