import traceback

try:
    import sqlite3
    import pandas as pd
    import FinanceDataReader as fdr
    print("모든 라이브러리 로드 성공!")
    
    conn = sqlite3.connect("test.db")
    print("DB 연결 성공!")
    
    # 간단한 테스트
    df = fdr.DataReader("005930", "2026-06-01", "2026-06-10")
    print(f"삼성전자 데이터 로드 성공: {len(df)}건")

except Exception:
    print("=== 에러가 발생했습니다! 아래 내용을 복사해서 저에게 보여주십시오 ===")
    print(traceback.format_exc())

input("\n확인을 위해 엔터를 누르세요...")
