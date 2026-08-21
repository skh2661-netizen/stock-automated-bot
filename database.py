# database.py
import sqlite3
import logging
import hashlib
import json
import os
from datetime import datetime
import pytz
from version import ENGINE_VERSION

_logger = logging.getLogger(__name__)
DB_PATH = "quant_data.db"
DB_SCHEMA_VERSION = 3

def get_kst_now() -> str:
    return datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")

def canonicalize_strategies(strategies: list) -> list:
    if not strategies:
        return []
    return sorted(list({str(x).strip().upper() for x in strategies if str(x).strip()}))

def generate_signal_id(code: str, signal_date: str, strategies: list, revision: int) -> str:
    date_str = signal_date[:10].replace("-", "")
    strats_str = ",".join(canonicalize_strategies(strategies)) if strategies else "NONE"
    raw_key = f"{code}_{date_str}_{strats_str}_{revision}"
    hash_suffix = hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:8]
    return f"{code}_{date_str}_R{revision}_{hash_suffix}"

def get_next_signal_revision(code: str, date_str: str) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT MAX(revision) FROM signal_master WHERE code = ? AND signal_date LIKE ?", (code, f"{date_str[:10]}%"))
    res = c.fetchone()[0]
    conn.close()
    return (res + 1) if res else 1

VALID_TRANSITIONS = {
    None: ["WATCH", "CONFIRMED"],
    "WATCH": ["WATCH", "CONFIRMED", "INVALIDATED", "EXPIRED"],
    "CONFIRMED": ["CONFIRMED", "INVALIDATED", "EXPIRED"],
    "INVALIDATED": [],
    "EXPIRED": []
}

def is_valid_transition(old_state: str, new_state: str) -> bool:
    return new_state in VALID_TRANSITIONS.get(old_state, [])

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def _table_exists(conn, table_name: str) -> bool:
    return conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone() is not None

def _column_exists(conn, table_name: str, column_name: str) -> bool:
    if not _table_exists(conn, table_name):
        return False
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
    return column_name in cols

def _get_current_schema_version(conn) -> int:
    if not _table_exists(conn, "schema_meta"):
        return 0
    res = conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
    return int(res[0]) if res else 0

def _backup_db_before_migration(conn):
    if os.path.exists(DB_PATH):
        backup_path = f"{DB_PATH}.bak_pre_v9_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        bck = sqlite3.connect(backup_path)
        conn.backup(bck)
        bck.close()

