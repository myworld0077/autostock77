"""
래리 윌리엄스 변동성 돌파 전략 — 고급 버전 (LW-VBS v3)

===== 핵심 전략 원리 =====

  1. 전일 변동폭(Range) 계산
       Range = 전일 고가 - 전일 저가

  2. 당일 목표가(Target) 설정
       Target = 당일 시가 + Range × K(0.5)

  3. 장중 목표가 돌파 시 매수 (돌파 매수)
       현재가 >= Target → 매수

  4. 요일 필터 (래리 윌리엄스 통계 기반)
       화요일(Tue) 매수 → 목요일(Thu) 매도
       ※ 화~목 외에는 매수 자제 (수익 극대화)

  5. Higher Lows(직전 저점을 계속 높여가는) 트레일링 스탑
       매수 후 최근 저점(swing low)을 추적
       현재가가 최근 swing low 아래로 내려오면 청산

  6. 매매 횟수 절감 필터 (Quality Filter)
       ① 전일 변동폭이 20일 평균의 80% 이상 (충분한 변동성)
       ② 5일 연속 하락 종목 제외
       ③ 목표가 돌파가 시가 대비 3% 이내 (과도한 상승 진입 방지)
       ④ 전일 거래량이 20일 평균의 1.5배 이상 (거래량 확인)

  7. 손절 기준
       매수 후 -2.5% 이하 시 즉시 손절 (소폭 손실로 끊기)

===== 매도 우선순위 =====
  ① 손절: 현재가 < 매수가 × (1 - 2.5%)
  ② Higher Lows 이탈: 현재가 < swing low
  ③ 목요일 장 마감 전 강제 청산 (화요일 매수 기준)
  ④ 수익 +5% 초과 시 즉시 절반 익절 + 나머지 트레일링

Python 3.9 호환 (Oracle Cloud 환경)
"""
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, Tuple
from strategy.base import BaseStrategy
from utils.logger import log


