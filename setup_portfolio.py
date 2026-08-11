# setup_portfolio.py
import json
import os

HOLDINGS_FILE = "holdings.json"

def load_holdings():
    if not os.path.exists(HOLDINGS_FILE):
        return []
    with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def save_holdings(data):
    with open(HOLDINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def add_holding():
    print("\n[신규 매수 종목 등록]")
    code = input("종목코드 (예: 017670): ").strip()
    if not code: return
    
    holdings = load_holdings()
    for h in holdings:
        if h["code"] == code:
            print(f"⚠️ 이미 보유 중인 종목입니다 ({code}).")
            return
            
    name = input("종목명 (예: SK텔레콤): ").strip()
    try:
        entry_price = float(input("매수가 (예: 86000): "))
        quantity = int(input("수량 (예: 10): "))
    except ValueError:
        print("⚠️ 가격과 수량은 숫자로 입력해야 합니다.")
        return

    new_item = {
        "code": code,
        "name": name,
        "entry_price": entry_price,
        "current_price": entry_price,
        "highest_price": entry_price,
        "quantity": quantity,
        "return_rate": 0.0,
        "action": "HOLD",
        "loss_limit": -10.0,
        "trailing_limit": -15.0
    }
    
    holdings.append(new_item)
    save_holdings(holdings)
    print(f"✅ 포트폴리오 추가 완료: {name} ({code}) / 매수가 {entry_price:,.0f}원")

def remove_holding():
    print("\n[보유 종목 삭제 (청산 완료)]")
    code = input("삭제할 종목코드: ").strip()
    holdings = load_holdings()
    
    new_holdings = [h for h in holdings if h["code"] != code]
    
    if len(holdings) == len(new_holdings):
        print("⚠️ 해당 종목을 찾을 수 없습니다.")
    else:
        save_holdings(new_holdings)
        print(f"✅ 종목({code})이 포트폴리오에서 삭제되었습니다.")

def list_holdings():
    print("\n=== 💼 현재 보유 포트폴리오 ===")
    holdings = load_holdings()
    if not holdings:
        print("보유 중인 종목이 없습니다.")
    else:
        for i, h in enumerate(holdings, 1):
            print(f"{i}. {h['name']} ({h['code']}) - 매수가: {h['entry_price']:,.0f}원 | 수량: {h['quantity']}주")
    print("===============================\n")

if __name__ == "__main__":
    while True:
        print("\n[V9 포트폴리오 관리자]")
        print("1. 보유 종목 조회")
        print("2. 신규 매수 등록")
        print("3. 청산 종목 삭제")
        print("4. 종료")
        
        choice = input("메뉴 선택 (1~4): ").strip()
        
        if choice == '1':
            list_holdings()
        elif choice == '2':
            add_holding()
        elif choice == '3':
            remove_holding()
        elif choice == '4':
            print("종료합니다.")
            break
        else:
            print("⚠️ 올바른 번호를 입력하세요.")
