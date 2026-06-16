def init_db():
    os.makedirs("data", exist_ok=True)
    conn = connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            unique_key TEXT PRIMARY KEY,
            date TEXT, timestamp TEXT, run_type TEXT,
            strategy_version TEXT, score_version TEXT,
            code TEXT, name TEXT, score INTEGER,
            buy_p INTEGER, target1_p INTEGER, target2_p INTEGER, stop_p INTEGER,
            entry_price INTEGER DEFAULT NULL, entry_success INTEGER DEFAULT NULL,
            exit_type TEXT DEFAULT '대기',
            d1_high INTEGER, d1_low INTEGER, d1_close INTEGER,
            d3_high INTEGER, d3_low INTEGER, d3_close INTEGER,
            d5_high INTEGER, d5_low INTEGER, d5_close INTEGER,
            result_status TEXT DEFAULT '대기'
        )
    """)
    # [형님 지침] 중복 발송 방지용 컬럼 추가 (이미 있다면 무시)
    try:
        conn.execute("ALTER TABLE candidates ADD COLUMN telegram_sent INTEGER DEFAULT 0")
    except:
        pass
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, run_type TEXT, message TEXT
        )
    """)
    conn.commit()
    conn.close()

# [형님 지침] 발송 상태 업데이트 함수
def mark_telegram_sent(codes):
    if not codes: return
    conn = connect()
    conn.executemany("UPDATE candidates SET telegram_sent=1 WHERE code=?", [(c,) for c in codes])
    conn.commit()
    conn.close()
