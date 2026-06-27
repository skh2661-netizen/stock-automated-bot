import sqlite3
import pandas as pd
import FinanceDataReader as fdr
import time
from datetime import datetime
import pytz

DB_PATH = "quant_data.db"

def get_pending_signals():
    """DB에서 아직 평가가 완료되지 않은(PENDING) 신호 목록을 가져옵니다."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, code, name, signal_date, price_at_signal FROM signal_outcome WHERE evaluation_status = 'PENDING'")
    rows = c.fetchall()
    conn.close()
    return rows

def update_outcome_record(record_id, metrics, status):
    """채점된 결과를 DB에 업데이트하고 상태(PENDING -> COMPLETED/ERROR)를 변경합니다."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('''UPDATE signal_outcome 
                     SET after_1d_chg = ?, after_3d_chg = ?, after_5d_chg = ?, 
                         max_gain = ?, max_drawdown = ?, evaluation_status = ? 
                     WHERE id = ?''',
                  (metrics.get("after_1d", 0.0), metrics.get("after_3d", 0.0), metrics.get("after_5d", 0.0),
                   metrics.get("max_gain", 0.0), metrics.get("mdd", 0.0), status, record_id))
        conn.commit()
    except Exception as e:
        print(f"⚠️ 성적표 업데이트 실패 (ID: {record_id}): {e}")
    finally:
        conn.close()

def evaluate_signals():
    """PENDING 상태의 신호들을 순회하며 실제 미래 수익률을 채점합니다."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 📊 장후 복기 엔진 가동 (Outcome Evaluator)")
    
    pending_records = get_pending_signals()
    if not pending_records:
        print("✅ 평가 대기 중인 신호가 없습니다.")
        return

    print(f"총 {len(pending_records)}개의 대기 신호 채점을 시작합니다...\n")

    for record in pending_records:
        record_id, code, name, signal_date, entry_price = record
        
        # 진입가가 0이거나 데이터 이상이 있는 경우 방어
        if entry_price <= 0:
            update_outcome_record(record_id, {}, "ERROR")
            continue

        try:
            # 신호 발생일(T+0)부터 현재까지의 주가 데이터 호출
            df = fdr.DataReader(code, signal_date)
            time.sleep(0.5) # API Rate Limit 방어를 위한 강제 지연 (매우 중요)
            
            if df.empty or len(df) == 0:
                print(f"⚠️ [{name}] 주가 데이터 없음 (거래정지 등) -> ERROR 처리")
                update_outcome_record(record_id, {}, "ERROR")
                continue

            metrics = {}
            trading_days_passed = len(df) - 1 # T+0일을 제외한 실제 경과 거래일 수
            
            # T+0 (신호 발생 당일) 이후의 데이터만 슬라이싱하여 고점/저점 추적
            future_df = df.iloc[1:] if trading_days_passed > 0 else pd.DataFrame()
            
            if not future_df.empty:
                # 기간 내 최대 수익률 (Max Gain) 및 최대 낙폭 (MDD) 연산
                metrics["max_gain"] = round(((future_df['High'].max() / entry_price) - 1) * 100, 2)
                metrics["mdd"] = round(((future_df['Low'].min() / entry_price) - 1) * 100, 2)
            
            # T+1, T+3, T+5 종가 기준 수익률 연산 (해당 일자가 도달했을 경우만)
            if trading_days_passed >= 1:
                metrics["after_1d"] = round(((df.iloc[1]['Close'] / entry_price) - 1) * 100, 2)
            if trading_days_passed >= 3:
                metrics["after_3d"] = round(((df.iloc[3]['Close'] / entry_price) - 1) * 100, 2)
            if trading_days_passed >= 5:
                metrics["after_5d"] = round(((df.iloc[5]['Close'] / entry_price) - 1) * 100, 2)

            # 상태 판별: 5거래일(T+5) 이상 데이터가 확보되었다면 평가 완료(COMPLETED)
            if trading_days_passed >= 5:
                status = "COMPLETED"
                print(f"✅ [{name}] T+5 평가 완료 (Max Gain: {metrics.get('max_gain')}%, MDD: {metrics.get('mdd')}%)")
            else:
                status = "PENDING" # 아직 5일이 지나지 않았으므로 계속 추적 대기
                print(f"⏳ [{name}] T+{trading_days_passed} 진행 중... (현재 Max Gain: {metrics.get('max_gain', 0.0)}%)")

            # 채점 결과 DB 반영
            update_outcome_record(record_id, metrics, status)

        except Exception as e:
            print(f"❌ [{name}] 연산 중 에러 발생: {e}")
            # 치명적 오류가 발생한 레코드는 무한 루프 방지를 위해 ERROR 처리
            update_outcome_record(record_id, {}, "ERROR")

    print("\n🏁 장후 복기 및 채점 프로세스 완료")

if __name__ == "__main__":
    evaluate_signals()
