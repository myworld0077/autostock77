#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF 변동성 전략 백테스트 — 삼성전자 레버리지/인버스 ETF (최근 2개월)
Oracle Cloud (Linux/Ubuntu) 전용

사용법:
    python3 backtest_etf.py

대상:
    005930 : 삼성전자 (국면 판단 기준)
    284430 : KODEX 삼성전자레버리지 (2배) — 없으면 삼성전자x2배 시뮬레이션
    395160 : KODEX 삼성전자인버스  (-1배) — 없으면 삼성전자x(-1)배 시뮬레이션
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Oracle Cloud: 타임존 강제 KST
os.environ.setdefault("TZ", "Asia/Seoul")
try:
    import time as _t; _t.tzset()
except AttributeError:
    pass

import pandas as pd
import numpy as np
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

try:
    import FinanceDataReader as fdr
    FDR_OK = True
except ImportError:
    FDR_OK = False
    print("[WARNING] FinanceDataReader 미설치 → 합성 데이터로 백테스트 진행")

# ─── 파라미터 ─────────────────────────────────────────────────────────────────
END_DATE   = date.today()
START_DATE = END_DATE - timedelta(days=65)   # 약 2개월
LONG_START = START_DATE - timedelta(days=60) # 지표 워밍업용 추가 2개월

START      = START_DATE.strftime("%Y-%m-%d")
END        = END_DATE.strftime("%Y-%m-%d")
LONG_S     = LONG_START.strftime("%Y-%m-%d")

INITIAL_CASH    = 10_000_000   # 초기 자금 1천만원
BUY_AMOUNT      = 1_000_000    # 1회 매수 금액 100만원
LEV_RATIO       = 0.20         # 레버리지 ETF 한도: 현금 20%
INV_RATIO       = 0.10         # 인버스 ETF  한도: 현금 10%
STOP_LOSS       = -3.0         # 손절 (%)
PROFIT_TAKE     = 6.0          # 즉시 익절 (%)
TRAIL_ENTRY     = 3.0          # 트레일링 진입 수익 (%)
TRAIL_DROP      = 2.0          # 트레일링 허용 하락 (%)
MAX_HOLD_DAYS   = 3            # 최대 보유 거래일

SAMSUNG_CODE = "005930"
LEV_CODE     = "284430"
INV_CODE     = "395160"

# ─── 지표 계산 ────────────────────────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # ATR(14)
    hl   = df["high"] - df["low"]
    hpc  = (df["high"] - df["close"].shift(1)).abs()
    lpc  = (df["low"]  - df["close"].shift(1)).abs()
    tr   = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    df["atr"]     = tr.rolling(14).mean()
    df["atr_avg"] = df["atr"].rolling(20).mean()
    # RSI(14)
    delta = df["close"].diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, float("nan"))
    df["rsi"] = (100 - (100 / (1 + rs))).fillna(50.0)
    # MACD(12,26,9)
    df["ema12"]       = df["close"].ewm(span=12, adjust=False).mean()
    df["ema26"]       = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"]        = df["ema12"] - df["ema26"]
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    # EMA 추세
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema60"] = df["close"].ewm(span=60, adjust=False).mean()
    # 수익률
    df["ret3"] = df["close"].pct_change(3)
    return df


