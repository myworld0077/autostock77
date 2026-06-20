"""
복합 지표 매매 전략 — 보완 v2 (모의투자 1개월 성과 반영)

=== 성과 분석 기반 개편 내용 ===

  [문제점 → 개선]
  ① 손절 -5% 너무 관대  →  -3%로 재조정 (손실 한도 축소)
  ② 매수 조건 3/4점     →  4/4점 완벽 조건만 매수 (진입 품질 향상)
  ③ 수익 0~3% 트레일링 없음 →  1~3%에서도 고점 -1.5% 시 조기 청산 추가
  ④ 상승장 완화 조건 축소  →  상승장도 -5% 손절 유지 (완화 제거)

=== 트레일링 스탑 단계 (v2) ===

  수익 0~1%  → 손절 구간 (-3% 고정)
  수익 1~3%  → 고점 대비 -1.5% 하락 시 청산 (조기 이익 확보)
  수익 3~8%  → 고점 대비 -2.0% 하락 시 청산
  수익 8~15% → 고점 대비 -3.0% 하락 시 청산
  수익 15%+  → 고점 대비 -4.0% 하락 시 청산

=== 매수 조건 (4개 모두 충족 시만 매수) ===
  ① BB 하단 근접 (동적 여유폭)
  ② MACD 골든크로스
  ③ RSV 과매도 (≤30)
  ④ 상승장 추세 (MA20 위 + MACD 크로스) 또는 거래량 급증
"""
import pandas as pd
from typing import Dict
from strategy.base import BaseStrategy
from utils.logger import log


