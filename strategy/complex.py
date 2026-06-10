"""
복합 지표 매매 전략 — 비대칭 리스크 구조
"상승은 열어두고, 하방은 닫는다" (손실최소·이익최대)

=== 설계 철학 ===

  [하방 차단]
    ① 손절: 매수가 대비 -3% → 즉시 전량 청산 (손실 한도 고정)
    ② 수익권 진입 후: 수익 단계별 트레일링 스탑으로 이익 보호

  [상방 개방]
    ① 고정 익절(take-profit) 없음 → 추세가 살아있는 한 보유 유지
    ② 수익이 커질수록 트레일링 스탑 여유를 확대
       → 작은 눌림목에 청산되지 않고 큰 추세 탑승 가능
    ③ 지표 매도: BB상단 + MACD데드크로스 + RSV과매수 3개 모두 일치 시만 청산
       (단일 조건으로 섣불리 매도 금지)

=== 트레일링 스탑 단계 (2026년 1~5월 일평균 변동폭 1.2~1.8% 반영) ===

  수익 0~3%  → 손절 -3% (원금 보호 구간)
  수익 3~8%  → 고점 대비 -2.0% 하락 시 청산 (이익 확보)
  수익 8~15% → 고점 대비 -3.0% 하락 시 청산 (추세 추종)
  수익 15%+  → 고점 대비 -5.0% 하락 시 청산 (대세 상승 탑승)

=== 상승장 감지 (MA 배열) ===
  20일 MA > 60일 MA + 현재가 > 20일 MA + 60일 MA 기울기 양수
  → 상승장 확인 시 손절 완화(-3% → -5%), 지표 매도 임계 강화
"""
import pandas as pd
from typing import Dict
from strategy.base import BaseStrategy
from utils.logger import log


