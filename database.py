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

# =========================================================================
# Signal Identity Contract & 정규화
# =========================================================================

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

# =========================================================================
# DB Safety & Column Exists Helper
# =========================================================================

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def _table_exists(conn, table_name: str) -> bool:
    return conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone() is not None

def _column_exists(conn, table_name: str, column_name: str) -> bool:
    """테이블 내 특정 컬럼의 존재 여부를 확인합니다."""
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
        _logger.info(f"DB logically backed up to {backup_path} via SQLite Backup API.")

# =========================================================================
# 극한의 Deep Schema Validator
# =========================================================================

def _validate_v9_schema(conn):
    tables = {
        "signal_master": [
            ("signal_id", "TEXT", 1, 1), ("code", "TEXT", 1, 0), ("signal_date", "TEXT", 1, 0),
            ("strategies", "TEXT", 1, 0), ("revision", "INTEGER", 1, 0), ("identity_origin", "TEXT", 1, 0),
            ("created_at", "TEXT", 1, 0)
        ],
        "signal_registry": [
            ("signal_id", "TEXT", 1, 1), ("code", "TEXT", 1, 0), ("signal_state", "TEXT", 0, 0)
        ],
        "signal_history_log": [
            ("id", "INTEGER", 0, 1), ("signal_id", "TEXT", 1, 0)
        ],
        "signal_outcome": [
            ("id", "INTEGER", 0, 1), ("history_id", "INTEGER", 1, 0), ("signal_id", "TEXT", 1, 0)
        ]
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
            if info[col_name][3] != not_null:
                raise RuntimeError(f"SCHEMA_VALIDATION_FAILED: {tbl}.{col_name} NOTNULL {info[col_name][3]} != {not_null}")
            if info[col_name][5] != pk:
                raise RuntimeError(f"SCHEMA_VALIDATION_FAILED: {tbl}.{col_name} PK {info[col_name][5]} != {pk}")

    fk_expectations = {
        "signal_registry": [("signal_id", "signal_master", "signal_id")],
        "signal_history_log": [("signal_id", "signal_master", "signal_id")],
        "signal_outcome": [("signal_id", "signal_master", "signal_id"), ("history_id", "signal_history_log", "id")]
    }
    for table, expected_fks in fk_expectations.items():
        fks = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        for from_col, target_tbl, to_col in expected_fks:
            if not any(fk[2] == target_tbl and fk[3] == from_col and fk[4] == to_col for fk in fks):
                raise RuntimeError(f"SCHEMA_VALIDATION_FAILED: Missing FK {table}.{from_col} -> {target_tbl}.{to_col}")

    idx_list = conn.execute("PRAGMA index_list(signal_master)").fetchall()
    unique_idx = [idx for idx in idx_list if idx[2] == 1]
    found_composite = False
    for idx in unique_idx:
        idx_info = conn.execute(f"PRAGMA index_info('{idx[1]}')").fetchall()
        cols = [col[2] for col in idx_info]
        if cols == ["code", "signal_date", "revision"]:
            found_composite = True
            break
    if not found_composite:
        raise RuntimeError("SCHEMA_VALIDATION_FAILED: signal_master UNIQUE(code, signal_date, revision) missing")

    registry_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='signal_registry'").fetchone()[0]
    normalized_sql = registry_sql.replace(" ", "").replace("\n", "").replace("\t", "")
    expected_check = "CHECK(signal_stateIN('WATCH','CONFIRMED','INVALIDATED','EXPIRED'))"
    if expected_check not in normalized_sql:
        raise RuntimeError("SCHEMA_VALIDATION_FAILED: signal_registry CHECK constraint missing or malformed")

# =========================================================================
# V0 -> V3 Fresh DB & Migration 분리
# =========================================================================

def _create_v3_schema(conn):
    _logger.info("Creating fresh V3 Database Schema...")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
    c.execute(f'''CREATE TABLE IF NOT EXISTS candidates (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, run_type TEXT, code TEXT, name TEXT, score INTEGER, buy_p INTEGER, target_1 INTEGER, target_2 INTEGER, stop_p INTEGER, price INTEGER, chg REAL, ma_gap REAL, prime_score INTEGER, final_rank REAL, conviction INTEGER, amount_strength REAL, rs_1d REAL, rs_5d REAL, rs_20d REAL, defense INTEGER, risk_level INTEGER, sent_telegram INTEGER DEFAULT 0, engine_version TEXT DEFAULT '{ENGINE_VERSION}')''')
    c.execute(f'''CREATE TABLE IF NOT EXISTS candidate_history (id INTEGER PRIMARY KEY AUTOINCREMENT, scan_datetime TEXT, run_type TEXT, code TEXT, name TEXT, rank_position INTEGER, price INTEGER, chg REAL, prime_final REAL, prime_score REAL, conviction REAL, rs_1d REAL, rs_5d REAL, rs_20d REAL, ma_gap REAL, amount INTEGER, amount_strength REAL, risk_level INTEGER, is_leader INTEGER DEFAULT 0, created_at TEXT, feature_snapshot_json TEXT, engine_version TEXT DEFAULT '{ENGINE_VERSION}')''')
    c.execute('''CREATE TABLE IF NOT EXISTS top10_tracking (id INTEGER PRIMARY KEY AUTOINCREMENT, scan_datetime TEXT, code TEXT, name TEXT, rank_position INTEGER, final_score REAL, risk_level INTEGER)''')
    c.execute('''CREATE TABLE signal_master (signal_id TEXT NOT NULL PRIMARY KEY, code TEXT NOT NULL, signal_date TEXT NOT NULL, strategies TEXT NOT NULL, revision INTEGER NOT NULL, identity_origin TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(code, signal_date, revision))''')
    c.execute('''CREATE TABLE signal_registry (signal_id TEXT NOT NULL PRIMARY KEY, code TEXT NOT NULL, name TEXT, signal_state TEXT CHECK(signal_state IN ('WATCH', 'CONFIRMED', 'INVALIDATED', 'EXPIRED')), first_seen_at TEXT, last_seen_at TEXT, last_price REAL, entry_price REAL, stop_loss REAL, target1 REAL, target2 REAL, ev REAL, expected_reward_rr REAL, current_level TEXT, confirmation_count INTEGER DEFAULT 1, invalidation_reason TEXT, updated_at TEXT, FOREIGN KEY(signal_id) REFERENCES signal_master(signal_id))''')
    c.execute('''CREATE TABLE signal_history_log (id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id TEXT NOT NULL, code TEXT, timestamp TEXT, level TEXT, ev REAL, signal_state TEXT, price REAL, action_note TEXT, FOREIGN KEY(signal_id) REFERENCES signal_master(signal_id))''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_signal_history_log_id_time ON signal_history_log(signal_id, timestamp)")
    c.execute('''CREATE TABLE signal_outcome (id INTEGER PRIMARY KEY AUTOINCREMENT, history_id INTEGER NOT NULL, signal_id TEXT NOT NULL, code TEXT, name TEXT, signal_date TEXT, price_at_signal INTEGER, after_1d_chg REAL DEFAULT 0.0, after_3d_chg REAL DEFAULT 0.0, after_5d_chg REAL DEFAULT 0.0, max_gain REAL DEFAULT 0.0, max_drawdown REAL DEFAULT 0.0, evaluation_status TEXT DEFAULT 'PENDING', market_regime TEXT, FOREIGN KEY(history_id) REFERENCES signal_history_log(id), FOREIGN KEY(signal_id) REFERENCES signal_master(signal_id), UNIQUE(history_id))''')

def _migrate_v0_to_v3(conn):
    c = conn.cursor()
    _logger.warning("Executing Schema V0 -> V3 Migration...")
    cnt_reg_old = c.execute("SELECT COUNT(*) FROM signal_registry").fetchone()[0] if _table_exists(conn, "signal_registry") else 0
    cnt_hist_old = c.execute("SELECT COUNT(*) FROM signal_history_log").fetchone()[0] if _table_exists(conn, "signal_history_log") else 0
    cnt_out_expected = c.execute("SELECT COUNT(DISTINCT history_id) FROM signal_outcome").fetchone()[0] if _table_exists(conn, "signal_outcome") else 0

    cols = [r[1] for r in c.execute("PRAGMA table_info(candidate_history)").fetchall()]
    if "feature_snapshot_json" not in cols:
        c.execute("ALTER TABLE candidate_history ADD COLUMN feature_snapshot_json TEXT")

    c.execute('''CREATE TABLE signal_master (signal_id TEXT NOT NULL PRIMARY KEY, code TEXT NOT NULL, signal_date TEXT NOT NULL, strategies TEXT NOT NULL, revision INTEGER NOT NULL, identity_origin TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(code, signal_date, revision))''')
    
    v8_codes = set()
    for tbl in ["signal_registry", "signal_history_log", "signal_outcome"]:
        if _table_exists(conn, tbl):
            v8_codes.update(r[0] for r in c.execute(f"SELECT DISTINCT code FROM {tbl}").fetchall() if r[0])

    for code in v8_codes:
        sig_id = f"V8_LEGACY_{code}"
        c.execute('''INSERT INTO signal_master (signal_id, code, signal_date, strategies, revision, identity_origin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)''', (sig_id, code, "2000-01-01", '["V8_MIGRATED"]', 0, 'V8_LEGACY_UNIFIED', get_kst_now()))

    if _table_exists(conn, "signal_registry"):
        old_data = c.execute("SELECT * FROM signal_registry").fetchall()
        old_cols = [col[0] for col in c.description]
        c.execute('''CREATE TABLE signal_registry_new (signal_id TEXT NOT NULL PRIMARY KEY, code TEXT NOT NULL, name TEXT, signal_state TEXT CHECK(signal_state IN ('WATCH', 'CONFIRMED', 'INVALIDATED', 'EXPIRED')), first_seen_at TEXT, last_seen_at TEXT, last_price REAL, entry_price REAL, stop_loss REAL, target1 REAL, target2 REAL, ev REAL, expected_reward_rr REAL, current_level TEXT, confirmation_count INTEGER DEFAULT 1, invalidation_reason TEXT, updated_at TEXT, FOREIGN KEY(signal_id) REFERENCES signal_master(signal_id))''')
        for row in old_data:
            rd = dict(zip(old_cols, row))
            code = rd.get("code", "000000")
            c.execute('''INSERT INTO signal_registry_new (signal_id, code, name, signal_state, first_seen_at, last_seen_at, last_price, entry_price, stop_loss, target1, target2, ev, expected_reward_rr, current_level, confirmation_count, invalidation_reason, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (f"V8_LEGACY_{code}", code, rd.get("name"), rd.get("signal_state", "EXPIRED"), rd.get("first_seen_at"), rd.get("last_seen_at"), rd.get("last_price"), rd.get("entry_price"), rd.get("stop_loss"), rd.get("target1"), rd.get("target2"), rd.get("ev"), rd.get("expected_reward_rr"), rd.get("current_level"), rd.get("confirmation_count", 1), rd.get("invalidation_reason"), rd.get("updated_at")))
        c.execute("DROP TABLE signal_registry")
        c.execute("ALTER TABLE signal_registry_new RENAME TO signal_registry")

    if _table_exists(conn, "signal_history_log"):
        old_data = c.execute("SELECT * FROM signal_history_log").fetchall()
        old_cols = [col[0] for col in c.description]
        c.execute('''CREATE TABLE signal_history_log_new (id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id TEXT NOT NULL, code TEXT, timestamp TEXT, level TEXT, ev REAL, signal_state TEXT, price REAL, action_note TEXT, FOREIGN KEY(signal_id) REFERENCES signal_master(signal_id))''')
        for row in old_data:
            rd = dict(zip(old_cols, row))
            code, hid = rd.get("code", "000000"), rd.get("id")
            c.execute('''INSERT INTO signal_history_log_new (id, signal_id, code, timestamp, level, ev, signal_state, price, action_note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', (hid, f"V8_LEGACY_{code}", code, rd.get("timestamp"), rd.get("level"), rd.get("ev"), rd.get("signal_state"), rd.get("price"), rd.get("action_note")))
        c.execute("DROP TABLE signal_history_log")
        c.execute("ALTER TABLE signal_history_log_new RENAME TO signal_history_log")
        c.execute("CREATE INDEX idx_signal_history_log_id_time ON signal_history_log(signal_id, timestamp)")

    if _table_exists(conn, "signal_outcome"):
        c.execute('''CREATE TABLE signal_outcome_new (id INTEGER PRIMARY KEY AUTOINCREMENT, history_id INTEGER NOT NULL, signal_id TEXT NOT NULL, code TEXT, name TEXT, signal_date TEXT, price_at_signal INTEGER, after_1d_chg REAL DEFAULT 0.0, after_3d_chg REAL DEFAULT 0.0, after_5d_chg REAL DEFAULT 0.0, max_gain REAL DEFAULT 0.0, max_drawdown REAL DEFAULT 0.0, evaluation_status TEXT DEFAULT 'PENDING', market_regime TEXT, FOREIGN KEY(history_id) REFERENCES signal_history_log(id), FOREIGN KEY(signal_id) REFERENCES signal_master(signal_id), UNIQUE(history_id))''')
        old_outcomes = c.execute("SELECT * FROM signal_outcome WHERE id IN (SELECT MAX(id) FROM signal_outcome GROUP BY history_id)").fetchall()
        old_cols = [col[0] for col in c.description]
        for row in old_outcomes:
            rd = dict(zip(old_cols, row))
            hid, code = rd.get("history_id"), rd.get("code", "000000")
            sig_id = f"V8_LEGACY_{code}"
            if not c.execute("SELECT 1 FROM signal_history_log WHERE id = ?", (hid,)).fetchone():
                c.execute('''INSERT INTO signal_history_log (id, signal_id, code, timestamp, signal_state, action_note) VALUES (?, ?, ?, ?, 'RESTORED', 'RESTORED_FOR_OUTCOME_FK')''', (hid, sig_id, code, rd.get("signal_date")))
            c.execute('''INSERT INTO signal_outcome_new (id, history_id, signal_id, code, name, signal_date, price_at_signal, after_1d_chg, after_3d_chg, after_5d_chg, max_gain, max_drawdown, evaluation_status, market_regime) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (rd["id"], hid, sig_id, code, rd.get("name"), rd.get("signal_date"), rd.get("price_at_signal"), rd.get("after_1d_chg"), rd.get("after_3d_chg"), rd.get("after_5d_chg"), rd.get("max_gain"), rd.get("max_drawdown"), rd.get("evaluation_status"), rd.get("market_regime")))
        c.execute("DROP TABLE signal_outcome")
        c.execute("ALTER TABLE signal_outcome_new RENAME TO signal_outcome")

    cnt_reg_new = c.execute("SELECT COUNT(*) FROM signal_registry").fetchone()[0] if _table_exists(conn, "signal_registry") else 0
    cnt_hist_new = c.execute("SELECT COUNT(*) FROM signal_history_log").fetchone()[0] if _table_exists(conn, "signal_history_log") else 0
    cnt_out_new = c.execute("SELECT COUNT(*) FROM signal_outcome").fetchone()[0] if _table_exists(conn, "signal_outcome") else 0

    if cnt_reg_old != cnt_reg_new:
        raise RuntimeError("MIGRATION_AUDIT_FAILED: Registry count mismatch")
    if cnt_hist_new < cnt_hist_old:
        raise RuntimeError("MIGRATION_AUDIT_FAILED: History count dropped")
    if cnt_out_expected != cnt_out_new:
        raise RuntimeError("MIGRATION_AUDIT_FAILED: Outcome count mismatch")

# =========================================================================
# 최상위 Bootstrap Orchestrator (Fail-Closed)
# =========================================================================

def bootstrap_db():
    conn = get_connection()
    try:
        mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if mode.lower() != "wal":
            raise RuntimeError("SQLITE_WAL_MODE_NOT_ACTIVE")

        current_ver = _get_current_schema_version(conn)
        if current_ver < DB_SCHEMA_VERSION:
            v9_exists = _table_exists(conn, "signal_master")
            v8_exists = _table_exists(conn, "signal_registry") and not _column_exists(conn, "signal_registry", "signal_id")

            if current_ver == 0 and v8_exists and v9_exists:
                raise RuntimeError("CORRUPTED_DB_STATE: Mixed V8/V9 tables detected with schema version 0.")

            if current_ver == 0 and v8_exists:
                _backup_db_before_migration(conn)
                conn.execute("BEGIN IMMEDIATE")
                _migrate_v0_to_v3(conn)
            elif current_ver == 0 and not v8_exists:
                conn.execute("BEGIN IMMEDIATE")
                _create_v3_schema(conn)
            else:
                raise RuntimeError(f"UNSUPPORTED_MIGRATION_PATH: {current_ver} -> {DB_SCHEMA_VERSION}")

            _validate_v9_schema(conn)
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("PRE_COMMIT_FK_VIOLATION")
            if conn.execute("PRAGMA integrity_check").fetchone()[0].lower() != "ok":
                raise RuntimeError("PRE_COMMIT_INTEGRITY_FAILED")

            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO schema_meta (key, value, updated_at) VALUES ('version', ?, ?)", (str(DB_SCHEMA_VERSION), get_kst_now()))
            conn.commit()
            _logger.info(f"DB Bootstrap to V{DB_SCHEMA_VERSION} Completed Safely.")
        elif current_ver == DB_SCHEMA_VERSION:
            _validate_v9_schema(conn)
        else:
            raise RuntimeError(f"DOWNGRADE_NOT_SUPPORTED: DB is v{current_ver}, Engine is v{DB_SCHEMA_VERSION}")
    except Exception as e:
        conn.rollback()
        _logger.critical(f"CRITICAL: DB Bootstrap Failed & Rolled Back. Engine Halted. Error: {e}")
        raise RuntimeError(f"DATABASE_BOOTSTRAP_FAILED: {e}") from e
    finally:
        conn.close()

# =========================================================================
# 런타임 트랜잭션 함수
# =========================================================================

def save_signal_transition(master_data: dict, registry_data: dict, log_data: dict) -> bool:
    if master_data and master_data["code"] != registry_data["code"]:
        raise ValueError("CROSS_TABLE_IDENTITY_MISMATCH: Master vs Registry code")
    if log_data["code"] != registry_data["code"]:
        raise ValueError("CROSS_TABLE_IDENTITY_MISMATCH: Log vs Registry code")

    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        c = conn.cursor()
        sig_id = registry_data["signal_id"]

        c.execute("SELECT 1 FROM signal_master WHERE signal_id=?", (sig_id,))
        master_exists = c.fetchone() is not None

        c.execute("SELECT signal_state FROM signal_registry WHERE signal_id=?", (sig_id,))
        reg_row = c.fetchone()
        reg_state = reg_row[0] if reg_row else None

        if not master_exists and reg_state:
            raise RuntimeError(f"DB_CORRUPTION: Registry exists but Master missing for {sig_id}")

        new_state = registry_data["signal_state"]
        if not is_valid_transition(reg_state, new_state):
            raise ValueError(f"STATE_MACHINE_VIOLATION: {reg_state} -> {new_state}")

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
        _logger.error(f"Atomic Transition Failed & Rolled back: {e}")
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
