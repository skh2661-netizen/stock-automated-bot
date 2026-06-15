# 기존 results.append 줄을 삭제하고 아래 내용으로 교체
            save_candidate(code, row['Name'], score, int(row['Close']), risk_level)
            
            # 텔레그램 전송용 상세 데이터 패키징
            amount_100m = int(row['Amount'] / 100000000) # 억 단위 변환
            results.append({
                "code": code, 
                "name": row['Name'], 
                "score": score, 
                "grade": grade(score), 
                "price": int(row['Close']),
                "amount": amount_100m,
                "chg": round(row['ChangesRatio'], 2)
            })