class Kospi200ComplexStrategy(BaseStrategy):
    """
    코스피 200 비대칭 리스크 전략
    - 하방 차단: 손절 -3%, 수익권 트레일링 스탑
    - 상방 개방: 고정 익절 없음, 추세 지속 시 무한 보유
    """

    name = "KOSPI 200 비대칭 리스크 (상방개방·하방차단)"

    def __init__(
        self,
        stop_loss_normal: float = -5.0,    # 황보장 손절 기준 (%) ← -3→-5%로 완화 (불필요한 조기 손절 방지)
        stop_loss_bull:   float = -7.0,    # 상승장 손절 기준 (완화)
    ):
        self.stop_loss_normal = stop_loss_normal
        self.stop_loss_bull   = stop_loss_bull
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

    # ─── 트레일링 스탑 기준 계산 ─────────────────────────────────

    @staticmethod
    def _trailing_threshold(profit_rate: float) -> float:
        """
        수익 단계별 트레일링 스탑 기준 (고점 대비 허용 하락폭)
        수익이 클수록 여유를 더 줘서 큰 추세를 탈 수 있게 함

          0~3%:  손절 구간 (트레일링 미적용)
          3~8%:  고점 대비 -2.0%
          8~15%: 고점 대비 -3.0%
          15%+:  고점 대비 -5.0%
        """
        if profit_rate < 3.0:
            return float('inf')   # 손절 구간 — 트레일링 미적용
        elif profit_rate < 8.0:
            return 2.0
        elif profit_rate < 15.0:
            return 3.0
        else:
            return 5.0            # 대세 상승 구간 — 여유 최대

    # ─── 매수 판단 ──────────────────────────────────────────────

    def should_buy(self, stock_code: str, df: pd.DataFrame, current_price: int) -> bool:
        if len(df) < 26:
            return False

        df = self._add_indicators(df)
        c = df.iloc[-1]
        p = df.iloc[-2]

        if c.isnull().any():
            return False

        bull = self._is_bull(df)

        # 동적 BB 여유폭 (2026년 일평균 변동폭 반영)
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
        # ④ 상승장 추세 추종 (MA20 위 + MACD 크로스)
        bull_follow = bull and c['close'] > c['ma20'] and macd_cross

        score = sum([bb_ok, macd_cross, rsv_ok, bull_follow])

        # 파산 방지: 매수 신호 품질 향상 (2점 → 3점 이상으로 임계값 상향)
        # 매수 횟수 줄이고 신호 품질 높여 손절 빈도 저하
        if score >= 3:
            log.info(
                f"[전략] 🟢 매수 - {stock_code} "
                f"({'상승장' if bull else '황보장'} | 점수:{score}/4 | "
                f"BB:{bb_ok} MACD:{macd_cross} RSV:{c['rsv']:.0f} 추세:{bull_follow})"
            )
            return True
        return False

    # ─── 매도 판단 ──────────────────────────────────────────────

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

        # 지표 계산 (ma20/ma60 포함) — _is_bull 호출 전에 먼저 수행
        if len(df) >= 26:
            df = self._add_indicators(df)

        # 상승장 여부 (지표 계산 후 호출)
        bull = self._is_bull(df) if len(df) >= 65 else False

        # ╔══════════════════════════════════════════════════════════╗
        # ║  하방 차단 ①: 고정 손절 (원금 보호)                     ║
        # ╚══════════════════════════════════════════════════════════╝
        stop = self.stop_loss_bull if bull else self.stop_loss_normal
        if profit_rate <= stop:
            log.info(
                f"[전략] 🔴 손절 - {stock_code} "
                f"({profit_rate:.1f}% ≤ {stop}% | {'상승장' if bull else '횡보장'})"
            )
            self._peak.pop(stock_code, None)
            return True

        # ╔══════════════════════════════════════════════════════════╗
        # ║  하방 차단 ②: 트레일링 스탑 (이익 보호)                  ║
        # ║  수익 단계별 허용 하락폭 → 상방은 무한 개방 유지          ║
        # ╚══════════════════════════════════════════════════════════╝
        # 고점 갱신
        peak = self._peak.get(stock_code, float(current_price))
        if current_price > peak:
            peak = float(current_price)
            self._peak[stock_code] = peak

        drop_from_peak = (peak - current_price) / peak * 100
        ts_threshold   = self._trailing_threshold(profit_rate)

        if drop_from_peak >= ts_threshold:
            log.info(
                f"[전략] 📉 트레일링 스탑 - {stock_code} "
                f"(수익 {profit_rate:.1f}% | 고점 {peak:,.0f}원 → "
                f"-{drop_from_peak:.1f}% | 기준 -{ts_threshold:.1f}%)"
            )
            self._peak.pop(stock_code, None)
            return True

        # ╔══════════════════════════════════════════════════════════╗
        # ║  지표 매도 (상방 개방 원칙 — 3개 조건 모두 충족 시만)    ║
        # ║  단일 조건(BB상단 or MACD크로스)으로 섣불리 매도 금지    ║
        # ╚══════════════════════════════════════════════════════════╝
        if len(df) < 26:
            return False

        # 지표 컬럼이 없으면(데이터 부족) 스킵
        if 'bb_upper' not in df.columns:
            return False

        c = df.iloc[-1]
        p = df.iloc[-2]


        bb_upper_touch = current_price >= c['bb_upper']
        macd_dead      = p['macd'] > p['macd_signal'] and c['macd'] <= c['macd_signal']
        rsv_overbought = c['rsv'] >= 70

        if bull:
            # 상승장: 3개 조건 모두 + 목표 10% 이상 수익 달성 시만 청산
            # → 상승 추세에서 섣부른 청산 최대한 방지
            if bb_upper_touch and macd_dead and rsv_overbought and profit_rate >= 10.0:
                log.info(
                    f"[전략] 📊 상승장 지표 청산 - {stock_code} "
                    f"(BB상단+MACD데드+RSV과매수 | 수익 {profit_rate:.1f}%)"
                )
                self._peak.pop(stock_code, None)
                return True
        else:
            # 횡보장: 2개 이상 조건 충족 시 청산
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