class VolatilityBreakoutStrategy(BaseStrategy):
    """래리 윌리엄스 변동성 돌파 전략 — LW-VBS v3"""

    name = "래리 윌리엄스 변동성 돌파 v3 (화매수·목매도·HigherLows)"

    def __init__(
        self,
        k: float = 0.5,                  # 변동성 계수 (0.5 = 50%)
        stop_loss_pct: float = -2.5,      # 손절 기준 (%)
        profit_take_pct: float = 5.0,     # 즉시 익절 기준 (%)
        range_ratio_min: float = 0.8,     # 유효 변동폭 최소 비율 (20일 평균 대비)
        vol_ratio_min: float = 1.5,       # 거래량 배율 최소 (20일 평균 대비)
        max_entry_gap_pct: float = 4.0,   # 시가 대비 목표가 최대 괴리 (%) — 과열 진입 방지
        use_day_filter: bool = True,       # 요일 필터 사용 여부
    ):
        self.k = k
        self.stop_loss_pct = stop_loss_pct
        self.profit_take_pct = profit_take_pct
        self.range_ratio_min = range_ratio_min
        self.vol_ratio_min = vol_ratio_min
        self.max_entry_gap_pct = max_entry_gap_pct
        self.use_day_filter = use_day_filter

        # 종목별 상태 추적
        self._peak: Dict[str, float] = {}           # 고점 추적 (트레일링)
        self._swing_low: Dict[str, float] = {}       # Higher Lows 추적
        self._buy_weekday: Dict[str, int] = {}       # 매수 요일 기록
        self._buy_date: Dict[str, str] = {}          # 매수 날짜 기록

    # ─── 내부 유틸 ─────────────────────────────────────────────────

    @staticmethod
    def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """보조 지표 추가"""
        df = df.copy()
        df["range"] = df["high"] - df["low"]
        df["avg_range_20"] = df["range"].rolling(20).mean()
        df["avg_vol_20"] = df["volume"].rolling(20).mean()
        df["ma5"] = df["close"].rolling(5).mean()
        df["ma20"] = df["close"].rolling(20).mean()
        # 5일 수익률 (연속 하락 필터용)
        df["ret5"] = df["close"].pct_change(5)
        return df

    def _calc_target_price(self, df: pd.DataFrame) -> Optional[float]:
        """
        목표가 계산:
          Target = 당일 시가 + 전일 Range × K
        """
        if len(df) < 2:
            return None
        prev = df.iloc[-2]
        curr = df.iloc[-1]
        prev_range = float(prev["high"]) - float(prev["low"])
        if prev_range <= 0:
            return None
        target = float(curr["open"]) + prev_range * self.k
        return target

    def _is_buy_day(self) -> bool:
        """
        요일 필터: 화요일(1) ~ 목요일(3) 매수 허용
        래리 윌리엄스 통계: 화요일 매수가 가장 수익 높음
        """
        if not self.use_day_filter:
            return True
        weekday = datetime.now().weekday()  # 0=월, 1=화, 2=수, 3=목, 4=금
        # 화(1) 우선, 수(2) 허용, 목(3) 청산이므로 매수 자제
        return weekday in (1, 2)  # 화·수요일만 신규 매수

    def _is_sell_day(self, stock_code: str) -> bool:
        """
        목요일 강제 청산 여부:
          화요일 매수 종목 → 목요일 청산
        """
        if not self.use_day_filter:
            return False
        weekday = datetime.now().weekday()
        buy_wd = self._buy_weekday.get(stock_code, -1)
        # 목요일(3)이고, 화·수요일에 매수한 종목
        if weekday == 3 and buy_wd in (1, 2):
            return True
        # 금요일 이상 넘어가면 무조건 청산 (주말 리스크 제거)
        if weekday == 4:
            return True
        return False

    def _calc_swing_low(self, df: pd.DataFrame, window: int = 3) -> Optional[float]:
        """
        최근 swing low 계산 (Higher Lows 추적용)
        최근 window일 중 최저 저가
        """
        if len(df) < window + 1:
            return None
        recent = df.iloc[-(window + 1):-1]
        return float(recent["low"].min())

    def _quality_filter(
        self, stock_code: str, df: pd.DataFrame, target: float
    ) -> Tuple[bool, str]:
        """
        매매 품질 필터 (매매 횟수 절감)
        Returns: (통과여부, 실패사유)
        """
        if len(df) < 21:
            return False, "데이터 부족(21봉 미만)"

        c = df.iloc[-1]
        p = df.iloc[-2]

        avg_range = c.get("avg_range_20", 0)
        avg_vol = c.get("avg_vol_20", 0)

        # ① 변동폭 필터: 전일 범위가 20일 평균의 80% 이상이어야 함
        prev_range = float(p["high"]) - float(p["low"])
        if avg_range > 0 and prev_range < avg_range * self.range_ratio_min:
            return False, f"변동폭 불충분({prev_range:.0f} < {avg_range * self.range_ratio_min:.0f})"

        # ② 5일 연속 하락 종목 제외
        if c.get("ret5") is not None and not pd.isna(c.get("ret5")):
            if float(c["ret5"]) < -0.05:  # 5일간 -5% 이상 하락 중인 종목 제외
                return False, f"5일 연속 하락 추세({float(c['ret5']) * 100:.1f}%)"

        # ③ 시가 대비 목표가 괴리율 필터 (과열 진입 방지)
        open_price = float(c["open"])
        if open_price > 0:
            gap_pct = (target - open_price) / open_price * 100
            if gap_pct > self.max_entry_gap_pct:
                return False, f"목표가 시가 괴리 과대({gap_pct:.1f}% > {self.max_entry_gap_pct}%)"

        # ④ 거래량 확인 (전일 거래량 기준)
        prev_vol = float(p["volume"])
        if avg_vol > 0 and prev_vol < avg_vol * self.vol_ratio_min:
            return False, f"전일 거래량 부족({prev_vol:.0f} < {avg_vol * self.vol_ratio_min:.0f})"

        return True, ""

    # ─── 매수 판단 ──────────────────────────────────────────────────

    def should_buy(self, stock_code: str, df: pd.DataFrame, current_price: int) -> bool:
        """
        래리 윌리엄스 변동성 돌파 매수 판단

        매수 조건:
          1. 화·수요일 (요일 필터)
          2. 현재가 >= 당일 시가 + 전일 변동폭 × 0.5 (목표가 돌파)
          3. 품질 필터 통과 (변동폭·거래량·괴리율·연속하락 체크)
        """
        # 요일 필터
        if not self._is_buy_day():
            return False

        if len(df) < 2:
            return False

        df = self._add_indicators(df)

        # 목표가 계산
        target = self._calc_target_price(df)
        if target is None:
            return False

        # 목표가 돌파 확인
        if current_price < target:
            return False

        # 품질 필터
        passed, reason = self._quality_filter(stock_code, df, target)
        if not passed:
            log.info(f"[전략] ⬜ 매수 보류 {stock_code} - {reason} (목표가:{target:,.0f})")
            return False

        # 매수 요일·날짜 기록
        self._buy_weekday[stock_code] = datetime.now().weekday()
        self._buy_date[stock_code] = datetime.now().strftime("%Y-%m-%d")

        # 초기 swing low 설정
        swing_low = self._calc_swing_low(df)
        if swing_low:
            self._swing_low[stock_code] = swing_low

        weekday_name = ["월", "화", "수", "목", "금"][datetime.now().weekday()]
        c = df.iloc[-1]
        prev_range = float(df.iloc[-2]["high"]) - float(df.iloc[-2]["low"])
        log.info(
            f"[전략] 🟢 변동성 돌파 매수 - {stock_code} "
            f"({weekday_name}요일 | 현재가:{current_price:,} >= 목표가:{target:,.0f} | "
            f"전일변동폭:{prev_range:,.0f} | 시가:{int(c['open']):,})"
        )
        return True

    # ─── 매도 판단 ──────────────────────────────────────────────────

    def should_sell(
        self,
        stock_code: str,
        df: pd.DataFrame,
        current_price: int,
        avg_price: int,
    ) -> bool:
        """
        매도 우선순위:
          ① 손절: 수익률 < -2.5%
          ② 목요일 강제 청산 (화·수요일 매수 기준)
          ③ Higher Lows 이탈: 현재가 < swing low
          ④ 즉시 익절: 수익률 >= +5%
          ⑤ 수익 보호 트레일링: 수익 2%+ 이후 고점 대비 -2% 하락
        """
        if avg_price <= 0:
            return False

        profit_rate = (current_price - avg_price) / avg_price * 100

        # ① 손절: -2.5% 이하 (소폭 손실 즉시 끊기)
        if profit_rate <= self.stop_loss_pct:
            log.info(
                f"[전략] 🔴 손절 - {stock_code} "
                f"({profit_rate:.1f}% ≤ {self.stop_loss_pct}%)"
            )
            self._cleanup(stock_code)
            return True

        # ② 목요일 강제 청산 (화·수 매수 종목)
        if self._is_sell_day(stock_code):
            weekday_name = ["월", "화", "수", "목", "금"][datetime.now().weekday()]
            log.info(
                f"[전략] 📅 {weekday_name}요일 강제 청산 - {stock_code} "
                f"(수익률 {profit_rate:.1f}%)"
            )
            self._cleanup(stock_code)
            return True

        # ③ Higher Lows 이탈: 현재가 < swing low
        if len(df) >= 4:
            df = self._add_indicators(df)
            new_swing = self._calc_swing_low(df)
            old_swing = self._swing_low.get(stock_code)

            if new_swing and old_swing:
                # Higher Lows: 새 저점이 이전 저점보다 높아야 함 (상승 추세 유지)
                if new_swing > old_swing:
                    self._swing_low[stock_code] = new_swing  # 저점 갱신 (Higher Low 확인)

                # 현재가가 swing low 아래 → 추세 붕괴 → 청산
                effective_swing = self._swing_low[stock_code]
                if current_price < effective_swing and profit_rate > 0:
                    log.info(
                        f"[전략] 📉 Higher Lows 이탈 - {stock_code} "
                        f"(현재가:{current_price:,} < swing low:{effective_swing:,.0f} | 수익 {profit_rate:.1f}%)"
                    )
                    self._cleanup(stock_code)
                    return True

        # ④ 즉시 익절: 수익률 >= +5%
        if profit_rate >= self.profit_take_pct:
            log.info(
                f"[전략] 💰 즉시 익절 - {stock_code} "
                f"(수익률 {profit_rate:.1f}% >= {self.profit_take_pct}%)"
            )
            self._cleanup(stock_code)
            return True

        # ⑤ 수익 보호 트레일링 (수익 2% 이상 진입 후 고점 -2% 이탈)
        peak = self._peak.get(stock_code, float(current_price))
        if current_price > peak:
            self._peak[stock_code] = float(current_price)
            peak = float(current_price)

        if profit_rate >= 2.0:
            drop_from_peak = (peak - current_price) / peak * 100
            if drop_from_peak >= 2.0:
                log.info(
                    f"[전략] 📉 트레일링 스탑 - {stock_code} "
                    f"(수익 {profit_rate:.1f}% | 고점 {peak:,.0f}원 → -{drop_from_peak:.1f}%)"
                )
                self._cleanup(stock_code)
                return True

        return False

    def _cleanup(self, stock_code: str):
        """종목 상태 초기화"""
        self._peak.pop(stock_code, None)
        self._swing_low.pop(stock_code, None)
        self._buy_weekday.pop(stock_code, None)
        self._buy_date.pop(stock_code, None)
