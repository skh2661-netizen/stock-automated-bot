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
    
    # 1. 기존 CANDIDATES 테이블 (레거시 호환성 유지)
    c.execute('''CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT, run_type TEXT, code TEXT, name TEXT, score INTEGER,
        buy_p INTEGER, target_1 INTEGER, target_2 INTEGER, stop_p INTEGER,
        price INTEGER, chg REAL, ma_gap REAL, prime_score INTEGER,
        final_rank REAL, conviction INTEGER, amount_strength REAL,
        rs_1d REAL, rs_5d REAL, rs_20d REAL, defense INTEGER,
        risk_level INTEGER, sent_telegram INTEGER DEFAULT 0
    )''')
    
    # 2. 기존 HOLDING ENGINE 전용 포트폴리오 테이블
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

    # 3. MEMORY LAYER단계 1: 상태 스냅샷 및 반복 출현 추적 테이블
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
    
    # 4. [신규 추가] MEMORY LAYER단계 2: 과거 신호의 미래 수익률 추적 성적표 테이블
    c.execute('''CREATE TABLE IF NOT EXISTS signal_outcome (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        history_id INTEGER,          
        code TEXT,
        name TEXT,
        signal_date TEXT,            
        price_at_signal INTEGER,     
        after_1d_chg REAL DEFAULT 0.0,           
        after_3d_chg REAL DEFAULT 0.0,           
        after_5d_chg REAL DEFAULT 0.0,           
        max_gain REAL DEFAULT 0.0,               
        max_drawdown REAL DEFAULT 0.0,           
        evaluation_status TEXT DEFAULT 'PENDING' 
    )''')
    
    conn.commit()
    conn.close()
    migrate_db()

# 최초 임포트 시 자동 테이블 생성 및 마이그레이션 실행
init_db()


# ==========================================
# MEMORY LAYER 1단계: 관측기록 데이터 핸들링
# ==========================================
def save_candidate_history(scan_datetime, run_type, code, name, rank_position, price, chg, 
                           prime_final, prime_score, conviction, rs_1d, rs_5d, rs_20d, 
                           ma_gap, amount, amount_strength, risk_level, is_leader=0):
    """스캔 시점의 판결 결과를 영구 저장하고, 생성된 고유 식별자(ID)를 반환합니다."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    kst = pytz.timezone("Asia/Seoul")
    created_at = datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")
    inserted_id = None
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
        inserted_id = c.lastrowid
    except Exception as e:
        print(f"⚠️ 히스토리 저장 실패: {e}")
    finally:
        conn.close()
    return inserted_id

def get_signal_persistence(code):
    """출력 엔진 및 의사결정 모델에 과거 누적 출현 지표를 제공합니다."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    kst = pytz.timezone("Asia/Seoul")
    today_str = datetime.now(kst).strftime("%Y-%m-%d")
    five_days_ago = (datetime.now(kst) - timedelta(days=5)).strftime("%Y-%m-%d")
    
    analysis = {"today_count": 0, "five_days_days": 0, "max_rank": 99, "leader_count": 0, "avg_final": 0.0}
    try:
        c.execute("SELECT COUNT(*) FROM candidate_history WHERE code = ? AND scan_datetime LIKE ?", (code, f"{today_str}%"))
        analysis["today_count"] = c.fetchone()[0]
        
        c.execute("SELECT COUNT(DISTINCT SUBSTR(scan_datetime, 1, 10)) FROM candidate_history WHERE code = ? AND scan_datetime >= ?", (code, five_days_ago))
        analysis["five_days_days"] = c.fetchone()[0]
        
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


# ==========================================
# [신규 추가] MEMORY LAYER 2단계: 성적표 등록 함수
# ==========================================
def register_signal_outcome(history_id, code, name, price_at_signal):
    """의사결정 엔진에서 최종 확정된 신호를 추적 명단에 PENDING 상태로 등록합니다."""
    if history_id is None:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    kst = pytz.timezone("Asia/Seoul")
    signal_date = datetime.now(kst).strftime("%Y-%m-%d")
    
    try:
        c.execute('''INSERT INTO signal_outcome 
                        (history_id, code, name, signal_date, price_at_signal, evaluation_status)
                     VALUES (?, ?, ?, ?, ?, 'PENDING')''',
                  (history_id, code, name, signal_date, price_at_signal))
        conn.commit()
    except Exception as e:
        print(f"⚠️ 성적표 등록 실패: {e}")
    finally:
        conn.close()


# ==========================================
# 레거시 데이터 및 포트폴리오 관리 (원본 유지)
# ==========================================
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