class Kospi200ComplexStrategy(BaseStrategy):
    """
    코스피 200 비대칭 리스크 전략 v2 (모의투자 성과 반영)
    - 손절 -3% (기존 -5%에서 강화)
    - 매수 점수 4/4점 완벽 조건
    - 조기 수익 보호 트레일링 추가
    """

    name = "KOSPI 200 비대칭 리스크 v2 (손절강화·매수품질향상)"

    def __init__(
        self,
        stop_loss_pct: float = -3.0,     # 손절 기준 (%) — -5 → -3으로 타이트하게
    ):
        self.stop_loss_pct = stop_loss_pct
        # 종목별 고점 추적 딕셔너리 (트레일링 스탑)
        self._peak: Dict[str, float] = {}

    # ─── 보조지표 ────────────────────────────────────────────────

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # Bollinger Bands (20일, 2σ)
        df['bb_mid']   = df['close'].rolling(20).mean()
        df['bb_std']   = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + df['bb_std'] * 2
        df['bb_lower'] = df['bb_mid'] - df['bb_std'] * 2

        # MACD (12, 26, 9)
        df['ema12']       = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26']       = df['close'].ewm(span=26, adjust=False).mean()
        df['macd']        = df['ema12'] - df['ema26']
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()

        # Stochastic %K / RSV (14일) — 0 분모 방지
        h14 = df['high'].rolling(14).max()
        l14 = df['low'].rolling(14).min()
        denom = (h14 - l14).replace(0, float('nan'))
        df['rsv'] = ((df['close'] - l14) / denom * 100).fillna(50.0)

        # 추세 이동평균
        df['ma20']  = df['close'].rolling(20).mean()
        df['ma60']  = df['close'].rolling(60).mean()

        # 거래량 20일 평균 대비 비율
        df['vol_ratio'] = df['volume'] / df['volume'].rolling(20).mean()

        # 일평균 변동폭 20일 평균 (BB 여유폭 동적 계산용)
        df['avg_range'] = ((df['high'] - df['low']) / df['close'] * 100).rolling(20).mean()

        return df

    # ─── 상승장 판단 ─────────────────────────────────────────────

    def _is_bull(self, df: pd.DataFrame) -> bool:
        """
        상승장 조건 (3개 중 2개 이상):
          ① MA20 > MA60
          ② 현재가 > MA20
          ③ MA60 최근 5일 기울기 양수
        """
        if len(df) < 65:
            return False
        c = df.iloc[-1]
        score = 0
        if c['ma20'] > c['ma60']:
            score += 1
        if c['close'] > c['ma20']:
            score += 1
        if df['ma60'].iloc[-1] > df['ma60'].iloc[-6]:
            score += 1
        return score >= 2

    # ─── 트레일링 스탑 기준 계산 (v2: 조기 수익 보호 추가) ──────

    @staticmethod
    def _trailing_threshold(profit_rate: float) -> float:
        """
        수익 단계별 트레일링 스탑 기준 (고점 대비 허용 하락폭) v2

          0~1%:  손절 구간 (트레일링 미적용)
          1~3%:  고점 대비 -1.5% (조기 수익 보호 — 신규 추가)
          3~8%:  고점 대비 -2.0%
          8~15%: 고점 대비 -3.0%
          15%+:  고점 대비 -4.0% (기존 -5 → -4로 타이트하게)
        """
        if profit_rate < 1.0:
            return float('inf')   # 손절 구간 — 트레일링 미적용
        elif profit_rate < 3.0:
            return 1.5            # 신규: 소폭 수익도 보호
        elif profit_rate < 8.0:
            return 2.0
        elif profit_rate < 15.0:
            return 3.0
        else:
            return 4.0            # 대세 상승 구간 (기존 5 → 4로 강화)

    # ─── 매수 판단 (v2: 4/4점 완벽 조건) ────────────────────────

    def should_buy(self, stock_code: str, df: pd.DataFrame, current_price: int) -> bool:
        if len(df) < 26:
            return False

        df = self._add_indicators(df)
        c = df.iloc[-1]
        p = df.iloc[-2]

        if c.isnull().any():
            return False

        bull = self._is_bull(df)

        # 동적 BB 여유폭 (일평균 변동폭 반영)
        avg_range = c.get('avg_range', 1.5)
        if pd.isna(avg_range):
            avg_range = 1.5
        bb_margin = min(0.05 + max(avg_range - 1.5, 0) * 0.02, 0.08)

        # ① BB 하단 근접 (동적 여유폭)
        bb_ok = current_price <= c['bb_lower'] * (1 + bb_margin)

        # ② MACD 골든크로스
        macd_cross = p['macd'] < p['macd_signal'] and c['macd'] >= c['macd_signal']

        # ③ RSV 과매도 (≤30)
        rsv_ok = c['rsv'] <= 30

        # ④ 추세 조건: 상승장 추종 OR 거래량 급증(2배 이상)
        vol_surge = (c.get('vol_ratio', 1.0) >= 2.0) if not pd.isna(c.get('vol_ratio', float('nan'))) else False
        bull_follow = (bull and c['close'] > c['ma20'] and macd_cross) or (vol_surge and macd_cross)

        score = sum([bb_ok, macd_cross, rsv_ok, bull_follow])

        # ★ v2 핵심 변경: 3점 → 4점 만점 모두 충족 시만 매수 (진입 품질 최대화)
        if score >= 4:
            log.info(
                f"[전략] 🟢 매수 - {stock_code} "
                f"({'상승장' if bull else '횡보장'} | 점수:{score}/4 | "
                f"BB:{bb_ok} MACD:{macd_cross} RSV:{c['rsv']:.0f} 추세:{bull_follow})"
            )
            return True

        # 3점이면 조건 로그만 남기고 패스 (디버깅용)
        if score == 3:
            log.info(
                f"[전략] ⬜ 매수 보류 - {stock_code} "
                f"(점수:{score}/4 — 4점 미달 | BB:{bb_ok} MACD:{macd_cross} RSV:{c['rsv']:.0f} 추세:{bull_follow})"
            )
        return False

    # ─── 매도 판단 (v2: 손절 -3% 고정, 트레일링 강화) ────────────

    def should_sell(
        self,
        stock_code: str,
        df: pd.DataFrame,
        current_price: int,
        avg_price: int,
    ) -> bool:
        if avg_price <= 0:
            return False

        profit_rate = (current_price - avg_price) / avg_price * 100

        # 지표 계산
        if len(df) >= 26:
            df = self._add_indicators(df)

        # ╔══════════════════════════════════════════════════════════╗
        # ║  하방 차단 ①: 고정 손절 -3% (원금 보호 최우선)          ║
        # ╚══════════════════════════════════════════════════════════╝
        if profit_rate <= self.stop_loss_pct:
            log.info(
                f"[전략] 🔴 손절 - {stock_code} "
                f"({profit_rate:.1f}% ≤ {self.stop_loss_pct}%)"
            )
            self._peak.pop(stock_code, None)
            return True

        # ╔══════════════════════════════════════════════════════════╗
        # ║  하방 차단 ②: 트레일링 스탑 v2 (조기 수익 보호 강화)    ║
        # ╚══════════════════════════════════════════════════════════╝
        peak = self._peak.get(stock_code, float(current_price))
        if current_price > peak:
            peak = float(current_price)
            self._peak[stock_code] = peak

        drop_from_peak = (peak - current_price) / peak * 100
        ts_threshold   = self._trailing_threshold(profit_rate)

        if drop_from_peak >= ts_threshold:
            log.info(
                f"[전략] 📉 트레일링 스탑 v2 - {stock_code} "
                f"(수익 {profit_rate:.1f}% | 고점 {peak:,.0f}원 → "
                f"-{drop_from_peak:.1f}% | 기준 -{ts_threshold:.1f}%)"
            )
            self._peak.pop(stock_code, None)
            return True

        # ╔══════════════════════════════════════════════════════════╗
        # ║  지표 매도: 횡보장 2개 / 상승장 3개 조건 충족 시 청산   ║
        # ╚══════════════════════════════════════════════════════════╝
        if len(df) < 26 or 'bb_upper' not in df.columns:
            return False

        c = df.iloc[-1]
        p = df.iloc[-2]

        bb_upper_touch = current_price >= c['bb_upper']
        macd_dead      = p['macd'] > p['macd_signal'] and c['macd'] <= c['macd_signal']
        rsv_overbought = c['rsv'] >= 70

        bull = self._is_bull(df) if len(df) >= 65 else False

        if bull:
            # 상승장: 3개 모두 + 수익 10% 이상
            if bb_upper_touch and macd_dead and rsv_overbought and profit_rate >= 10.0:
                log.info(
                    f"[전략] 📊 상승장 지표 청산 - {stock_code} "
                    f"(BB상단+MACD데드+RSV과매수 | 수익 {profit_rate:.1f}%)"
                )
                self._peak.pop(stock_code, None)
                return True
        else:
            # 횡보장: 2개 이상 충족
            signal_count = sum([bb_upper_touch, macd_dead, rsv_overbought])
            if signal_count >= 2:
                reason = "+".join(filter(None, [
                    "BB상단" if bb_upper_touch else "",
                    "MACD데드" if macd_dead else "",
                    "RSV과매수" if rsv_overbought else "",
                ]))
                log.info(f"[전략] 📊 횡보장 지표 매도 - {stock_code} ({reason})")
                self._peak.pop(stock_code, None)
                return True

        return False
