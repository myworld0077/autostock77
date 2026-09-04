"""
시장 상태(레짐) 판별 모듈 — 코스피 지수 기반

시장 상태 판별 기준:
  - 하락장(BEAR):  코스피 20일 고점 대비 -10% 이상 하락
  - 상승장(BULL):  코스피 20일 저점 대비 +6% 이상 반등
  - 횡보장(SIDEWAYS): 위 두 조건에 해당하지 않는 박스권

Python 3.9+ 호환
"""
from enum import Enum
from typing import Optional
from utils.logger import log


class MarketRegime(Enum):
    """시장 상태 열거형"""
    BEAR = "bear"           # 하락장
    SIDEWAYS = "sideways"   # 횡보장
    BULL = "bull"           # 상승장


# 레짐별 한글 라벨/이모지
_LABELS = {
    MarketRegime.BEAR:     "🔴 하락장",
    MarketRegime.SIDEWAYS: "🟡 횡보장",
    MarketRegime.BULL:     "🟢 상승장",
}

# 레짐별 텔레그램 명령어 매핑
COMMAND_TO_REGIME = {
    "a": MarketRegime.BEAR,
    "b": MarketRegime.SIDEWAYS,
    "c": MarketRegime.BULL,
}


def get_regime_label(regime: MarketRegime) -> str:
    """텔레그램 표시용 한글 라벨"""
    return _LABELS.get(regime, "❓ 알 수 없음")


def detect_regime(
    bear_threshold: float = -10.0,
    bull_threshold: float = 6.0,
    lookback_days: int = 20,
) -> MarketRegime:
    """
    코스피 지수 기반 시장 상태 자동 판별.

    판별 로직:
      1) 최근 lookback_days일 코스피 일봉을 조회
      2) 기간 내 최고점(high_20) / 최저점(low_20) 계산
      3) 현재가 vs 고점 비율 → -10% 이하면 BEAR
      4) 현재가 vs 저점 비율 → +6% 이상이면 BULL
      5) 둘 다 아니면 SIDEWAYS

    Args:
        bear_threshold: 하락장 진입 기준 (고점 대비 %, 기본 -10)
        bull_threshold: 상승장 진입 기준 (저점 대비 %, 기본 +6)
        lookback_days: 조회 기간 (거래일, 기본 20)

    Returns:
        MarketRegime (BEAR / SIDEWAYS / BULL)
    """
    try:
        from core.market import get_daily_ohlcv, get_current_price

        # 코스피 종합지수 = 종목코드 "0001" (업종 코드)
        # 한국투자증권 API: 업종 시세는 별도 API 사용
        kospi_price = _get_kospi_index()
        if kospi_price is None:
            log.warning("[REGIME] 코스피 지수 조회 실패 → 횡보장(기본) 유지")
            return MarketRegime.SIDEWAYS

        kospi_ohlcv = _get_kospi_ohlcv(lookback_days)
        if kospi_ohlcv is None or len(kospi_ohlcv) < 5:
            log.warning("[REGIME] 코스피 일봉 조회 실패 → 횡보장(기본) 유지")
            return MarketRegime.SIDEWAYS

        high_20 = max(row["high"] for row in kospi_ohlcv)
        low_20 = min(row["low"] for row in kospi_ohlcv)
        current = kospi_price

        if high_20 <= 0 or low_20 <= 0:
            return MarketRegime.SIDEWAYS

        drop_from_high = ((current - high_20) / high_20) * 100.0
        rise_from_low = ((current - low_20) / low_20) * 100.0

        log.info(
            f"[REGIME] 코스피 현재: {current:.2f} | "
            f"20일 고점: {high_20:.2f} ({drop_from_high:+.1f}%) | "
            f"20일 저점: {low_20:.2f} ({rise_from_low:+.1f}%)"
        )

        if drop_from_high <= bear_threshold:
            regime = MarketRegime.BEAR
        elif rise_from_low >= bull_threshold:
            regime = MarketRegime.BULL
        else:
            regime = MarketRegime.SIDEWAYS

        log.info(f"[REGIME] 시장 판별 결과: {get_regime_label(regime)}")
        return regime

    except Exception as e:
        log.warning(f"[REGIME] 시장 판별 오류: {e} → 횡보장(기본) 유지")
        return MarketRegime.SIDEWAYS


def _get_kospi_index() -> Optional[float]:
    """코스피 종합지수 현재가 조회 (한투 업종 시세 API)"""
    try:
        from core.api import api

        tr_id = "FHKUP03500100"
        params = {
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": "0001",  # 코스피 종합
        }
        data = api.get(
            "/uapi/domestic-stock/v1/quotations/inquire-index-price",
            tr_id, params
        )
        output = data.get("output", {})
        price = float(output.get("bstp_nmix_prpr", 0))
        if price > 0:
            return price

        # fallback: 일반 시세 API로 시도
        return _get_kospi_index_fallback()
    except Exception as e:
        log.debug(f"[REGIME] 업종 시세 API 실패: {e}")
        return _get_kospi_index_fallback()


def _get_kospi_index_fallback() -> Optional[float]:
    """코스피 ETF(KODEX 200)로 간접 추정 (업종 API 실패 시)"""
    try:
        from core.market import get_current_price
        # KODEX 200 ETF (069500) 현재가로 코스피 방향 대리
        info = get_current_price("069500")
        price = info.get("price", 0)
        if price > 0:
            # KODEX 200 가격 × 약 10 = 대략적 코스피 지수 추정
            return float(price) * 10.0
        return None
    except Exception:
        return None


def _get_kospi_ohlcv(count: int = 20) -> Optional[list]:
    """코스피 종합지수 일봉 조회"""
    try:
        from core.api import api
        from datetime import datetime, timedelta

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=count * 2)).strftime("%Y%m%d")

        tr_id = "FHKUP03500100"
        params = {
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": "0001",
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": end_date,
            "FID_PERIOD_DIV_CODE": "D",
        }

        try:
            data = api.get(
                "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
                tr_id, params
            )
            records = data.get("output2", [])
            if records:
                rows = []
                for r in records[:count]:
                    rows.append({
                        "high": float(r.get("bstp_nmix_hgpr", 0)),
                        "low": float(r.get("bstp_nmix_lwpr", 0)),
                        "close": float(r.get("bstp_nmix_prpr", 0)),
                    })
                return rows
        except Exception:
            pass

        # fallback: KODEX 200 ETF 일봉으로 대리
        return _get_kospi_ohlcv_fallback(count)

    except Exception as e:
        log.debug(f"[REGIME] 코스피 일봉 조회 실패: {e}")
        return _get_kospi_ohlcv_fallback(count)


def _get_kospi_ohlcv_fallback(count: int = 20) -> Optional[list]:
    """KODEX 200 ETF 일봉으로 코스피 방향 대리 추정"""
    try:
        from core.market import get_daily_ohlcv
        df = get_daily_ohlcv("069500", "D", count)
        if df is None or df.empty:
            return None
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "high": float(r["high"]) * 10.0,
                "low": float(r["low"]) * 10.0,
                "close": float(r["close"]) * 10.0,
            })
        return rows
    except Exception:
        return None
