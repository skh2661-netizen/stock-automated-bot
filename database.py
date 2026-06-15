import sqlite3
from datetime import datetime
import os

DB_PATH = "candidates.db"

def connect(): 
    return sqlite3.connect(DB_PATH, timeout=30)

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
