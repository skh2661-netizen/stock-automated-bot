import sqlite3
import os
from datetime import datetime, timedelta
import pytz

DB_PATH = "quant_data.db"

def migrate_db():
    tables = {
        "candidates": {"engine_version": "TEXT DEFAULT 'V8.8.26.1'"},
        "candidate_history": {"engine_version": "TEXT DEFAULT 'V8.8.26.1'"},
        "signal_outcome": {"market_regime": "TEXT DEFAULT 'NORMAL'"}
    }
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for table, columns in tables.items():
        try:
            c.execute(f"PRAGMA table_info({table})")
            existing = [row[1] for row in c.fetchall()]
            if existing:
                for col, dtype in columns.items():
                    if col not in existing:
                        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
        except Exception: pass
    conn.commit()
    conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS candidates (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, run_type TEXT, code TEXT, name TEXT, score INTEGER, buy_p INTEGER, target_1 INTEGER, target_2 INTEGER, stop_p INTEGER, price INTEGER, chg REAL, ma_gap REAL, prime_score INTEGER, final_rank REAL, conviction INTEGER, amount_strength REAL, rs_1d REAL, rs_5d REAL, rs_20d REAL, defense INTEGER, risk_level INTEGER, sent_telegram INTEGER DEFAULT 0, engine_version TEXT DEFAULT 'V8.8.26.1')''')
    c.execute('''CREATE TABLE IF NOT EXISTS candidate_history (id INTEGER PRIMARY KEY AUTOINCREMENT, scan_datetime TEXT, run_type TEXT, code TEXT, name TEXT, rank_position INTEGER, price INTEGER, chg REAL, prime_final REAL, prime_score REAL, conviction REAL, rs_1d REAL, rs_5d REAL, rs_20d REAL, ma_gap REAL, amount INTEGER, amount_strength REAL, risk_level INTEGER, is_leader INTEGER DEFAULT 0, created_at TEXT, engine_version TEXT DEFAULT 'V8.8.26.1')''')
    c.execute('''CREATE TABLE IF NOT EXISTS signal_outcome (id INTEGER PRIMARY KEY AUTOINCREMENT, history_id INTEGER, code TEXT, name TEXT, signal_date TEXT, price_at_signal INTEGER, after_1d_chg REAL DEFAULT 0.0, after_3d_chg REAL DEFAULT 0.0, after_5d_chg REAL DEFAULT 0.0, max_gain REAL DEFAULT 0.0, max_drawdown REAL DEFAULT 0.0, evaluation_status TEXT DEFAULT 'PENDING', market_regime TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS top10_tracking (id INTEGER PRIMARY KEY AUTOINCREMENT, scan_datetime TEXT, code TEXT, name TEXT, rank_position INTEGER, final_score REAL, risk_level INTEGER)''')
    conn.commit()
    conn.close()
    migrate_db()

init_db()

def debug_top10(code):
    safe_code = str(code).zfill(6)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT scan_datetime, code, name, rank_position FROM top10_tracking WHERE code=? ORDER BY id DESC LIMIT 5""", (safe_code,))
    rows = c.fetchall()
    if not rows:
        print(f"⚠️ [TOP10 DEBUG EMPTY] {safe_code} 검색 결과 없음")
    else:
        for r in rows:
            print(f"🔍 [TOP10 DEBUG FOUND]: {r}")
    conn.close()

def debug_history(code):
    safe_code = str(code).zfill(6)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT id, scan_datetime, code, name, rank_position FROM candidate_history WHERE code=? ORDER BY id DESC LIMIT 5""", (safe_code,))
    rows = c.fetchall()
    for r in rows:
        print(f"🔍 [DEBUG HISTORY]: {r}")
    conn.close()

def get_signal_persistence(code):
    safe_code = str(code).zfill(6)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    kst_now = datetime.now(pytz.timezone("Asia/Seoul"))
    five_days_ago = (kst_now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    today = kst_now.strftime("%Y-%m-%d")
    
    c.execute("SELECT COUNT(*), COUNT(DISTINCT SUBSTR(scan_datetime, 1, 10)), MIN(rank_position), SUM(is_leader), AVG(prime_final), AVG(rank_position) FROM candidate_history WHERE code = ? AND datetime(scan_datetime) >= datetime(?)", (safe_code, five_days_ago))
    row = c.fetchone()
    
    c.execute("SELECT COUNT(*) FROM candidate_history WHERE code = ? AND scan_datetime LIKE ?", (safe_code, f"{today}%"))
    today_count = c.fetchone()[0]
    conn.close()
    
    return {
        "today_count": today_count,
        "five_days_days": row[1] if row and row[1] else 0,
        "max_rank": row[2] if row and row[2] else 99,
        "leader_count": row[3] if row and row[3] else 0,
        "avg_final": round(row[4], 1) if row and row[4] else 0.0,
        "avg_rank": round(row[5], 1) if row and row[5] else 0.0
    }

def get_top10_stability(code):
    safe_code = str(code).zfill(6)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    kst_now = datetime.now(pytz.timezone("Asia/Seoul"))
    five_days_ago = (kst_now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute("""SELECT COUNT(*), COUNT(DISTINCT SUBSTR(scan_datetime, 1, 10)), AVG(rank_position) FROM top10_tracking WHERE code=? AND datetime(scan_datetime) >= datetime(?)""", (safe_code, five_days_ago))
    row = c.fetchone()
    conn.close()
    
    return {
        "top10_count": row[0] if row and row[0] else 0,
        "days": row[1] if row and row[1] else 0,
        "avg_rank": round(row[2], 1) if row and row[2] else 0.0
    }

def save_top10_tracking(scan_datetime, code, name, rank_position, final_score, risk_level):
    safe_code = str(code).zfill(6)
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''INSERT INTO top10_tracking (scan_datetime, code, name, rank_position, final_score, risk_level) VALUES (?, ?, ?, ?, ?, ?)''', (scan_datetime, safe_code, name, rank_position, final_score, risk_level))
        conn.commit()
        print(f"✅ [TOP10 SAVE SUCCESS] {safe_code} {name} rank={rank_position} time={scan_datetime}")
    except Exception as e:
        print(f"❌ [TOP10 SAVE ERROR] {safe_code} {name} : {e}")
    finally:
        conn.close()

