"""
변동성 돌파 전략 (래리 윌리엄스)

매수 조건: 당일 시가 + 전일 레인지(고가-저가) × K 를 돌파하면 매수
매도 조건: 당일 종가에 전량 매도 (익일 시가에 매도)
"""
import pandas as pd
from typing import Optional
from strategy.base import BaseStrategy
from utils.logger import log


class VolatilityBreakoutStrategy(BaseStrategy):
    """변동성 돌파 전략"""

    name = "Volatility Breakout"

    def __init__(self, k: float = 0.5):
        """
        Args:
            k: 변동성 계수 (0.0 ~ 1.0). 클수록 보수적.
        """
        self.k = k

    def _calc_target_price(self, df: pd.DataFrame) -> Optional[float]:
        """목표가 계산: 당일 시가 + 전일 레인지 × K"""
        if len(df) < 2:
            return None

        prev = df.iloc[-2]
        curr = df.iloc[-1]
        prev_range = prev["high"] - prev["low"]
        target = curr["open"] + prev_range * self.k
        return target

    def should_buy(self, stock_code: str, df: pd.DataFrame, current_price: int) -> bool:
        target = self._calc_target_price(df)
        if target is None:
            return False

        if current_price >= target:
            log.info(f"[전략] 🟢 변동성 돌파 매수 - {stock_code} "
                     f"(현재가: {current_price:,} ≥ 목표가: {target:,.0f})")
            return True
        return False

    def should_sell(self, stock_code: str, df: pd.DataFrame, current_price: int,
                    avg_price: int) -> bool:
        """다음날 시가에 전량 매도 (간단 구현: 보유 중이면 항상 매도 신호)"""
        # 실전에서는 스케줄러가 09:01에 전일 매수분을 매도
        # 여기서는 should_sell이 호출되면 매도하도록 설계
        if avg_price > 0:
            profit_rate = ((current_price - avg_price) / avg_price) * 100
            log.info(f"[전략] 🔴 변동성 돌파 매도 - {stock_code} "
                     f"(수익률: {profit_rate:.1f}%)")
            return True
        return False
