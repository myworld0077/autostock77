"""
거래소 영업일 판단 모듈

판단 우선순위:
    1. 주말 (토요일 / 일요일)          → 휴장
    2. 한국 법정공휴일 (holidays 라이브러리)  → 휴장
    3. KIS API 임시 휴장일 조회 (CTCA0903R) → 결과 반영
       ↳ API 실패 시 영업일로 간주 (보수적 운영)
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Dict, Optional

import holidays as _holidays_lib

from utils.logger import log

# ─── KIS API 결과 캐시 (당일 1회만 호출) ─────────────────────────
_kis_cache: Dict[str, Optional[bool]] = {}  # YYYYMMDD → True(휴장)/False(영업)/None(실패)


# ─── 법정공휴일 ────────────────────────────────────────────────────

@lru_cache(maxsize=10)
def _kr_holidays(year: int) -> _holidays_lib.HolidayBase:
    """한국 법정공휴일 객체 (연도별 캐싱)"""
    return _holidays_lib.country_holidays("KR", years=year)


# ─── KIS API 영업일 조회 ───────────────────────────────────────────

def _kis_is_holiday(target: date) -> Optional[bool]:
    """
    KIS API(CTCA0903R)로 해당 날짜의 휴장 여부 조회.

    Returns:
        True  = 휴장일
        False = 영업일
        None  = 조회 실패 (판단 불가)
    """
    from core.api import api  # 순환 임포트 방지용 지연 import

    date_str = target.strftime("%Y%m%d")
    if date_str in _kis_cache:  # None이더라도 쫐시 저장된 결과 반환 (재조회 금지)
        return _kis_cache[date_str]

    try:
        resp = api.get(
            "/uapi/domestic-stock/v1/quotations/chk-holiday",
            tr_id="CTCA0903R",
            params={
                "BASS_DT": date_str,
                "CTX_AREA_NK": "",
                "CTX_AREA_FC": "",
            },
        )

        output = resp.get("output", [])
        if not output:
            _kis_cache[date_str] = None
            return None

        # output 리스트에서 해당 날짜 항목 탐색
        for item in output:
            if item.get("BASS_DT") == date_str:
                # BZYS_YESNO: "Y" = 영업일, "N" = 휴장일
                is_holiday = item.get("BZYS_YESNO", "N") != "Y"
                if is_holiday:
                    holi_name = item.get("HOLI_NAME", "임시휴장")
                    log.info(f"[CALENDAR] KIS 휴장일 확인 → {holi_name} ({date_str})")
                _kis_cache[date_str] = is_holiday
                return is_holiday

        # 해당 날짜 항목 없음 → 첫 번째 항목의 영업일 여부로 대체
        item = output[0]
        is_holiday = item.get("BZYS_YESNO", "Y") != "Y"
        _kis_cache[date_str] = is_holiday
        return is_holiday

    except Exception as exc:
        log.warning(f"[CALENDAR] KIS 영업일 조회 실패 ({date_str}): {exc}")
        _kis_cache[date_str] = None
        return None


# KIS API 조회 성공 여부 추적용 플래그
# True = 정상 조회 완료 / False = 조회 실패하여 임시 영업일 간주 상태
is_kis_calendar_verified = True


def verify_market_open_strict() -> bool:
    """
    현재 시각 기준, 실제 한국투자증권 API가 정상 작동하고
    오늘이 진짜 장운영 영업일이었는지 엄격하게 교차 검증합니다.
    """
    global is_kis_calendar_verified
    # 1) 1차적으로 캘린더에서 KIS API 조회가 성공적이었다면 영업일로 인정
    if is_kis_calendar_verified:
        return True

    # 2) 만약 KIS API 조회가 실패하여 임시 영업일 상태라면,
    # 실제 삼성전자 '005930'의 시세 조회를 실시간 시도해봅니다.
    try:
        from core.market import get_current_price
        price_info = get_current_price("005930")
        if price_info and price_info.get("price", 0) > 0:
            log.info("[CALENDAR] 2중 검증 성공 → KIS API 실시간 시세 조회 정상 (영업일 확인됨)")
            return True
    except Exception as e:
        log.warning(f"[CALENDAR] 2중 검증 실패 → KIS API 실시간 교차 조회 에러: {e}")

    log.warning("[CALENDAR] 🚫 2중 검증 차단 → 영업일 증빙 데이터 부족으로 휴장일 간주 (리포트 발송 생략)")
    return False


# ─── 공개 API ─────────────────────────────────────────────────────

def is_trading_day(target: Optional[date] = None) -> bool:
    """
    주어진 날짜가 거래소 영업일인지 판단.

    Args:
        target: 판단할 날짜. None 이면 오늘.

    Returns:
        True = 영업일 / False = 휴장일
    """
    if target is None:
        target = date.today()

    # ① 주말
    if target.weekday() >= 5:  # 5=토, 6=일
        day_name = "토요일" if target.weekday() == 5 else "일요일"
        log.info(f"[CALENDAR] {target} {day_name} → 휴장")
        return False

    # ② 근로자의 날 (5월 1일)
    if target.month == 5 and target.day == 1:
        log.info(f"[CALENDAR] {target} 근로자의 날 → 휴장")
        return False

    # ③ 연말 휴장일 (12월 31일이 주말인 경우 직전 평일)
    if target.month == 12:
        dec31 = date(target.year, 12, 31)
        dec31_wd = dec31.weekday()
        is_last_market_holiday = False
        if dec31_wd < 5:
            is_last_market_holiday = (target.day == 31)
        elif dec31_wd == 5:
            is_last_market_holiday = (target.day == 30)
        else:
            is_last_market_holiday = (target.day == 29)

        if is_last_market_holiday:
            log.info(f"[CALENDAR] {target} 연말 납회일 익일 휴장 → 휴장")
            return False

    # ④ 법정공휴일
    kr_hols = _kr_holidays(target.year)
    if target in kr_hols:
        log.info(f"[CALENDAR] {target} 법정공휴일 → {kr_hols.get(target)} → 휴장")
        return False

    # ⑤ KIS API 임시 휴장 확인
    global is_kis_calendar_verified
    result = _kis_is_holiday(target)
    if result is True:
        is_kis_calendar_verified = True
        return False   # 휴장
    if result is False:
        is_kis_calendar_verified = True
        return True    # 영업

    # None (API 실패) → 영업일로 간주 (보수적 운영) — 동일날은 쫐시 1회만 경고
    is_kis_calendar_verified = False
    date_str = target.strftime("%Y%m%d")
    if _kis_cache.get(date_str) is None:  # 이미 설정된 None(성공적 실패)은 경고 안 함
        log.warning(f"[CALENDAR] {target} KIS 조회 실패 — 영업일로 간주하고 진행")
    return True


def next_trading_day(from_date: Optional[date] = None) -> date:
    """다음 영업일 날짜 반환 (최대 60일 탐색)."""
    d = (from_date or date.today()) + timedelta(days=1)
    for _ in range(60):  # 무한루프 방지
        if is_trading_day(d):
            return d
        d += timedelta(days=1)
    # 60일 내에 영업일을 찾지 못한 경우 (비정상 상황)
    log.warning("[CALENDAR] next_trading_day: 60일 내 영업일 탐색 실패 → 현재 날짜+1 반환")
    return (from_date or date.today()) + timedelta(days=1)


def trading_day_status(target: Optional[date] = None) -> str:
    """영업일 상태 문자열 반환 (로그/표시용)."""
    if target is None:
        target = date.today()
    if is_trading_day(target):
        return f"✅ {target} 영업일"
    nd = next_trading_day(target)
    return f"🚫 {target} 휴장 → 다음 영업일: {nd}"
