# 1. migrate_db()의 columns 딕셔너리에 버전 컬럼 추가
columns = {
    # ... (기존 컬럼들) ...
    "engine_version": "TEXT DEFAULT 'V8.8.13'"
}

# 2. save_candidate_history 함수 서명 및 쿼리에 engine_version 추가
def save_candidate_history(..., risk_level, is_leader=0, engine_version="V8.8.13"):
    # ... INSERT INTO 쿼리에 engine_version 추가 로직 반영 ...

# 3. get_signal_quality 함수 내 N<5 차단 로직 추가
def get_signal_quality(risk_level, rs_20d, conviction):
    # ... (기존 설정) ...
    try:
        for level_idx, margins in enumerate(fallback_levels, 1):
            # ... (조건 연산) ...
            c.execute(...)
            rows = c.fetchall()
            
            if rows:
                total = len(rows)
                # [수정] 표본이 5개 미만이면 통계적 유의성이 없으므로 기각하고 다음 Fallback 레벨로 이동
                if total < 5:
                    continue 
                
                wins = len([r for r in rows if r[0] > 0])
                quality_stats["match_count"] = total
                quality_stats["win_rate"] = round((wins / total) * 100, 1)
                quality_stats["avg_after_5d"] = round(sum(r[0] for r in rows) / total, 2)
                quality_stats["avg_max_gain"] = round(sum(r[1] for r in rows) / total, 2)
                quality_stats["avg_mdd"] = round(sum(r[2] for r in rows) / total, 2)
                quality_stats["is_valid"] = True
                quality_stats["search_level"] = level_idx
                break
