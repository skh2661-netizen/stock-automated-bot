def get_top10_stability(code):
    safe_code = str(code).zfill(6)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # [패치] 시계열 기준점 동기화 (최근 5일 데이터만 추출)
    kst_now = datetime.now(pytz.timezone("Asia/Seoul"))
    five_days_ago = (kst_now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute("""
        SELECT 
            COUNT(*), 
            COUNT(DISTINCT SUBSTR(scan_datetime, 1, 10)), 
            AVG(rank_position) 
        FROM top10_tracking 
        WHERE code=? 
        AND datetime(scan_datetime) >= datetime(?)
    """, (safe_code, five_days_ago))
    
    row = c.fetchone()
    conn.close()
    
    return {
        "top10_count": row[0] if row and row[0] else 0,
        "days": row[1] if row and row[1] else 0,
        "avg_rank": round(row[2], 1) if row and row[2] else 0.0
    }
