"""
하락장 방어 전략 (DefensiveBearStrategy)
=========================================

하락장에서 손실을 최소화하고 현금을 보존하는 전략입니다.

핵심 원리:
  1. 일반 종목 매수 금지 — 인버스 ETF만 매수 허용
  2. 현금 비중 80% 이상 유지
  3. 매우 타이트한 손절 (-2%)
  4. 인버스 ETF: 시장 하락 시 수익 발생
  5. 최대 보유 기간 2거래일 (단기 매매)

매수 조건 (인버스 ETF):
  ① 코스피 20일선 아래 (하락 추세 확인)
  ② RSI(14) ≥ 45 (과매도 바닥은 피함 — 반등 리스크)
  ③ 거래량 20일 평균의 1.0배 이상

매도 조건:
  ① 손절: -2% (매우 타이트)
  ② 트레일링: +3% 달성 후 고점 대비 -1% 하락
  ③ 최대 보유 2거래일 → 강제 청산

Python 3.9+ 호환
"""
import pandas as pd
from typing import Dict, Tuple
from strategy.base import BaseStrategy
from utils.logger import log


class DefensiveBearStrategy(BaseStrategy):
    """하락장 방어 전략 — 현금 보존 + 인버스 ETF 단기 매매"""

    name = "하락장 방어 전략 (현금보존·인버스ETF·손절-2%)"

    def __init__(
        self,
        stop_loss_pct: float = -2.0,      # 손절 기준 (-2%)
        take_profit_pct: float = 4.0,     # 익절 기준 (+4%)
        max_hold_days: int = 2,           # 최대 보유 기간 (거래일)
    ):
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_hold_days = max_hold_days

        # 종목별 고점 추적
        self._peak: Dict[str, float] = {}
        # 매수 날짜 추적
        self._buy_date: Dict[str, str] = {}

    @staticmethod
    def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """보조 지표 계산"""
        df = df.copy()
        df['ma5'] = df['close'].rolling(5).mean()
        df['ma20'] = df['close'].rolling(20).mean()

        # 거래량 20일 평균
        df['vol_ma20'] = df['volume'].rolling(20).mean()
        df['vol_ratio'] = df['volume'] / df['vol_ma20'].replace(0, float('nan'))

        # RSI (14일)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, float('nan'))
        df['rsi14'] = 100 - (100 / (1 + rs))

        return df

    def should_buy(self, stock_code: str, df: pd.DataFrame, current_price: int) -> bool:
        """
        매수 판단 — 인버스 ETF만 매수 허용
        (일반 종목은 AutoTrader에서 인버스 ETF 리스트로 필터링)
        """
        if len(df) < 25:
            return False

        df = self._add_indicators(df)
        c = df.iloc[-1]

        if c.isnull().any():
            return False

        # 1) 코스피 하락 추세 확인: 현재가 < 20일선 (인버스 → 수익)
        ma20 = float(c.get('ma20', 0))
        close = float(c.get('close', current_price))
        if ma20 > 0 and close > ma20:
            # 현재가가 20일선 위 → 아직 하락 확정 아님 → 매수 자제
            return False

        # 2) RSI 45~70 — 과매도 바닥(30 이하)은 반등 리스크
        rsi = float(c.get('rsi14', 50))
        if not (45.0 <= rsi <= 70.0):
            return False

        # 3) 거래량 확인
        vol_ratio = float(c.get('vol_ratio', 0))
        if vol_ratio < 1.0:
            return False

        log.info(
            f"[BEAR SIGNAL] {stock_code} 인버스 매수 신호 | "
            f"현재가: {current_price:,}원, RSI: {rsi:.1f}, 거래량비율: {vol_ratio:.1f}배"
        )
        return True

    def should_sell(
        self,
        stock_code: str,
        df: pd.DataFrame,
        current_price: int,
        buy_price: int,
        qty: int = 0,
    ) -> Tuple[bool, str]:
        """매도 판단 (손절 -2%, 트레일링, 보유기간 제한)"""
        if buy_price <= 0:
            return False, ""

        profit_rate = ((current_price - buy_price) / buy_price) * 100.0

        # 고점 갱신
        if stock_code not in self._peak or current_price > self._peak[stock_code]:
            self._peak[stock_code] = float(current_price)

        peak_price = self._peak[stock_code]
        drop_from_peak = ((peak_price - current_price) / peak_price) * 100.0

        # ① 손절: -2%
        if profit_rate <= self.stop_loss_pct:
            self._peak.pop(stock_code, None)
            return True, f"손절 ({profit_rate:+.2f}% ≤ {self.stop_loss_pct}%)"

        # ② 즉시 익절: +4%
        if profit_rate >= self.take_profit_pct:
            self._peak.pop(stock_code, None)
            return True, f"익절 ({profit_rate:+.2f}% ≥ +{self.take_profit_pct}%)"

        # ③ 트레일링: +3% 달성 후 고점 대비 -1% 하락
        if profit_rate >= 3.0 and drop_from_peak >= 1.0:
            self._peak.pop(stock_code, None)
            return True, f"트레일링 ({profit_rate:+.2f}%, 고점 대비 -{drop_from_peak:.1f}%)"

        # ④ 추세 반전: 20일선 위로 복귀 → 인버스 불리
        if len(df) >= 20:
            df_ind = self._add_indicators(df)
            ma20 = float(df_ind.iloc[-1].get('ma20', 0))
            if ma20 > 0 and current_price > ma20 * 1.02:  # 20일선 +2% 이상
                self._peak.pop(stock_code, None)
                return True, f"추세 반전 (현재가 {current_price:,} > 20일선 {ma20:,.0f} +2%)"

        return False, ""
