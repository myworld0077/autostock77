#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF 변동성 장세 대응 전략 — EtfVolatilityStrategy

===== 전략 개요 =====

  레버리지 ETF (2배 상승형):
    상승 국면 + 과매도 반등 신호 → 매수
    ex) TIGER 미국필라델피아반도체레버리지, KODEX 삼성전자레버리지

  인버스 ETF (하락 헤지형):
    하락 국면 + 과매수 하락 신호 → 매수 (헤지)
    ex) TIGER 미국필라델피아반도체인버스, KODEX 삼성전자인버스

===== 국면 판단 (Market Regime) =====

  ATR 비율 + RSI + MACD 복합 신호로 4가지 국면 분류:
    ① 상승  : 레버리지 ETF 매수 적합
    ② 하락  : 인버스 ETF 매수 적합 (헤지)
    ③ 공황  : 인버스 ETF 헤지 + 일반 매매 중단 권고
    ④ 횡보  : 관망 (신규 진입 금지)

===== 리스크 관리 =====

  - 손절: -3% (레버리지 2배이므로 실질 -6% 방어)
  - 즉시 익절: +6% (레버리지 효과 단기 수확)
  - 트레일링 스탑: 수익 3%+ 이후 고점 -2% 이탈 시 청산
  - 최대 보유: 3거래일 (금요일 강제 청산, 주말 GAP 리스크 제거)
  - 동시 보유 방지: 레버리지 + 인버스 페어 동시 보유 절대 금지