def detect_regime(df: pd.DataFrame) -> str:
    """ATR+RSI+MACD+EMA 복합 신호로 시장 국면 판단"""
    if len(df) < 30:
        return "횡보"
    c  = df.iloc[-1]
    p  = df.iloc[-2]

    def _f(col: str, default: float = 0.0) -> float:
        v = c.get(col, default)
        return float(v) if (v is not None and not (isinstance(v, float) and np.isnan(v))) else default

    atr     = _f("atr");      atr_avg = _f("atr_avg", 1.0)
    rsi     = _f("rsi", 50.0)
    macd    = _f("macd");     sig  = _f("macd_signal")
    ema20   = _f("ema20");    ema60 = _f("ema60")
    close   = _f("close");    ret3  = _f("ret3")
    pm      = float(p.get("macd", 0) or 0)
    ps      = float(p.get("macd_signal", 0) or 0)

    atr_ratio   = atr / atr_avg if atr_avg > 0 else 1.0
    macd_golden = (pm < ps) and (macd >= sig)
    macd_dead   = (pm > ps) and (macd <= sig)
    macd_bull   = macd > sig
    ema_bull    = (ema20 > ema60) and (close > ema20) if ema20 and ema60 else False

    # 공황: ATR 2배 이상 + 3일 -5% 이상 급락
    if atr_ratio >= 2.0 and ret3 < -0.05:
        return "공황"
    # 하락: MACD 데드크로스 + RSI 고점
    if macd_dead and rsi >= 65:
        return "하락"
    if not macd_bull and not ema_bull and rsi > 55 and ret3 < -0.03:
        return "하락"
    # 상승: MACD 골든크로스 + RSI 저점 + ATR 확대
    if macd_golden and rsi <= 40 and atr_ratio >= 1.3:
        return "상승"
    if macd_bull and ema_bull and rsi < 60 and atr_ratio >= 1.3:
        return "상승"
    return "횡보"


# ─── 매수/매도 신호 ───────────────────────────────────────────────────────────

def signal_buy_leverage(df: pd.DataFrame) -> bool:
    """레버리지 ETF 매수: 상승 국면 + (RSI<=40 + ATR확대 + MACD강세) 2개 이상"""
    if len(df) < 30 or detect_regime(df) != "상승":
        return False
    c  = df.iloc[-1]; p = df.iloc[-2]
    rsi      = float(c.get("rsi", 50) or 50)
    atr      = float(c.get("atr", 0) or 0)
    atr_avg  = float(c.get("atr_avg", 1) or 1)
    macd     = float(c.get("macd", 0) or 0)
    sig      = float(c.get("macd_signal", 0) or 0)
    pm       = float(p.get("macd", 0) or 0)
    ps       = float(p.get("macd_signal", 0) or 0)
    atr_r    = atr / atr_avg if atr_avg > 0 else 1.0
    golden   = (pm < ps) and (macd >= sig)
    return sum([rsi <= 40, atr_r >= 1.3, golden or (macd > sig)]) >= 2


def signal_buy_inverse(df: pd.DataFrame) -> bool:
    """인버스 ETF 매수 (헤지): 하락/공황 국면 + 조건 충족"""
    if len(df) < 30:
        return False
    regime = detect_regime(df)
    if regime not in ("하락", "공황"):
        return False
    c  = df.iloc[-1]; p = df.iloc[-2]
    rsi  = float(c.get("rsi", 50) or 50)
    macd = float(c.get("macd", 0) or 0)
    sig  = float(c.get("macd_signal", 0) or 0)
    pm   = float(p.get("macd", 0) or 0)
    ps   = float(p.get("macd_signal", 0) or 0)
    ret3 = float(c.get("ret3", 0) or 0)
    dead = (pm > ps) and (macd <= sig)
    score = sum([rsi >= 65, dead or (macd < sig), ret3 < -0.03])
    return score >= (1 if regime == "공황" else 2)


def signal_sell(
    etf_type: str,
    df: pd.DataFrame,
    cur: float,
    avg: float,
    hold_days: int,
    peak: float,
    weekday: int,
) -> Tuple[bool, str]:
    """ETF 매도 신호 판단"""
    pr = (cur - avg) / avg * 100

    if pr <= STOP_LOSS:
        return True, f"손절({pr:.1f}%)"
    if weekday == 4:
        return True, f"금요일강제청산({pr:+.1f}%)"
    if hold_days >= MAX_HOLD_DAYS:
        return True, f"최대보유일({pr:+.1f}%)"
    if len(df) >= 30:
        regime = detect_regime(df)
        if etf_type == "leverage" and regime in ("하락", "공황"):
            return True, f"국면전환->{regime}({pr:+.1f}%)"
        if etf_type == "inverse" and regime == "상승":
            return True, f"국면전환->{regime}({pr:+.1f}%)"
    if pr >= PROFIT_TAKE:
        return True, f"즉시익절({pr:.1f}%)"
    if pr >= TRAIL_ENTRY and peak > 0:
        drop = (peak - cur) / peak * 100
        if drop >= TRAIL_DROP:
            return True, f"트레일링({pr:+.1f}%,고점-{drop:.1f}%)"
    return False, ""


