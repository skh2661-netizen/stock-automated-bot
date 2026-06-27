# [수정 4] 집계 쿼리 버그 수정 및 표본 등급화
def fetch_pattern_stats(code):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), AVG(after_5d_chg), AVG(max_gain), AVG(max_drawdown) FROM signal_outcome WHERE code=? AND evaluation_status='COMPLETED'", (code,))
    row = c.fetchone()
    if row and row[0] >= 5: # 표본 검증
        wins = c.execute("SELECT COUNT(*) FROM signal_outcome WHERE code=? AND after_5d_chg > 0", (code,)).fetchone()[0]
        return (round(wins/row[0]*100,1), round(row[1],2), round(row[2],2), round(row[3],2), row[0])
    return None

# [출력부 수정]
if pattern:
    (win, avg, gain, dd, matches) = pattern
    rel = "🔥 강한 신뢰" if matches >= 50 else ("🟢 유효" if matches >= 20 else "🟡 참고")
    msg += f"신뢰도: {rel} ({matches}개)\n승률: {win}%\n수익: {avg}%\n"
