import sqlite3
import datetime
import os

DB_PATH = "candidates.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 기존 테이블 (호환성 유지용)
    c.execute('''CREATE TABLE IF NOT EXISTS candidates (
                    date TEXT, run_type TEXT, code TEXT, name TEXT, score REAL, 
                    buy_p INTEGER, target_1 INTEGER, target_2 INTEGER, stop_p INTEGER, 
                    price INTEGER, chg REAL, ma_gap REAL, prime_score REAL, 
                    prime_final REAL, conviction REAL, amount_strength REAL, 
                    rs_1d REAL, rs_5d REAL, rs_20d REAL, defense INTEGER, risk_level INTEGER)''')
    
    # 신규 Memory Layer: 상태 스냅샷 및 반복 출현 추적 테이블
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
                    created_at TEXT)''')
    conn.commit()
    conn.close()

# 최초 임포트 시 자동 테이블 생성
init_db()

def save_candidate_history(scan_datetime, run_type, code, name, rank_position, price, chg, 
                           prime_final, prime_score, conviction, rs_1d, rs_5d, rs_20d, 
                           ma_gap, amount, amount_strength, risk_level):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO candidate_history (
                    scan_datetime, run_type, code, name, rank_position, price, chg, 
                    prime_final, prime_score, conviction, rs_1d, rs_5d, rs_20d, 
                    ma_gap, amount, amount_strength, risk_level, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (scan_datetime, run_type, code, name, rank_position, price, chg, 
               prime_final, prime_score, conviction, rs_1d, rs_5d, rs_20d, 
               ma_gap, amount, amount_strength, risk_level, created_at))
    conn.commit()
    conn.close()

def save_candidate(run_type, code, name, score, buy_p, t1, t2, stop, price, chg, ma_gap, prime_score, prime_final, conviction, amount_strength, rs_1d, rs_5d, rs_20d, defense, risk_level):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO candidates (date, run_type, code, name, score, buy_p, target_1, target_2, stop_p, price, chg, ma_gap, prime_score, prime_final, conviction, amount_strength, rs_1d, rs_5d, rs_20d, defense, risk_level) 
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), run_type, code, name, score, buy_p, t1, t2, stop, price, chg, ma_gap, prime_score, prime_final, conviction, amount_strength, rs_1d, rs_5d, rs_20d, defense, risk_level))
    conn.commit()
    conn.close()
