import time
from core.order import buy_market, sell_market
from core.account import get_balance

def test_orders():
    print("--- 현재 잔고 조회 ---")
    balance = get_balance()
    print("잔고:", balance)
    
    print("\n--- 매수 테스트 (KODEX 200: 069500, 1주) ---")
    buy_res = buy_market("069500", 1)
    print("매수 결과:", buy_res)
    
    time.sleep(1)
    
    print("\n--- 매도 테스트 (KODEX 200: 069500, 1주) ---")
    sell_res = sell_market("069500", 1)
    print("매도 결과:", sell_res)

if __name__ == "__main__":
    test_orders()
