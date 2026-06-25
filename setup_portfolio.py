from database import add_holding, get_all_holdings

def inject_initial_portfolio():
    print("⏳ [시스템] 포트폴리오 DB 주입을 시작합니다...")
    
    # 형님의 실제 보유 종목 데이터를 여기에 무한대로 추가할 수 있습니다.
    add_holding(
        code="232140", 
        name="와이씨", 
        buy_price=19520, 
        quantity=100, 
        weight=10.0, 
        sector="IT", 
        theme="반도체 장비"
    )
    
    # 예시: 추가 종목 주입 시 아래와 같이 복사하여 사용
    # add_holding(code="000660", name="SK하이닉스", buy_price=200000, quantity=50, weight=20.0, sector="IT", theme="반도체 대형주")
    
    print("✅ [성공] 데이터 주입이 완료되었습니다.\n")

def verify_database():
    print("🔍 [시스템] 현재 DB에 저장된 포트폴리오 목록을 확인합니다.")
    holdings = get_all_holdings()
    
    if not holdings:
        print("⚠️ 저장된 종목이 없습니다.")
        return
        
    for h in holdings:
        code, name, buy_p, qty, weight, b_date, sector, theme = h
        print(f" - [{code}] {name} | 매수가: {buy_p:,}원 | 테마: {theme}")
        
if __name__ == "__main__":
    inject_initial_portfolio()
    verify_database()
