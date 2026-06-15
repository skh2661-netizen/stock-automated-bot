import sqlite3
from datetime import datetime
import os

DB_PATH = "candidates.db"

def connect(): 
    conn = sqlite3.connect(DB_PATH, timeout=30)
    # 데이터를 딕셔너리 형태로 반환하도록 설정 (validator.py 호환성 확보)
    conn.row_factory = sqlite3.Row 
    return conn

def init_db():
    conn = connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY, 
            date TEXT, 
            code TEXT, 
            name TEXT, 
            score INTEGER, 
            price INTEGER, 
            market_mode INTEGER,
            rs REAL,
            ma_gap REAL,
            buy_p INTEGER,
            target_p INTEGER,
            stop_p INTEGER,
            result_5d REAL DEFAULT NULL
        )
    """)
    conn.commit()
    conn.close()

def save_candidate(code, name, score, price, mode, rs, ma_gap, buy_p, target_p, stop_p):
    conn = connect()
    conn.execute("""
        INSERT INTO candidates 
        (date, code, name, score, price, market_mode, rs, ma_gap, buy_p, target_p, stop_p) 
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (datetime.now().strftime("%Y-%m-%d"), code, name, score, price, mode, rs, ma_gap, buy_p, target_p, stop_p))
    conn.commit()
    conn.close()

def get_today_candidates():
    """오늘 스캔된 종목들을 불러와 15:00 생존 검사(validator)에 전달"""
    if not os.path.exists(DB_PATH): 
        return []
        
    conn = connect()
    today = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute("SELECT * FROM candidates WHERE date=?", (today,)).fetchall()
    conn.close()
    
    # DB row 객체를 일반 딕셔너리로 변환하여 리턴
    return [dict(row) for row in rows]
