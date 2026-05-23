"""
이동평균선 골든크로스/데드크로스 전략

매수 조건: 단기 이동평균(5일)이 장기 이동평균(20일)을 상향 돌파 (골든크로스)
매도 조건: 단기 이동평균이 장기 이동평균을 하향 돌파 (데드크로스)
         또는 수익률이 목표(+5%) 도달 / 손절(-3%) 도달
"""
import pandas as pd
from strategy.base import BaseStrategy
from utils.logger import log


class MovingAverageCrossStrategy(BaseStrategy):
    """이동평균선 크로스 전략"""

    name = "MA Cross (5/20)"

    def __init__(self, short_window: int = 5, long_window: int = 20,
                 take_profit: float = 5.0, stop_loss: float = -3.0):
        self.short_window = short_window
        self.long_window = long_window
        self.take_profit = take_profit    # 익절 기준 (%)
        self.stop_loss = stop_loss        # 손절 기준 (%)

    def _calc_ma(self, df: pd.DataFrame) -> pd.DataFrame:
        """이동평균선 계산"""
        df = df.copy()
        df["ma_short"] = df["close"].rolling(window=self.short_window).mean()
        df["ma_long"] = df["close"].rolling(window=self.long_window).mean()
        return df

    def should_buy(self, stock_code: str, df: pd.DataFrame, current_price: int) -> bool:
        if len(df) < self.long_window + 1:
            return False

        df = self._calc_ma(df)
        prev = df.iloc[-2]
        curr = df.iloc[-1]

        # 골든크로스: 직전 봉에서는 단기 < 장기 → 현재 봉에서 단기 >= 장기
        golden_cross = (prev["ma_short"] < prev["ma_long"]) and \
                       (curr["ma_short"] >= curr["ma_long"])

        if golden_cross:
            log.info(f"[전략] 🟢 골든크로스 매수 신호 - {stock_code} "
                     f"(MA{self.short_window}={curr['ma_short']:.0f}, "
                     f"MA{self.long_window}={curr['ma_long']:.0f})")
        return golden_cross

    def should_sell(self, stock_code: str, df: pd.DataFrame, current_price: int,
                    avg_price: int) -> bool:
        if avg_price <= 0:
            return False

        profit_rate = ((current_price - avg_price) / avg_price) * 100

        # 1) 익절
        if profit_rate >= self.take_profit:
            log.info(f"[전략] 🔴 익절 매도 - {stock_code} "
                     f"(수익률: {profit_rate:.1f}% ≥ {self.take_profit}%)")
            return True

        # 2) 손절
        if profit_rate <= self.stop_loss:
            log.info(f"[전략] 🔴 손절 매도 - {stock_code} "
                     f"(수익률: {profit_rate:.1f}% ≤ {self.stop_loss}%)")
            return True

        # 3) 데드크로스
        if len(df) >= self.long_window + 1:
            df = self._calc_ma(df)
            prev = df.iloc[-2]
            curr = df.iloc[-1]
            dead_cross = (prev["ma_short"] > prev["ma_long"]) and \
                         (curr["ma_short"] <= curr["ma_long"])
            if dead_cross:
                log.info(f"[전략] 🔴 데드크로스 매도 - {stock_code}")
                return True

        return False
