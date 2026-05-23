"""
매매 전략 베이스 클래스
모든 전략은 이 클래스를 상속하여 구현합니다.
"""
from abc import ABC, abstractmethod
import pandas as pd


class BaseStrategy(ABC):
    """전략 추상 클래스"""

    name: str = "BaseStrategy"

    @abstractmethod
    def should_buy(self, stock_code: str, df: pd.DataFrame, current_price: int) -> bool:
        """
        매수 조건 판단

        Args:
            stock_code: 종목코드
            df: OHLCV DataFrame
            current_price: 현재가

        Returns:
            True = 매수 신호
        """
        ...

    @abstractmethod
    def should_sell(self, stock_code: str, df: pd.DataFrame, current_price: int,
                    avg_price: int) -> bool:
        """
        매도 조건 판단

        Args:
            stock_code: 종목코드
            df: OHLCV DataFrame
            current_price: 현재가
            avg_price: 평균 매입 단가

        Returns:
            True = 매도 신호
        """
        ...

    def __repr__(self):
        return f"<Strategy: {self.name}>"
