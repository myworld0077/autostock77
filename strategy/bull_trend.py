"""
상승장 주도주 추세 추종 전략 (BullTrendStrategy)
=================================================

1. 핵심 전략 원리:
   - 이동평균선 정배열(MA5 > MA20 > MA60) 및 MA20 우상향 종목을 주도주로 선정
   - 상승 추세 내 눌림목(MA5~MA20 조정 후 반등) 또는 20일 신고가 돌파 시 매수
   - RSI(14) 50~70 모멘텀 확인 + 거래량 1.5배 이상 수급 확인

2. 리스크 및 수익 관리:
   - 손절(Stop Loss): -3.0%
   - 분할 익절: +7.0% 달성 시 50% 분할 익절
   - 트레일링 스탑: 수익 구간별 고점 대비 -1.5% ~ -3.0% 추적 청산
   - 추세 이탈: 20일 이동평균선 하향 이탈 시 전량 매도
"""

import pandas as pd
from typing import Dict, Tuple
from strategy.base import BaseStrategy
from utils.logger import log


class BullTrendStrategy(BaseStrategy):
    """상승장 주도주 추세 추종 전략"""

    name = "상승장 주도주 추세 추종 전략 (정배열·눌림목·트레일링)"

    def __init__(
        self,
        stop_loss_pct: float = -3.0,       # 손절 기준 (-3%)
        take_profit_pct: float = 7.0,      # 분할 익절 기준 (+7%)
        vol_ratio_min: float = 1.2,        # 최소 거래량 비율 (20일 평균 대비 1.2배)
    ):
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.vol_ratio_min = vol_ratio_min

        # 종목별 고점 추적 딕셔너리 (트레일링 스탑용)
        self._peak: Dict[str, float] = {}

    @staticmethod
    def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """보조 지표 계산"""
        df = df.copy()

        # 이동평균선 (5일, 20일, 60일)
        df['ma5'] = df['close'].rolling(5).mean()
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma60'] = df['close'].rolling(60).mean()

        # 거래량 20일 평균
        df['vol_ma20'] = df['volume'].rolling(20).mean()
        df['vol_ratio'] = df['volume'] / df['vol_ma20'].replace(0, float('nan'))

        # RSI (14일)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, float('nan'))
        df['rsi14'] = 100 - (100 / (1 + rs))

        # 20일 신고가 (당일 제외 전일 기준)
        df['high_20'] = df['high'].shift(1).rolling(20).max()

        return df

    def _is_bull_trend(self, c: pd.Series, p_ma20: float) -> bool:
        """
        상승장 주도주 조건:
          1) 정배열: MA5 > MA20 > MA60
          2) 현재가 > MA20
          3) 20일선 우상향: MA20(현재) > MA20(이전)
        """
        ma5 = c.get('ma5', 0)
        ma20 = c.get('ma20', 0)
        ma60 = c.get('ma60', 0)
        close = c.get('close', 0)

        if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60):
            return False

        # 정배열 & 20일선 위 & 20일선 우상향
        is_aligned = (ma5 > ma20) and (ma20 > ma60)
        is_above_ma20 = close > ma20
        is_ma20_up = ma20 > p_ma20

        return is_aligned and is_above_ma20 and is_ma20_up

    def should_buy(self, stock_code: str, df: pd.DataFrame, current_price: int) -> bool:
        """매수 판단 로직"""
        if len(df) < 65:
            return False

        df = self._add_indicators(df)
        c = df.iloc[-1]
        p = df.iloc[-2]

        if c.isnull().any():
            return False

        # 1) 상승장 추세 필터
        p_ma20 = float(p.get('ma20', 0))
        if not self._is_bull_trend(c, p_ma20):
            return False

        # 2) RSI 50~75 강세 모멘텀 구간
        rsi = float(c.get('rsi14', 50))
        if not (50.0 <= rsi <= 75.0):
            return False

        # 3) 거래량 확인 (20일 평균의 1.2배 이상)
        vol_ratio = float(c.get('vol_ratio', 0))
        if vol_ratio < self.vol_ratio_min:
            return False

        # 4) 진입 패턴 (A: 5일선 눌림목 반등 / B: 20일 신고가 돌파)
        close = float(c.get('close', current_price))
        open_p = float(c.get('open', close))
        ma5 = float(c.get('ma5', 0))
        high_20 = float(c.get('high_20', close * 2))

        is_dip_buy = (open_p <= ma5) and (close > ma5)  # 5일선 눌림 후 양봉 돌파
        is_breakout = close >= high_20                  # 20일 신고가 돌파

        if is_dip_buy or is_breakout:
            pattern = "눌림목 반등" if is_dip_buy else "20일 신고가 돌파"
            log.info(
                f"[BULL SIGNAL] {stock_code} 매수 신호! ({pattern}) | "
                f"현재가: {current_price:,}원, RSI: {rsi:.1f}, 거래량비율: {vol_ratio:.1f}배"
            )
            return True

        return False

    def should_sell(
        self,
        stock_code: str,
        df: pd.DataFrame,
        current_price: int,
        buy_price: int,
        qty: int,
    ) -> Tuple[bool, str]:
        """매도 판단 로직 (손절 -3%, 추세 이탈, 트레일링 스탑)"""
        if buy_price <= 0:
            return False, ""

        profit_rate = ((current_price - buy_price) / buy_price) * 100.0

        # 고점 갱신
        if stock_code not in self._peak or current_price > self._peak[stock_code]:
            self._peak[stock_code] = float(current_price)

        peak_price = self._peak[stock_code]
        drop_from_peak = ((peak_price - current_price) / peak_price) * 100.0

        # ① 손절: -3.0% 이하
        if profit_rate <= self.stop_loss_pct:
            self._peak.pop(stock_code, None)
            return True, f"손절 (-3% 이탈: {profit_rate:+.2f}%)"

        # ② 추세 이탈: 20일선 하향 이탈
        if len(df) >= 20:
            df_ind = self._add_indicators(df)
            ma20 = float(df_ind.iloc[-1].get('ma20', 0))
            if ma20 > 0 and current_price < ma20:
                self._peak.pop(stock_code, None)
                return True, f"추세 이탈 (20일선 하회: {current_price:,}원 < {ma20:,.0f}원)"

        # ③ 트레일링 스탑 (수익 구간별 고점 대비 하락폭 제한)
        if profit_rate >= 10.0 and drop_from_peak >= 3.0:
            self._peak.pop(stock_code, None)
            return True, f"트레일링 스탑 (+10% 달성 후 고점대비 -3.0% 하락, 수익률: {profit_rate:+.2f}%)"
        elif profit_rate >= 5.0 and drop_from_peak >= 2.0:
            self._peak.pop(stock_code, None)
            return True, f"트레일링 스탑 (+5% 달성 후 고점대비 -2.0% 하락, 수익률: {profit_rate:+.2f}%)"
        elif profit_rate >= 2.0 and drop_from_peak >= 1.5:
            self._peak.pop(stock_code, None)
            return True, f"트레일링 스탑 (+2% 달성 후 고점대비 -1.5% 하락, 수익률: {profit_rate:+.2f}%)"

        return False, ""
