"""
백테스트: 비대칭 리스크 전략 (2026년 1월~5월)
python backtest.py 로 실행
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import FinanceDataReader as fdr
from datetime import date

# 전략 임포트
from strategy.complex import Kospi200ComplexStrategy

START = "2026-01-02"
END   = "2026-05-21"

# 시총 상위 30종목 (대표 샘플 — 전체 150개는 API 제한으로 축소)
SAMPLE_CODES = [
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("005380", "현대차"),
    ("000270", "기아"),
    ("051910", "LG화학"),
    ("035420", "NAVER"),
    ("006400", "삼성SDI"),
    ("068270", "셀트리온"),
    ("028260", "삼성물산"),
    ("105560", "KB금융"),
    ("055550", "신한지주"),
    ("086790", "하나금융지주"),
    ("032830", "삼성생명"),
    ("017670", "SK텔레콤"),
    ("030200", "KT"),
    ("096770", "SK이노베이션"),
    ("034730", "SK"),
    ("003670", "포스코퓨처엠"),
    ("207940", "삼성바이오로직스"),
    ("012330", "현대모비스"),
    ("035720", "카카오"),
    ("010130", "고려아연"),
    ("011170", "롯데케미칼"),
    ("009150", "삼성전기"),
    ("018260", "삼성에스디에스"),
    ("051900", "LG생활건강"),
    ("003550", "LG"),
    ("000100", "유한양행"),
    ("047050", "포스코인터내셔널"),
    ("316140", "우리금융지주"),
]

INITIAL_CASH = 10_000_000   # 초기 자금 1000만원
BUY_AMOUNT   = 500_000      # 종목당 매수 금액 50만원
MAX_STOCKS   = 10           # 최대 보유 종목 수

strategy = Kospi200ComplexStrategy()

# ── 데이터 로드 ──────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  백테스트: {START} ~ {END}")
print(f"  전략: {strategy.name}")
print(f"  초기자금: {INITIAL_CASH:,}원  |  종목당 매수: {BUY_AMOUNT:,}원")
print(f"{'='*60}\n")

price_data: dict[str, pd.DataFrame] = {}
for code, name in SAMPLE_CODES:
    try:
        df = fdr.DataReader(code, START, END)
        if df is None or len(df) < 30:
            continue
        df = df.rename(columns=str.lower)
        df = df[['open','high','low','close','volume']].dropna()
        price_data[code] = (name, df)
    except Exception as e:
        pass

print(f"데이터 로드 완료: {len(price_data)}개 종목\n")

# ── 백테스트 엔진 ────────────────────────────────────────────────────
cash      = float(INITIAL_CASH)
holdings  = {}   # code → {name, qty, avg_price, peak}
trade_log = []

# 전체 거래일 기준으로 순서대로 시뮬레이션
all_dates = sorted(set(
    d for _, (name, df) in price_data.items() for d in df.index
))

for today in all_dates:
    # 매도 먼저
    for code in list(holdings.keys()):
        if code not in price_data:
            continue
        name, df = price_data[code]
        if today not in df.index:
            continue

        idx      = df.index.get_loc(today)
        cur_price = int(df.iloc[idx]['close'])
        hist_df   = df.iloc[:idx+1].copy()

        h       = holdings[code]
        avg_p   = h['avg_price']
        qty     = h['qty']
        peak    = h.get('peak', cur_price)

        # 고점 갱신
        if cur_price > peak:
            h['peak'] = cur_price
            peak = cur_price

        # 수익률
        profit_rate = (cur_price - avg_p) / avg_p * 100

        if len(hist_df) < 26:
            continue

        sell = strategy.should_sell(code, hist_df, cur_price, avg_p)
        if sell:
            proceeds = cur_price * qty
            cash += proceeds
            pnl  = (cur_price - avg_p) * qty
            trade_log.append({
                'date':   str(today.date() if hasattr(today,'date') else today)[:10],
                'side':   'SELL',
                'code':   code,
                'name':   name,
                'qty':    qty,
                'price':  cur_price,
                'avg':    avg_p,
                'pnl':    pnl,
                'profit_rate': profit_rate,
            })
            del holdings[code]

    # 매수
    if len(holdings) < MAX_STOCKS:
        for code, (name, df) in price_data.items():
            if code in holdings:
                continue
            if len(holdings) >= MAX_STOCKS:
                break
            if today not in df.index:
                continue

            idx       = df.index.get_loc(today)
            cur_price = int(df.iloc[idx]['close'])
            hist_df   = df.iloc[:idx+1].copy()

            if len(hist_df) < 26:
                continue

            buy = strategy.should_buy(code, hist_df, cur_price)
            if buy and cash >= BUY_AMOUNT:
                qty = BUY_AMOUNT // cur_price
                if qty <= 0:
                    continue
                cost = qty * cur_price
                cash -= cost
                holdings[code] = {
                    'name': name, 'qty': qty,
                    'avg_price': cur_price, 'peak': cur_price,
                }
                trade_log.append({
                    'date':  str(today.date() if hasattr(today,'date') else today)[:10],
                    'side':  'BUY',
                    'code':  code,
                    'name':  name,
                    'qty':   qty,
                    'price': cur_price,
                    'avg':   cur_price,
                    'pnl':   0,
                    'profit_rate': 0,
                })

# 잔여 보유종목 평가 (미청산)
# 마지막 날 종가 기준
final_eval = 0.0
unrealized = []
for code, h in holdings.items():
    if code not in price_data:
        continue
    name, df = price_data[code]
    last_price = int(df.iloc[-1]['close'])
    val = last_price * h['qty']
    pnl = (last_price - h['avg_price']) * h['qty']
    rate = (last_price - h['avg_price']) / h['avg_price'] * 100
    final_eval += val
    unrealized.append({
        'code': code, 'name': name,
        'qty': h['qty'], 'avg': h['avg_price'], 'last': last_price,
        'pnl': pnl, 'rate': rate,
    })

# ── 결과 출력 ────────────────────────────────────────────────────────
total_value  = cash + final_eval
total_return = (total_value - INITIAL_CASH) / INITIAL_CASH * 100

# 거래 내역
buys  = [t for t in trade_log if t['side'] == 'BUY']
sells = [t for t in trade_log if t['side'] == 'SELL']
wins  = [t for t in sells if t['pnl'] > 0]
loses = [t for t in sells if t['pnl'] <= 0]

print(f"\n{'='*60}")
print(f"  백테스트 결과 ({START} ~ {END})")
print(f"{'='*60}")
print(f"  초기자금:      {INITIAL_CASH:>12,.0f} 원")
print(f"  최종 현금:     {cash:>12,.0f} 원")
print(f"  미청산 평가액: {final_eval:>12,.0f} 원")
print(f"  최종 총자산:   {total_value:>12,.0f} 원")
print(f"  총 수익률:     {total_return:>+11.2f} %")
print(f"{'─'*60}")
print(f"  총 매수 횟수:  {len(buys):>4}회")
print(f"  총 매도 횟수:  {len(sells):>4}회")
if sells:
    print(f"  승리 거래:     {len(wins):>4}회  ({len(wins)/len(sells)*100:.1f}%)")
    print(f"  패배 거래:     {len(loses):>4}회  ({len(loses)/len(sells)*100:.1f}%)")
    avg_win  = sum(t['profit_rate'] for t in wins)  / len(wins)  if wins  else 0
    avg_lose = sum(t['profit_rate'] for t in loses) / len(loses) if loses else 0
    print(f"  평균 수익률(승):  {avg_win:>+.2f}%")
    print(f"  평균 수익률(패):  {avg_lose:>+.2f}%")
    if avg_lose != 0:
        print(f"  손익비 (W/L):     {abs(avg_win/avg_lose):.2f}x")

# 미청산 보유종목
if unrealized:
    print(f"\n  {'─'*55}")
    print(f"  미청산 보유종목 (마지막 날 종가 기준)")
    print(f"  {'종목명':<16} {'보유수':<5} {'매수가':>8} {'현재가':>8} {'수익률':>7} {'평가손익':>10}")
    print(f"  {'─'*55}")
    for u in sorted(unrealized, key=lambda x: x['rate'], reverse=True):
        print(f"  {u['name']:<16} {u['qty']:>4}주  {u['avg']:>8,} {u['last']:>8,} {u['rate']:>+6.1f}% {u['pnl']:>+10,.0f}")

# 거래 내역 상세 (상위/하위 5개)
if sells:
    print(f"\n  {'─'*55}")
    print(f"  수익 TOP 5")
    for t in sorted(sells, key=lambda x: x['profit_rate'], reverse=True)[:5]:
        print(f"    {t['date']} {t['name']:<14}  {t['profit_rate']:>+6.1f}%  {t['pnl']:>+10,.0f}원")
    if loses:
        print(f"\n  손실 TOP 5")
        for t in sorted(sells, key=lambda x: x['profit_rate'])[:5]:
            print(f"    {t['date']} {t['name']:<14}  {t['profit_rate']:>+6.1f}%  {t['pnl']:>+10,.0f}원")

print(f"\n{'='*60}\n")