def _validate_v9_schema(conn):
    tables = {
        "signal_master": [("signal_id", "TEXT", 1, 1), ("code", "TEXT", 1, 0), ("signal_date", "TEXT", 1, 0), ("strategies", "TEXT", 1, 0), ("revision", "INTEGER", 1, 0), ("identity_origin", "TEXT", 1, 0), ("created_at", "TEXT", 1, 0)],
        "signal_registry": [("signal_id", "TEXT", 1, 1), ("code", "TEXT", 1, 0), ("signal_state", "TEXT", 0, 0)],
        "signal_history_log": [("id", "INTEGER", 0, 1), ("signal_id", "TEXT", 1, 0)],
        "signal_outcome": [("id", "INTEGER", 0, 1), ("history_id", "INTEGER", 1, 0), ("signal_id", "TEXT", 1, 0)]
    }
    for tbl, cols in tables.items():
        if not _table_exists(conn, tbl):
            raise RuntimeError(f"SCHEMA_VALIDATION_FAILED: Table {tbl} missing")
        info = {r[1]: r for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
        for col_name, c_type, not_null, pk in cols:
            if col_name not in info:
                raise RuntimeError(f"SCHEMA_VALIDATION_FAILED: {tbl}.{col_name} missing")
            if info[col_name][2] != c_type:
                raise RuntimeError(f"SCHEMA_VALIDATION_FAILED: {tbl}.{col_name} TYPE {info[col_name][2]} != {c_type}")

def _create_v3_schema(conn):
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
    c.execute(f'''CREATE TABLE IF NOT EXISTS candidates (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, run_type TEXT, code TEXT, name TEXT, score INTEGER, buy_p INTEGER, target_1 INTEGER, target_2 INTEGER, stop_p INTEGER, price INTEGER, chg REAL, ma_gap REAL, prime_score INTEGER, final_rank REAL, conviction INTEGER, amount_strength REAL, rs_1d REAL, rs_5d REAL, rs_20d REAL, defense INTEGER, risk_level INTEGER, sent_telegram INTEGER DEFAULT 0, engine_version TEXT DEFAULT '{ENGINE_VERSION}')''')
    c.execute(f'''CREATE TABLE IF NOT EXISTS candidate_history (id INTEGER PRIMARY KEY AUTOINCREMENT, scan_datetime TEXT, run_type TEXT, code TEXT, name TEXT, rank_position INTEGER, price INTEGER, chg REAL, prime_final REAL, prime_score REAL, conviction REAL, rs_1d REAL, rs_5d REAL, rs_20d REAL, ma_gap REAL, amount INTEGER, amount_strength REAL, risk_level INTEGER, is_leader INTEGER DEFAULT 0, created_at TEXT, feature_snapshot_json TEXT, engine_version TEXT DEFAULT '{ENGINE_VERSION}')''')
    c.execute('''CREATE TABLE IF NOT EXISTS top10_tracking (id INTEGER PRIMARY KEY AUTOINCREMENT, scan_datetime TEXT, code TEXT, name TEXT, rank_position INTEGER, final_score REAL, risk_level INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS signal_master (signal_id TEXT NOT NULL PRIMARY KEY, code TEXT NOT NULL, signal_date TEXT NOT NULL, strategies TEXT NOT NULL, revision INTEGER NOT NULL, identity_origin TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(code, signal_date, revision))''')
    c.execute('''CREATE TABLE IF NOT EXISTS signal_registry (signal_id TEXT NOT NULL PRIMARY KEY, code TEXT NOT NULL, name TEXT, signal_state TEXT CHECK(signal_state IN ('WATCH', 'CONFIRMED', 'INVALIDATED', 'EXPIRED')), first_seen_at TEXT, last_seen_at TEXT, last_price REAL, entry_price REAL, stop_loss REAL, target1 REAL, target2 REAL, ev REAL, expected_reward_rr REAL, current_level TEXT, confirmation_count INTEGER DEFAULT 1, invalidation_reason TEXT, updated_at TEXT, FOREIGN KEY(signal_id) REFERENCES signal_master(signal_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS signal_history_log (id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id TEXT NOT NULL, code TEXT, timestamp TEXT, level TEXT, ev REAL, signal_state TEXT, price REAL, action_note TEXT, FOREIGN KEY(signal_id) REFERENCES signal_master(signal_id))''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_signal_history_log_id_time ON signal_history_log(signal_id, timestamp)")
    c.execute('''CREATE TABLE IF NOT EXISTS signal_outcome (id INTEGER PRIMARY KEY AUTOINCREMENT, history_id INTEGER NOT NULL, signal_id TEXT NOT NULL, code TEXT, name TEXT, signal_date TEXT, price_at_signal INTEGER, after_1d_chg REAL DEFAULT 0.0, after_3d_chg REAL DEFAULT 0.0, after_5d_chg REAL DEFAULT 0.0, max_gain REAL DEFAULT 0.0, max_drawdown REAL DEFAULT 0.0, evaluation_status TEXT DEFAULT 'PENDING', market_regime TEXT, FOREIGN KEY(history_id) REFERENCES signal_history_log(id), FOREIGN KEY(signal_id) REFERENCES signal_master(signal_id), UNIQUE(history_id))''')

def _migrate_v0_to_v3(conn):
    c = conn.cursor()
    cols = [r[1] for r in c.execute("PRAGMA table_info(candidate_history)").fetchall()]
    if "feature_snapshot_json" not in cols:
        c.execute("ALTER TABLE candidate_history ADD COLUMN feature_snapshot_json TEXT")
    c.execute('''CREATE TABLE IF NOT EXISTS signal_master (signal_id TEXT NOT NULL PRIMARY KEY, code TEXT NOT NULL, signal_date TEXT NOT NULL, strategies TEXT NOT NULL, revision INTEGER NOT NULL, identity_origin TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(code, signal_date, revision))''')

def bootstrap_db():
    conn = get_connection()
    try:
        mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if mode.lower() != "wal":
            raise RuntimeError("SQLITE_WAL_MODE_NOT_ACTIVE")

        current_ver = _get_current_schema_version(conn)
        
        # 무조건 테이블 존재 여부를 확인하고 없으면 V3 스키마를 생성하도록 보완
        conn.execute("BEGIN IMMEDIATE")
        _create_v3_schema(conn)

        if current_ver < DB_SCHEMA_VERSION:
            v8_exists = _table_exists(conn, "signal_registry") and not _column_exists(conn, "signal_registry", "signal_id")
            if current_ver == 0 and v8_exists:
                _backup_db_before_migration(conn)
                _migrate_v0_to_v3(conn)

        _validate_v9_schema(conn)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO schema_meta (key, value, updated_at) VALUES ('version', ?, ?)", (str(DB_SCHEMA_VERSION), get_kst_now()))
        conn.commit()
        _logger.info(f"DB Bootstrap to V{DB_SCHEMA_VERSION} Completed Safely.")
    except Exception as e:
        conn.rollback()
        _logger.critical(f"CRITICAL: DB Bootstrap Failed: {e}")
        raise RuntimeError(f"DATABASE_BOOTSTRAP_FAILED: {e}") from e
    finally:
        conn.close()

def save_signal_transition(master_data: dict, registry_data: dict, log_data: dict) -> bool:
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        c = conn.cursor()
        sig_id = registry_data["signal_id"]
        
        c.execute("SELECT 1 FROM signal_master WHERE signal_id=?", (sig_id,))
        master_exists = c.fetchone() is not None
        
        now_str = get_kst_now()
        registry_data["updated_at"] = now_str
        log_data["timestamp"] = now_str

        if not master_exists and master_data:
            master_data["strategies"] = json.dumps(canonicalize_strategies(master_data.get("strategies", [])), ensure_ascii=False)
            master_data["identity_origin"] = "V9_RUNTIME"
            master_data["created_at"] = now_str
            c.execute('''INSERT INTO signal_master (signal_id, code, signal_date, strategies, revision, identity_origin, created_at) VALUES (:signal_id, :code, :signal_date, :strategies, :revision, :identity_origin, :created_at)''', master_data)

        c.execute('''INSERT INTO signal_registry (signal_id, code, name, signal_state, first_seen_at, last_seen_at, last_price, entry_price, stop_loss, target1, target2, ev, expected_reward_rr, current_level, confirmation_count, invalidation_reason, updated_at) VALUES (:signal_id, :code, :name, :signal_state, :first_seen_at, :last_seen_at, :last_price, :entry_price, :stop_loss, :target1, :target2, :ev, :expected_reward_rr, :current_level, :confirmation_count, :invalidation_reason, :updated_at) ON CONFLICT(signal_id) DO UPDATE SET signal_state = excluded.signal_state, last_seen_at = excluded.last_seen_at, last_price = excluded.last_price, entry_price = excluded.entry_price, stop_loss = excluded.stop_loss, target1 = excluded.target1, target2 = excluded.target2, ev = excluded.ev, expected_reward_rr = excluded.expected_reward_rr, current_level = excluded.current_level, confirmation_count = excluded.confirmation_count, invalidation_reason = excluded.invalidation_reason, updated_at = excluded.updated_at''', registry_data)

        c.execute('''INSERT INTO signal_history_log (signal_id, code, timestamp, level, ev, signal_state, price, action_note) VALUES (:signal_id, :code, :timestamp, :level, :ev, :signal_state, :price, :action_note)''', log_data)

        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        _logger.error(f"Atomic Transition Failed: {e}")
        return False
    finally:
        conn.close()

def get_active_signals() -> dict:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM signal_registry WHERE signal_state IN ('WATCH', 'CONFIRMED')")
    rows = c.fetchall()
    conn.close()
    return {row['signal_id']: dict(row) for row in rows}
