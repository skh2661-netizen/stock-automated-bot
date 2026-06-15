import sqlite3
from datetime import datetime
DB_PATH = "data/candidates.db"
def connect(): return sqlite3.connect(DB_PATH, timeout=30)
def init_db():
    conn = connect()
    conn.execute("CREATE TABLE IF NOT EXISTS candidates (id INTEGER PRIMARY KEY, date TEXT, code TEXT, name TEXT, score INTEGER, price INTEGER, market_mode INTEGER)")
    conn.commit()
    conn.close()
def save_candidate(code, name, score, price, mode):
    conn = connect()
    conn.execute("INSERT INTO candidates (date, code, name, score, price, market_mode) VALUES (?,?,?,?,?,?)", (datetime.now().strftime("%Y-%m-%d"), code, name, score, price, mode))
    conn.commit()
    conn.close()
def get_today_candidates():
    conn = connect()
    data = conn.execute("SELECT * FROM candidates WHERE date=?", (datetime.now().strftime("%Y-%m-%d"),)).fetchall()
    conn.close()
    return data
