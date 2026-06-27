def fetch_pattern_stats(code):
    """단일 레코드가 아닌, 해당 종목의 과거 완료된 성적표를 그룹화하여 통계를 냅니다."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""
            SELECT 
                COUNT(*), 
                AVG(after_5d_chg), 
                AVG(max_gain), 
                AVG(max_drawdown)
            FROM signal_outcome 
            WHERE code = ? AND evaluation_status = 'COMPLETED'
        """, (code,))
        row = c.fetchone()
        
        if row and row[0] > 0:
            total = row[0]
            avg5 = row[1]
            avg_gain = row[2]
            avg_dd = row[3]
            
            c.execute("""
                SELECT COUNT(*) 
                FROM signal_outcome 
                WHERE code = ? AND evaluation_status = 'COMPLETED' AND after_5d_chg > 0
            """, (code,))
            wins = c.fetchone()[0]
            
            return (round(wins/total*100, 1), round(avg5, 2), round(avg_gain, 2), round(avg_dd, 2), total, 1)
    except Exception as e:
        print(f"⚠️ 텔레그램 통계 집계 에러: {e}")
    finally:
        conn.close()
    return None
