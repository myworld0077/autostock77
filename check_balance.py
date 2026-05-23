from config.settings import settings
from core.account import get_balance, get_holdings

balance = get_balance()
holdings = get_holdings()

print('=== 모의계좌 잔고 ===')
print(f'주문가능 예수금: {balance["cash"]:,}원')
print(f'총 평가금액: {balance["total_eval"]:,}원')
print(f'총 평가손익: {balance["total_profit"]:,}원')
print(f'총 수익률: {balance["profit_rate"]}%\n')

print('=== 보유 종목 ===')
if not holdings:
    print('보유 종목이 없습니다.')
else:
    for h in holdings:
        profit_rate = h.get('profit_rate', 0.0)
        print(f'{h["name"]}({h["code"]}) - {h["qty"]}주 | 매입가: {h["avg_price"]:,}원 | 현재가: {h["cur_price"]:,}원 | 수익률: {profit_rate:+.2f}%')