# ─── 데이터 로드 ──────────────────────────────────────────────────────────────

def load_df(code: str, start: str, end: str) -> Optional[pd.DataFrame]:
    if not FDR_OK:
        return None
    try:
        df = fdr.DataReader(code, start, end)
        df = df.rename(columns=str.lower)
        cols = [c for c in ["open","high","low","close","volume"] if c in df.columns]
        df = df[cols].dropna()
        return df if len(df) >= 15 else None
    except Exception as e:
        print(f"  [{code}] 로드 실패: {e}")
        return None


def make_sim_df(base_df: pd.DataFrame, mult: float) -> pd.DataFrame:
    """베이스 종가 일봉을 N배 ETF로 합성"""
    ret    = base_df["close"].pct_change().fillna(0) * mult
    price  = 10_000.0 * (1 + ret).cumprod()
    ratio  = price / base_df["close"]
    spread = abs(mult - 1) * 0.005
    return pd.DataFrame({
        "open":   base_df["open"]   * ratio,
        "high":   base_df["high"]   * ratio * (1 + spread),
        "low":    base_df["low"]    * ratio * (1 - spread),
        "close":  price,
        "volume": base_df["volume"],
    }, index=base_df.index)


# ─── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    sep = "=" * 65
    print(f"\n{sep}")
    print(f"  ETF 변동성 전략 백테스트: {START} ~ {END}")
    print(f"  삼성전자 레버리지/인버스 ETF 시뮬레이션")
    print(f"  초기자금: {INITIAL_CASH:,}원  |  1회 매수: {BUY_AMOUNT:,}원")
    print(sep + "\n")

    # 데이터 로드
    samsung_raw = load_df(SAMSUNG_CODE, LONG_S, END)
    if samsung_raw is None:
        print("  [INFO] 삼성전자 실데이터 없음 → 랜덤워크 더미 생성")
        dates = pd.bdate_range(LONG_S, END)
        np.random.seed(42)
        prices = 55_000.0 * np.cumprod(1 + np.random.normal(0.001, 0.015, len(dates)))
        samsung_raw = pd.DataFrame({
            "open": prices * 0.998, "high": prices * 1.012,
            "low":  prices * 0.988, "close": prices,
            "volume": np.random.randint(10_000_000, 30_000_000, len(dates)),
        }, index=dates)
        print(f"  삼성전자 더미 생성: {len(samsung_raw)}일")
    else:
        print(f"  삼성전자({SAMSUNG_CODE}) 로드: {len(samsung_raw)}일")

    lev_raw = load_df(LEV_CODE, LONG_S, END)
    if lev_raw is None:
        lev_raw = make_sim_df(samsung_raw, 2.0)
        print(f"  KODEX삼성전자레버리지({LEV_CODE}) 합성: {len(lev_raw)}일 (x2배)")
    else:
        print(f"  KODEX삼성전자레버리지({LEV_CODE}) 로드: {len(lev_raw)}일")

    inv_raw = load_df(INV_CODE, LONG_S, END)
    if inv_raw is None:
        inv_raw = make_sim_df(samsung_raw, -1.0)
        print(f"  KODEX삼성전자인버스({INV_CODE}) 합성: {len(inv_raw)}일 (x-1배)")
    else:
        print(f"  KODEX삼성전자인버스({INV_CODE}) 로드: {len(inv_raw)}일")

    # 지표 계산
    samsung_full = add_indicators(samsung_raw)
    lev_full     = add_indicators(lev_raw)
    inv_full     = add_indicators(inv_raw)

    # 백테스트 거래일 (2개월 구간)
    bt_start = pd.Timestamp(START)
    bt_end   = pd.Timestamp(END)
    trading_dates = sorted([d for d in samsung_full.index if bt_start <= d <= bt_end])
    print(f"\n  백테스트 거래일: {len(trading_dates)}일\n")

    # ── 엔진 ────────────────────────────────────────────────────────────────
    cash: float       = float(INITIAL_CASH)
    holdings: Dict    = {}   # code → {type,qty,avg_price,peak,hold_days}
    trade_log: List   = []
    regime_log: List  = []
    daily_equity: List = []  # 일별 자산 추적

    for today in trading_dates:
        wd = today.weekday()   # 0=월,4=금

        sam_hist = samsung_full[samsung_full.index <= today]
        lev_hist = lev_full[lev_full.index <= today]
        inv_hist = inv_full[inv_full.index <= today]

        if len(sam_hist) < 30:
            continue

        cur_lev = float(lev_hist.iloc[-1]["close"]) if len(lev_hist) > 0 else 0.0
        cur_inv = float(inv_hist.iloc[-1]["close"]) if len(inv_hist) > 0 else 0.0
        regime  = detect_regime(sam_hist)
        regime_log.append({"date": str(today.date()), "regime": regime})

        # 매도
        for code in list(holdings.keys()):
            h = holdings[code]
            cp   = cur_lev if code == LEV_CODE else cur_inv
            hist = lev_hist if code == LEV_CODE else inv_hist
            if cp <= 0:
                continue
            if cp > h["peak"]:
                h["peak"] = cp
            ok, reason = signal_sell(h["type"], hist, cp, h["avg_price"],
                                     h["hold_days"], h["peak"], wd)
            if ok:
                proceeds = cp * h["qty"]
                pnl      = (cp - h["avg_price"]) * h["qty"]
                pr       = (cp - h["avg_price"]) / h["avg_price"] * 100
                cash    += proceeds
                trade_log.append({
                    "date": str(today.date()), "side": "SELL",
                    "code": code, "name": "레버리지ETF" if code==LEV_CODE else "인버스ETF",
                    "type": h["type"], "qty": h["qty"],
                    "price": cp, "avg": h["avg_price"],
                    "pnl": pnl, "profit_rate": pr,
                    "reason": reason, "regime": regime,
                })
                del holdings[code]

        # 매수
        lev_held = holdings[LEV_CODE]["qty"] * cur_lev if LEV_CODE in holdings else 0.0
        inv_held = holdings[INV_CODE]["qty"] * cur_inv if INV_CODE in holdings else 0.0
        lev_avail = cash * LEV_RATIO - lev_held
        inv_avail = cash * INV_RATIO - inv_held

        # 레버리지 ETF 매수
        if (LEV_CODE not in holdings
                and INV_CODE not in holdings     # 페어 동시보유 금지
                and lev_avail >= BUY_AMOUNT * 0.5
                and cur_lev > 0
                and signal_buy_leverage(sam_hist)):
            amt = min(lev_avail, cash, BUY_AMOUNT)
            qty = int(amt // cur_lev)
            if qty > 0:
                cash -= qty * cur_lev
                holdings[LEV_CODE] = {
                    "type": "leverage", "qty": qty,
                    "avg_price": cur_lev, "peak": cur_lev, "hold_days": 0,
                }
                trade_log.append({
                    "date": str(today.date()), "side": "BUY",
                    "code": LEV_CODE, "name": "레버리지ETF", "type": "leverage",
                    "qty": qty, "price": cur_lev, "avg": cur_lev,
                    "pnl": 0, "profit_rate": 0,
                    "reason": f"상승국면매수(국면:{regime})", "regime": regime,
                })

        # 인버스 ETF 매수 (헤지)
        if (INV_CODE not in holdings
                and LEV_CODE not in holdings     # 페어 동시보유 금지
                and inv_avail >= BUY_AMOUNT * 0.5
                and cur_inv > 0
                and signal_buy_inverse(sam_hist)):
            amt = min(inv_avail, cash, BUY_AMOUNT)
            qty = int(amt // cur_inv)
            if qty > 0:
                cash -= qty * cur_inv
                holdings[INV_CODE] = {
                    "type": "inverse", "qty": qty,
                    "avg_price": cur_inv, "peak": cur_inv, "hold_days": 0,
                }
                trade_log.append({
                    "date": str(today.date()), "side": "BUY",
                    "code": INV_CODE, "name": "인버스ETF", "type": "inverse",
                    "qty": qty, "price": cur_inv, "avg": cur_inv,
                    "pnl": 0, "profit_rate": 0,
                    "reason": f"하락국면헤지(국면:{regime})", "regime": regime,
                })

        # 보유일 증가
        for h in holdings.values():
            h["hold_days"] += 1

        # 일별 총자산
        ev = (holdings.get(LEV_CODE, {}).get("qty", 0) * cur_lev
            + holdings.get(INV_CODE, {}).get("qty", 0) * cur_inv)
        daily_equity.append({"date": str(today.date()), "equity": cash + ev})

    # ── 미청산 평가 ────────────────────────────────────────────────────────
    final_eval = 0.0
    unrealized = []
    for code, h in holdings.items():
        lp    = float(lev_full.iloc[-1]["close"]) if code == LEV_CODE else float(inv_full.iloc[-1]["close"])
        name  = "레버리지ETF" if code == LEV_CODE else "인버스ETF"
        val   = lp * h["qty"]
        pnl   = (lp - h["avg_price"]) * h["qty"]
        rate  = (lp - h["avg_price"]) / h["avg_price"] * 100
        final_eval += val
        unrealized.append({"name": name, "qty": h["qty"],
                            "avg": h["avg_price"], "last": lp, "pnl": pnl, "rate": rate})

    # ── 결과 출력 ──────────────────────────────────────────────────────────
    total_value  = cash + final_eval
    total_return = (total_value - INITIAL_CASH) / INITIAL_CASH * 100

    buys   = [t for t in trade_log if t["side"] == "BUY"]
    sells  = [t for t in trade_log if t["side"] == "SELL"]
    lev_s  = [t for t in sells if t["type"] == "leverage"]
    inv_s  = [t for t in sells if t["type"] == "inverse"]
    wins   = [t for t in sells if t["pnl"] > 0]
    loses  = [t for t in sells if t["pnl"] <= 0]

    # MDD 계산
    eq_vals = [d["equity"] for d in daily_equity]
    if eq_vals:
        peak_eq = INITIAL_CASH
        mdd = 0.0
        for ev in eq_vals:
            if ev > peak_eq:
                peak_eq = ev
            dd = (peak_eq - ev) / peak_eq * 100
            if dd > mdd:
                mdd = dd
    else:
        mdd = 0.0

    print(f"\n{sep}")
    print(f"  [백테스트 결과] {START} ~ {END}")
    print(sep)
    print(f"  초기자금:        {INITIAL_CASH:>12,} 원")
    print(f"  최종 현금:       {cash:>12,.0f} 원")
    print(f"  미청산 평가액:   {final_eval:>12,.0f} 원")
    print(f"  최종 총자산:     {total_value:>12,.0f} 원")
    print(f"  총 수익률:       {total_return:>+11.2f} %")
    print(f"  최대 낙폭(MDD):  {mdd:>+11.2f} %")
    print("-" * 65)
    lev_cnt = sum(1 for t in buys if t["type"] == "leverage")
    inv_cnt = sum(1 for t in buys if t["type"] == "inverse")
    print(f"  총 매수 횟수:    {len(buys):>3}회  (레버리지:{lev_cnt} / 인버스:{inv_cnt})")
    print(f"  총 매도 횟수:    {len(sells):>3}회")
    if sells:
        wr   = len(wins) / len(sells) * 100
        aw   = sum(t["profit_rate"] for t in wins)  / len(wins)  if wins  else 0.0
        al   = sum(t["profit_rate"] for t in loses) / len(loses) if loses else 0.0
        print(f"  승률:            {wr:>+10.1f} %")
        print(f"  평균수익(승):    {aw:>+10.2f} %")
        print(f"  평균수익(패):    {al:>+10.2f} %")
        if al != 0:
            print(f"  손익비(W/L):     {abs(aw/al):>10.2f} x")

    if lev_s:
        lw  = [t for t in lev_s if t["pnl"] > 0]
        lpn = sum(t["pnl"] for t in lev_s)
        print("-" * 65)
        print(f"  [레버리지ETF] 거래:{len(lev_s)}회 | 승률:{len(lw)/len(lev_s)*100:.0f}% | 실현손익:{lpn:>+,.0f}원")
    if inv_s:
        iw  = [t for t in inv_s if t["pnl"] > 0]
        ipn = sum(t["pnl"] for t in inv_s)
        print(f"  [인버스ETF]   거래:{len(inv_s)}회 | 승률:{len(iw)/len(inv_s)*100:.0f}% | 실현손익:{ipn:>+,.0f}원")

    # 국면 분포
    if regime_log:
        rdf  = pd.DataFrame(regime_log)
        rdist = rdf["regime"].value_counts()
        print("-" * 65)
        print(f"  시장 국면 분포 (총 {len(regime_log)}일):")
        for r, cnt in rdist.items():
            bar = "#" * int(cnt / len(regime_log) * 30)
            pct = cnt / len(regime_log) * 100
            print(f"    {r:<4}: {cnt:>3}일 ({pct:4.0f}%) {bar}")

    # 미청산
    if unrealized:
        print("-" * 65)
        print("  미청산 보유종목 (마지막 날 종가 기준):")
        hdr = f"  {'종목명':<12} {'수량':>5} {'매수가':>10} {'현재가':>10} {'수익률':>7} {'평가손익':>13}"
        print(hdr)
        print("  " + "-" * 60)
        for u in unrealized:
            sign = "+" if u["pnl"] >= 0 else ""
            print(
                f"  {u['name']:<12} {u['qty']:>4}주  "
                f"{u['avg']:>10,.0f} {u['last']:>10,.0f} "
                f"{u['rate']:>+6.1f}% {sign}{u['pnl']:>12,.0f}"
            )

    # 거래 내역 상세
    if sells:
        print("-" * 65)
        print(f"  청산 거래 내역 ({len(sells)}건):")
        hdr2 = f"  {'날짜':10} {'종류':8} {'수익률':>7} {'손익':>13}  사유"
        print(hdr2)
        print("  " + "-" * 65)
        for t in sorted(sells, key=lambda x: x["profit_rate"], reverse=True):
            tag = "[WIN] " if t["pnl"] > 0 else "[LOSS]"
            sign = "+" if t["pnl"] >= 0 else ""
            print(
                f"  {t['date']:10} {t['name']:8} "
                f"{t['profit_rate']:>+6.1f}% {sign}{t['pnl']:>12,.0f}원"
                f"  {tag} {t['reason']}"
            )

    # 파라미터 요약
    print("\n" + sep)
    print("  [전략 파라미터]")
    print(f"    손절: {STOP_LOSS}%  |  즉시익절: +{PROFIT_TAKE}%  |  트레일링: 수익{TRAIL_ENTRY}%+->고점-{TRAIL_DROP}%")
    print(f"    최대보유: {MAX_HOLD_DAYS}거래일  |  금요일 강제청산  |  레버리지+인버스 동시보유 금지")
    print(f"    레버리지 한도: 현금 {LEV_RATIO*100:.0f}%  |  인버스 한도: 현금 {INV_RATIO*100:.0f}%")
    print(sep + "\n")


if __name__ == "__main__":
    main()
