import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['bb_mid'] = df['close'].rolling(window=20).mean()
    df['bb_std'] = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['bb_mid'] + (df['bb_std'] * 2)
    df['bb_lower'] = df['bb_mid'] - (df['bb_std'] * 2)
    
    df['ema_12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema_26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = df['ema_12'] - df['ema_26']
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    
    ndays_high = df['high'].rolling(window=14).max()
    ndays_low = df['low'].rolling(window=14).min()
    df['rsv'] = ((df['close'] - ndays_low) / (ndays_high - ndays_low)) * 100
    return df

def run_backtest(code, name, start_date, end_date):
    ticker = f"{code}.KS"
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if df.empty:
        return None
    
    df.columns = [col[0].lower() for col in df.columns]  # Make columns like 'close', 'open'
    df = add_indicators(df)
    
    cash = 10000000
    buy_amount = 1000000
    qty = 0
    avg_price = 0
    
    trades = 0
    wins = 0
    
    for i in range(26, len(df)):
        curr_price = df['close'].iloc[i]
        
        # Check Sell
        if qty > 0:
            profit_rate = ((curr_price - avg_price) / avg_price) * 100
            
            # Take profit 5%, Stop loss -3%
            if profit_rate >= 5.0 or profit_rate <= -3.0:
                cash += qty * curr_price
                if profit_rate > 0: wins += 1
                trades += 1
                qty = 0
                avg_price = 0
                continue
                
            curr = df.iloc[i]
            prev = df.iloc[i-1]
            
            bb_upper_touch = curr_price >= curr['bb_upper']
            macd_dead_cross = (prev['macd'] > prev['macd_signal']) and (curr['macd'] <= curr['macd_signal'])
            rsv_overbought = curr['rsv'] >= 70
            
            if bb_upper_touch or (macd_dead_cross and rsv_overbought):
                cash += qty * curr_price
                if profit_rate > 0: wins += 1
                trades += 1
                qty = 0
                avg_price = 0
                continue

        # Check Buy
        if qty == 0 and cash >= buy_amount:
            curr = df.iloc[i]
            prev = df.iloc[i-1]
            
            bb_condition = curr_price <= curr['bb_lower'] * 1.05
            macd_golden_cross = (prev['macd'] < prev['macd_signal']) and (curr['macd'] >= curr['macd_signal'])
            rsv_condition = curr['rsv'] <= 30
            
            score = sum([bb_condition, macd_golden_cross, rsv_condition])
            
            if score >= 2:
                buy_qty = buy_amount // curr_price
                if buy_qty > 0:
                    cost = buy_qty * curr_price
                    cash -= cost
                    qty += buy_qty
                    avg_price = curr_price

    # End of period
    final_eval = cash + (qty * df['close'].iloc[-1])
    profit = final_eval - 10000000
    profit_pct = (profit / 10000000) * 100
    win_rate = (wins / trades * 100) if trades > 0 else 0
    
    return {
        "Name": name,
        "Trades": trades,
        "Win Rate": f"{win_rate:.1f}%",
        "Final Eval": f"{int(final_eval):,}원",
        "Total Profit": f"{int(profit):,}원",
        "Return": f"{profit_pct:+.1f}%"
    }

if __name__ == "__main__":
    stocks = [
        ("005930", "삼성전자"),
        ("000660", "SK하이닉스"),
        ("035420", "NAVER"),
        ("005380", "현대차"),
        ("068270", "셀트리온")
    ]
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=5*365)).strftime("%Y-%m-%d")
    
    print(f"=== 복합 전략 5년 백테스트 결과 ({start_date} ~ {end_date}) ===")
    print(f"초기 자본: 10,000,000원 | 1회 매수: 1,000,000원")
    print("-" * 65)
    
    results = []
    for code, name in stocks:
        res = run_backtest(code, name, start_date, end_date)
        if res:
            results.append(res)
            print(f"{res['Name']:<10} | 거래 {res['Trades']:>2}회 | 승률 {res['Win Rate']:>6} | 수익: {res['Return']:>6} ({res['Total Profit']})")
    print("-" * 65)
    
    # 총합
    total_eval = sum([int(r['Final Eval'].replace(',', '').replace('원', '')) for r in results])
    total_invest = 10000000 * len(stocks)
    total_profit = total_eval - total_invest
    total_return = (total_profit / total_invest) * 100
    print(f"[총 계좌 요약] 총 평가: {total_eval:,}원 | 총 수익률: {total_return:+.1f}%")