Python 3.9 호환
"""
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Set

from strategy.base import BaseStrategy
from core.etf_universe import (
    is_leverage, is_inverse, get_pair, get_etf_name,
    ALL_LEVERAGE_ETF, ALL_INVERSE_ETF,
)
from utils.logger import log


# ─── 국면 상수 ────────────────────────────────────────────────────────────────
REGIME_BULL   = "상승"   # 레버리지 매수
REGIME_BEAR   = "하락"   # 인버스 매수 (헤지)
REGIME_PANIC  = "공황"   # 인버스 헤지 + 신규매수 자제
REGIME_RANGE  = "횡보"   # 관망

# 국면별 색상 (로그용)
_REGIME_ICON = {
    REGIME_BULL:  "🟢",
    REGIME_BEAR:  "🔴",
    REGIME_PANIC: "🆘",
    REGIME_RANGE: "🟡",
}


class EtfVolatilityStrategy(BaseStrategy):
    """
    ETF 변동성 장세 대응 전략

    레버리지 ETF: 상승 국면 포착 + 빠른 익절
    인버스 ETF : 하락/공황 국면 헤지 포지션
    """

    name = "ETF 변동성 대응 전략 v1 (레버리지2배·인버스 헤지)"

    # ── 기본 파라미터 ──
    STOP_LOSS_PCT:   float = -3.0   # 손절 (%)
    PROFIT_TAKE_PCT: float =  6.0   # 즉시 익절 (%)
    TRAIL_ENTRY_PCT: float =  3.0   # 트레일링 진입 수익 기준 (%)
    TRAIL_DROP_PCT:  float =  2.0   # 트레일링 허용 하락폭 (%)
    MAX_HOLD_DAYS:   int   =  3     # 최대 보유 거래일 (초과 시 강제 청산)

    # ── 국면 판단 파라미터 ──
    RSI_OVERSOLD:    float = 40.0   # RSI 과매도 기준 (레버리지 매수)
    RSI_OVERBOUGHT:  float = 65.0   # RSI 과매수 기준 (인버스 매수)
    ATR_SURGE_RATIO: float =  1.3   # ATR 급등 배율 (변동성 확대 감지)
    PANIC_ATR_RATIO: float =  2.0   # ATR 공황 배율

    def __init__(
        self,
        held_codes_ref: Optional[Set[str]] = None,   # AutoTrader 보유 목록 참조 (동시보유 방지용)
        stop_loss_pct:   float = -3.0,
        profit_take_pct: float =  6.0,
        max_hold_days:   int   =  3,
    ):
        self.stop_loss_pct   = stop_loss_pct
        self.profit_take_pct = profit_take_pct
        self.max_hold_days   = max_hold_days
        self._held_ref       = held_codes_ref  # 외부 보유 집합 참조 (선택적)

        # 종목별 상태 추적
        self._peak:      Dict[str, float] = {}   # 고점 추적 (트레일링)
        self._buy_date:  Dict[str, str]   = {}   # 매수 날짜 (최대 보유일 계산)
        self._hold_days: Dict[str, int]   = {}   # 보유 거래일 카운터
        self._regime_cache: Dict[str, str] = {}  # 국면 캐시 (1사이클 내 재사용)

    # ─────────────────────────────────────────────────────────────────────────
    #  보조 지표
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """ATR, RSI, MACD, EMA 보조 지표 추가"""
        df = df.copy()

        # ── ATR (Average True Range) ─────────────────────────────────────────
        h_l   = df["high"] - df["low"]
        h_pc  = (df["high"] - df["close"].shift(1)).abs()
        l_pc  = (df["low"]  - df["close"].shift(1)).abs()
        tr    = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
        df["atr"]     = tr.rolling(14).mean()
        df["atr_avg"] = df["atr"].rolling(20).mean()   # 20일 평균 ATR

        # ── RSI (14일) ────────────────────────────────────────────────────────
        delta  = df["close"].diff()
        gain   = delta.clip(lower=0).rolling(14).mean()
        loss   = (-delta.clip(upper=0)).rolling(14).mean()
        rs     = gain / loss.replace(0, float("nan"))
        df["rsi"] = 100 - (100 / (1 + rs))
        df["rsi"] = df["rsi"].fillna(50.0)

        # ── MACD (12, 26, 9) ─────────────────────────────────────────────────
        df["ema12"]       = df["close"].ewm(span=12, adjust=False).mean()
        df["ema26"]       = df["close"].ewm(span=26, adjust=False).mean()
        df["macd"]        = df["ema12"] - df["ema26"]
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_hist"]   = df["macd"] - df["macd_signal"]

        # ── EMA 추세 ──────────────────────────────────────────────────────────
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
        df["ema60"] = df["close"].ewm(span=60, adjust=False).mean()

        # ── 일간 수익률 ───────────────────────────────────────────────────────
        df["ret1"] = df["close"].pct_change(1)    # 1일 수익률
        df["ret3"] = df["close"].pct_change(3)    # 3일 수익률

        return df

    # ─────────────────────────────────────────────────────────────────────────
    #  국면 판단 (Market Regime Detection)
    # ─────────────────────────────────────────────────────────────────────────

    def detect_regime(self, stock_code: str, df: pd.DataFrame) -> str:
        """
        ATR + RSI + MACD + EMA 복합 신호로 시장 국면 판단

        Returns:
            "상승" | "하락" | "공황" | "횡보"
        """
        if len(df) < 30:
            return REGIME_RANGE

        c = df.iloc[-1]
        p = df.iloc[-2]

        atr      = float(c.get("atr",     0) or 0)
        atr_avg  = float(c.get("atr_avg", 1) or 1)
        rsi      = float(c.get("rsi",    50) or 50)
        macd     = float(c.get("macd",    0) or 0)
        sig      = float(c.get("macd_signal", 0) or 0)
        ema20    = float(c.get("ema20",   0) or 0)
        ema60    = float(c.get("ema60",   0) or 0)
        close    = float(c.get("close",   0) or 0)
        ret3     = float(c.get("ret3",    0) or 0)

        prev_macd = float(p.get("macd", 0) or 0)
        prev_sig  = float(p.get("macd_signal", 0) or 0)

        atr_ratio = atr / atr_avg if atr_avg > 0 else 1.0

        # MACD 크로스 방향
        macd_golden = (prev_macd < prev_sig) and (macd >= sig)   # 골든크로스 (상승 전환)
        macd_dead   = (prev_macd > prev_sig) and (macd <= sig)   # 데드크로스  (하락 전환)
        macd_bull   = macd > sig                                   # 현재 MACD 우위

        # EMA 추세
        ema_bull = (ema20 > ema60) and (close > ema20) if ema20 and ema60 else False

        # ── 공황 판단 (최우선): ATR 2배 이상 급등 + 급락 ──────────────────────
        if atr_ratio >= self.PANIC_ATR_RATIO and ret3 < -0.05:
            log.info(
                f"[ETF국면] 🆘 공황 - {stock_code} "
                f"(ATR비율:{atr_ratio:.2f}x, 3일수익률:{ret3*100:.1f}%)"
            )
            return REGIME_PANIC

        # ── 하락 판단: MACD 데드크로스 + RSI 고점 ────────────────────────────
        if macd_dead and rsi >= self.RSI_OVERBOUGHT:
            log.info(
                f"[ETF국면] 🔴 하락 - {stock_code} "
                f"(MACD데드크로스, RSI:{rsi:.0f})"
            )
            return REGIME_BEAR

        # 추가 하락 신호: MACD 음수 + EMA 역배열 + RSI 중립 이상
        if not macd_bull and not ema_bull and rsi > 55 and ret3 < -0.03:
            log.info(
                f"[ETF국면] 🔴 하락(추세) - {stock_code} "
                f"(MACD:{macd:.2f}, EMA역배열, RSI:{rsi:.0f})"
            )
            return REGIME_BEAR

        # ── 상승 판단: MACD 골든크로스 + RSI 저점 + 변동성 확대 ──────────────
        if macd_golden and rsi <= self.RSI_OVERSOLD and atr_ratio >= self.ATR_SURGE_RATIO:
            log.info(
                f"[ETF국면] 🟢 상승 - {stock_code} "
                f"(MACD골든크로스, RSI:{rsi:.0f}, ATR:{atr_ratio:.2f}x)"
            )
            return REGIME_BULL

        # 추가 상승 신호: MACD 양수 + EMA 정배열 + RSI 과매도 아님
        if macd_bull and ema_bull and rsi < 60 and atr_ratio >= self.ATR_SURGE_RATIO:
            log.info(
                f"[ETF국면] 🟢 상승(추세) - {stock_code} "
                f"(MACD강세, EMA정배열, ATR:{atr_ratio:.2f}x)"
            )
            return REGIME_BULL

        return REGIME_RANGE

    # ─────────────────────────────────────────────────────────────────────────
    #  레버리지 ↔ 인버스 동시 보유 방지 헬퍼
    # ─────────────────────────────────────────────────────────────────────────

    def _is_pair_held(self, code: str, held_codes: Optional[Set[str]]) -> bool:
        """
        페어(반대 방향) ETF가 이미 보유 중인지 확인
        (레버리지 보유 중이면 인버스 매수 금지, 반대도 동일)
        """
        if held_codes is None:
            return False
        pair = get_pair(code)
        if pair and pair in held_codes:
            return True
        return False

    # ─────────────────────────────────────────────────────────────────────────
    #  매수 판단
    # ─────────────────────────────────────────────────────────────────────────

    def should_buy(
        self,
        stock_code: str,
        df: pd.DataFrame,
        current_price: int,
        held_codes: Optional[Set[str]] = None,
    ) -> bool:
        """
        ETF 매수 조건 판단

        [레버리지 ETF 매수 조건]
          1. 시장 국면 = '상승'
          2. RSI <= 40 (과매도 반등 국면)
          3. ATR 변동성 확대 (20일 평균의 1.3배 이상)
          4. 페어 인버스 ETF 미보유

        [인버스 ETF 매수 조건 (헤지)]
          1. 시장 국면 = '하락' 또는 '공황'
          2. RSI >= 65 (과매수 하락 신호) 또는 3일 급락 -3% 이상
          3. MACD 데드크로스
          4. 페어 레버리지 ETF 미보유
        """
        if len(df) < 30:
            log.info(f"[ETF전략] ⬜ {get_etf_name(stock_code)}({stock_code}) — 데이터 부족")
            return False

        # ── 페어 동시 보유 방지 ─────────────────────────────────────────────
        if self._is_pair_held(stock_code, held_codes):
            pair = get_pair(stock_code)
            log.info(
                f"[ETF전략] ⛔ {get_etf_name(stock_code)}({stock_code}) — "
                f"페어({pair}) 이미 보유 중 → 동시 보유 금지"
            )
            return False

        df = self._add_indicators(df)
        c   = df.iloc[-1]
        p   = df.iloc[-2]

        rsi      = float(c.get("rsi",    50) or 50)
        macd     = float(c.get("macd",    0) or 0)
        sig      = float(c.get("macd_signal", 0) or 0)
        atr      = float(c.get("atr",     0) or 0)
        atr_avg  = float(c.get("atr_avg", 1) or 1)
        ret3     = float(c.get("ret3",    0) or 0)

        prev_macd = float(p.get("macd", 0) or 0)
        prev_sig  = float(p.get("macd_signal", 0) or 0)

        atr_ratio   = atr / atr_avg if atr_avg > 0 else 1.0
        macd_golden = (prev_macd < prev_sig) and (macd >= sig)
        macd_dead   = (prev_macd > prev_sig) and (macd <= sig)

        # 국면 감지
        regime = self.detect_regime(stock_code, df)
        self._regime_cache[stock_code] = regime

        # ══════════════════════════════════════════════════════════════════════
        #  레버리지 ETF 매수 판단
        # ══════════════════════════════════════════════════════════════════════
        if is_leverage(stock_code):
            if regime not in (REGIME_BULL,):
                log.info(
                    f"[ETF전략] ⬜ 레버리지 매수 보류 {get_etf_name(stock_code)}({stock_code}) "
                    f"— 국면:{regime} (상승 국면만 매수)"
                )
                return False

            cond_rsi = rsi <= self.RSI_OVERSOLD
            cond_atr = atr_ratio >= self.ATR_SURGE_RATIO
            cond_macd_ok = macd_golden or (macd > sig)

            score = sum([cond_rsi, cond_atr, cond_macd_ok])

            if score >= 2:  # 3가지 중 2가지 이상 충족
                log.info(
                    f"[ETF전략] 🟢 레버리지 매수 - {get_etf_name(stock_code)}({stock_code}) "
                    f"(국면:{regime} | RSI:{rsi:.0f} ATR:{atr_ratio:.2f}x "
                    f"MACD골든:{macd_golden} | 점수:{score}/3)"
                )
                self._buy_date[stock_code]  = datetime.now().strftime("%Y-%m-%d")
                self._hold_days[stock_code] = 0
                return True
            else:
                log.info(
                    f"[ETF전략] ⬜ 레버리지 매수 보류 {get_etf_name(stock_code)}({stock_code}) "
                    f"(점수:{score}/3 | RSI:{rsi:.0f} ATR:{atr_ratio:.2f}x MACD:{macd_golden})"
                )
                return False

        # ══════════════════════════════════════════════════════════════════════
        #  인버스 ETF 매수 판단 (헤지)
        # ══════════════════════════════════════════════════════════════════════
        if is_inverse(stock_code):
            if regime not in (REGIME_BEAR, REGIME_PANIC):
                log.info(
                    f"[ETF전략] ⬜ 인버스 매수 보류 {get_etf_name(stock_code)}({stock_code}) "
                    f"— 국면:{regime} (하락/공황 국면만 헤지 매수)"
                )
                return False

            cond_rsi  = rsi >= self.RSI_OVERBOUGHT
            cond_macd = macd_dead or (macd < sig)
            cond_drop = ret3 < -0.03   # 3일간 -3% 이상 급락

            score = sum([cond_rsi, cond_macd, cond_drop])

            # 공황 국면은 조건 1개만 충족해도 매수 (긴급 헤지)
            min_score = 1 if regime == REGIME_PANIC else 2

            if score >= min_score:
                log.info(
                    f"[ETF전략] 🔴 인버스 헤지 매수 - {get_etf_name(stock_code)}({stock_code}) "
                    f"(국면:{regime} | RSI:{rsi:.0f} MACD데드:{macd_dead} "
                    f"3일수익:{ret3*100:.1f}% | 점수:{score}/3)"
                )
                self._buy_date[stock_code]  = datetime.now().strftime("%Y-%m-%d")
                self._hold_days[stock_code] = 0
                return True
            else:
                log.info(
                    f"[ETF전략] ⬜ 인버스 매수 보류 {get_etf_name(stock_code)}({stock_code}) "
                    f"(점수:{score}/{min_score}+ | RSI:{rsi:.0f} MACD:{macd_dead} 3일:{ret3*100:.1f}%)"
                )
                return False

        return False

    # ─────────────────────────────────────────────────────────────────────────
    #  매도 판단
    # ─────────────────────────────────────────────────────────────────────────

    def should_sell(
        self,
        stock_code: str,
        df: pd.DataFrame,
        current_price: int,
        avg_price: int,
    ) -> bool:
        """
        ETF 매도 우선순위:
          ① 손절: 수익률 <= -3% (레버리지 2배 실질 -6% 방어)
          ② 금요일 강제 청산 (주말 GAP 리스크 제거)
          ③ 최대 보유일(3거래일) 초과 시 강제 청산
          ④ 국면 전환 감지 시 즉시 청산
          ⑤ 즉시 익절: 수익률 >= +6%
          ⑥ 트레일링 스탑: 수익 3%+ 이후 고점 -2% 이탈
        """
        if avg_price <= 0:
            return False

        profit_rate = (current_price - avg_price) / avg_price * 100

        # ① 손절: -3% 이하 즉시 청산 ─────────────────────────────────────────
        if profit_rate <= self.stop_loss_pct:
            log.info(
                f"[ETF전략] 🔴 손절 - {get_etf_name(stock_code)}({stock_code}) "
                f"(수익률 {profit_rate:.1f}% ≤ {self.stop_loss_pct}%)"
            )
            self._cleanup(stock_code)
            return True

        # ② 금요일 강제 청산 (주말 보유 금지) ───────────────────────────────
        weekday = datetime.now().weekday()
        if weekday == 4:  # 금요일
            log.info(
                f"[ETF전략] 📅 금요일 강제 청산 - {get_etf_name(stock_code)}({stock_code}) "
                f"(주말 GAP 리스크 제거 | 수익률 {profit_rate:.1f}%)"
            )
            self._cleanup(stock_code)
            return True

        # ③ 최대 보유일 초과 시 강제 청산 ─────────────────────────────────────
        hold = self._hold_days.get(stock_code, 0)
        if hold >= self.max_hold_days:
            log.info(
                f"[ETF전략] ⏱ 최대보유일({self.max_hold_days}일) 초과 청산 "
                f"- {get_etf_name(stock_code)}({stock_code}) (수익률 {profit_rate:.1f}%)"
            )
            self._cleanup(stock_code)
            return True
        # 보유일 카운터 증가
        self._hold_days[stock_code] = hold + 1

        # ④ 국면 전환 감지 → 즉시 청산 ─────────────────────────────────────
        if len(df) >= 30:
            df_ind = self._add_indicators(df)
            regime = self.detect_regime(stock_code, df_ind)

            if is_leverage(stock_code) and regime in (REGIME_BEAR, REGIME_PANIC):
                log.info(
                    f"[ETF전략] 🔄 국면전환 청산 (레버리지→{regime}) "
                    f"- {get_etf_name(stock_code)}({stock_code}) (수익률 {profit_rate:.1f}%)"
                )
                self._cleanup(stock_code)
                return True

            if is_inverse(stock_code) and regime == REGIME_BULL:
                log.info(
                    f"[ETF전략] 🔄 국면전환 청산 (인버스→{regime}) "
                    f"- {get_etf_name(stock_code)}({stock_code}) (수익률 {profit_rate:.1f}%)"
                )
                self._cleanup(stock_code)
                return True

        # ⑤ 즉시 익절: +6% 이상 ──────────────────────────────────────────────
        if profit_rate >= self.profit_take_pct:
            log.info(
                f"[ETF전략] 💰 즉시 익절 - {get_etf_name(stock_code)}({stock_code}) "
                f"(수익률 {profit_rate:.1f}% ≥ {self.profit_take_pct}%)"
            )
            self._cleanup(stock_code)
            return True

        # ⑥ 트레일링 스탑: 수익 3%+ 진입 후 고점 -2% 이탈 ───────────────────
        peak = self._peak.get(stock_code, float(current_price))
        if current_price > peak:
            self._peak[stock_code] = float(current_price)
            peak = float(current_price)

        if profit_rate >= self.TRAIL_ENTRY_PCT:
            drop_from_peak = (peak - current_price) / peak * 100
            if drop_from_peak >= self.TRAIL_DROP_PCT:
                log.info(
                    f"[ETF전략] 📉 트레일링 스탑 - {get_etf_name(stock_code)}({stock_code}) "
                    f"(수익 {profit_rate:.1f}% | 고점 {peak:,.0f} → -{drop_from_peak:.1f}%)"
                )
                self._cleanup(stock_code)
                return True

        return False

    # ─────────────────────────────────────────────────────────────────────────
    #  상태 초기화
    # ─────────────────────────────────────────────────────────────────────────

    def _cleanup(self, stock_code: str):
        """종목 상태 초기화"""
        self._peak.pop(stock_code,        None)
        self._buy_date.pop(stock_code,    None)
        self._hold_days.pop(stock_code,   None)
        self._regime_cache.pop(stock_code, None)

    def get_regime_summary(self) -> str:
        """현재 캐시된 국면 현황 문자열 반환 (로그/알림용)"""
        if not self._regime_cache:
            return "국면 데이터 없음"
        lines = []
        for code, regime in self._regime_cache.items():
            icon = _REGIME_ICON.get(regime, "⬜")
            lines.append(f"  {icon} {get_etf_name(code)}({code}): {regime}")
        return "\n".join(lines)