def save_candidate_history(scan_datetime, run_type, code, name, rank_position, price, chg, prime_final, prime_score, conviction, rs_1d, rs_5d, rs_20d, ma_gap, amount, amount_strength, risk_level, is_leader=0):
    safe_code = str(code).zfill(6)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO candidate_history (scan_datetime, run_type, code, name, rank_position, price, chg, prime_final, prime_score, conviction, rs_1d, rs_5d, rs_20d, ma_gap, amount, amount_strength, risk_level, is_leader, created_at, engine_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'V8.8.26.1')''',
              (scan_datetime, run_type, safe_code, name, rank_position, price, chg, prime_final, prime_score, conviction, rs_1d, rs_5d, rs_20d, ma_gap, amount, amount_strength, risk_level, is_leader, datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    inserted_id = c.lastrowid
    conn.close()
    return inserted_id

def register_signal_outcome(history_id, code, name, price_at_signal, market_regime):
    if not history_id: return
    safe_code = str(code).zfill(6)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO signal_outcome (history_id, code, name, signal_date, price_at_signal, evaluation_status, market_regime) VALUES (?, ?, ?, ?, ?, 'PENDING', ?)", 
              (history_id, safe_code, name, datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d"), price_at_signal, market_regime))
    conn.commit()
    conn.close()

def get_signal_quality(market_regime, rs_20d, conviction):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for m in [{"rs": 15.0, "conv": 10}, {"rs": 30.0, "conv": 20}, {"rs": 50.0, "conv": 40}]:
        c.execute('''SELECT after_5d_chg, max_gain, max_drawdown FROM signal_outcome o JOIN candidate_history h ON o.history_id = h.id 
                     WHERE o.evaluation_status = 'COMPLETED' AND o.market_regime = ? AND h.rs_20d BETWEEN ? AND ? AND h.conviction BETWEEN ? AND ?''',
                  (market_regime, rs_20d-m["rs"], rs_20d+m["rs"], conviction-m["conv"], conviction+m["conv"]))
        rows = c.fetchall()
        if len(rows) >= 5:
            win_rate = round(len([r for r in rows if r[0] > 0])/len(rows)*100, 1)
            conn.close()
            return {"win_rate": win_rate, "match_count": len(rows), "is_valid": True}
    conn.close()
    return {"win_rate": 0.0, "match_count": 0, "is_valid": False}
