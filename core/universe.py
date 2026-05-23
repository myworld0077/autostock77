"""
유니버스 (종목 그룹) 관리 모듈
"""
import requests
import FinanceDataReader as fdr
import time
from datetime import datetime
from utils.logger import log
from core.market import get_current_price


# ── 마지막 성공한 top150 캐시 (장외 시간 재활용) ─────────────────────
_cached_top150: list[str] = []
_cached_top150_at: str = ""   # "YYYYMMDD" 형식


def _is_market_open() -> bool:
    """현재 시각이 KRX 정규장 시간(09:00~15:30) 내인지 확인."""
    now = datetime.now()
    t = now.hour * 60 + now.minute
    return 9 * 60 <= t <= 15 * 60 + 30


def _method1_snap_reader() -> list[str]:
    """방법 1: fdr.SnapDataReader (KRX 인덱스 구성종목)"""
    df = fdr.SnapDataReader('KRX/INDEX/STOCK/1028')
    if df is None or df.empty:
        raise ValueError("SnapDataReader 빈 응답")
    col = next((c for c in df.columns if c in ('Code', 'ISU_SRT_CD', 'Symbol')), None)
    if col is None:
        raise ValueError(f"Code 컬럼 없음 (컬럼: {list(df.columns)})")
    codes = [str(c).zfill(6) for c in df[col].tolist() if str(c).strip()]
    if not codes:
        raise ValueError("종목코드 0개")
    return codes


def _method2_stock_listing() -> list[str]:
    """방법 2: fdr.StockListing('KOSPI') → 시가총액 상위 200개 근사"""
    df = fdr.StockListing('KOSPI')
    if df is None or df.empty:
        raise ValueError("StockListing 빈 응답")

    # 시가총액 컬럼 탐색
    cap_col = next((c for c in df.columns if 'cap' in c.lower() or '시가총액' in c), None)
    code_col = next((c for c in df.columns if c in ('Code', 'Symbol', 'ISU_SRT_CD')), None)
    if code_col is None:
        raise ValueError(f"Code 컬럼 없음 (컬럼: {list(df.columns)})")

    if cap_col:
        df = df.sort_values(cap_col, ascending=False)

    codes = [str(c).zfill(6) for c in df[code_col].tolist()[:200] if str(c).strip()]
    if not codes:
        raise ValueError("종목코드 0개")
    return codes


def _method3_krx_http() -> list[str]:
    """방법 3: KRX 정보데이터시스템 직접 HTTP 요청"""
    url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://data.krx.co.kr/",
    }
    body = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT00601",
        "indIdx": "1",
        "indIdx2": "028",  # 코스피 200
        "share": "1",
        "money": "1",
        "csvxls_isNo": "false",
    }
    resp = requests.post(url, data=body, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("OutBlock_1", [])
    if not items:
        raise ValueError("KRX HTTP 응답에 종목 없음")
    codes = [str(item.get("ISU_SRT_CD", "")).zfill(6) for item in items
             if item.get("ISU_SRT_CD")]
    if not codes:
        raise ValueError("종목코드 0개")
    return codes


def get_kospi200_universe() -> list[str]:
    """
    코스피 200 구성 종목 코드를 가져옵니다.
    3가지 방법을 순서대로 시도하고, 모두 실패 시 Fallback 반환.

    Returns:
        종목코드 문자열 리스트 (예: ['005930', '000660', ...])
    """
    log.info("[UNIVERSE] 코스피 200 종목 리스트 갱신 중...")

    methods = [
        ("SnapDataReader", _method1_snap_reader),
        ("StockListing 시가총액 상위 200", _method2_stock_listing),
        ("KRX HTTP 직접 요청", _method3_krx_http),
    ]

    for name, fn in methods:
        try:
            codes = fn()
            log.info(f"[UNIVERSE] 코스피 200 종목 {len(codes)}개 로드 성공 (방법: {name})")
            return codes
        except Exception as e:
            log.warning(f"[UNIVERSE] '{name}' 실패 → 다음 방법 시도: {e}")

    # 모든 방법 실패 시 Fallback
    fallback = ["005930", "000660", "035420", "035720", "051910",
                "005380", "000270", "068270", "207940", "028260"]
    log.error(f"[UNIVERSE] 모든 방법 실패 — Fallback {len(fallback)}개 종목 사용")
    return fallback


def get_kis_kospi200_top150() -> list[str]:
    """
    코스피 200 종목을 가져온 뒤, 한국투자증권 API를 통해 현재 시가총액을 자동 업데이트하고
    시가총액 기준 상위 150개 종목만 필터링하여 반환합니다.

    장외 시간에는 inquire-price API가 500 에러를 반환하므로:
      - 오늘 이미 캐싱된 top150이 있으면 캐시 반환
      - 없으면 FDR StockListing 정렬 순서를 그대로 활용 (시가총액 정렬 근사치)
    장중에는 KIS API 시가총액으로 정렬하고 캐시에 저장합니다.
    """
    global _cached_top150, _cached_top150_at

    today_str = datetime.now().strftime("%Y%m%d")
    market_open = _is_market_open()

    log.info(f"[UNIVERSE] 코스피 200 종목 대상 시총 상위 150위 필터링 시작... "
             f"({'장중' if market_open else '장외 시간'})")

    # ── 장외 시간이고 오늘 캐시가 있으면 바로 반환 ──────────────────
    if not market_open and _cached_top150 and _cached_top150_at == today_str:
        log.info(f"[UNIVERSE] 장외 시간 — 오늘 캐시된 top150 재사용 ({len(_cached_top150)}종목)")
        return _cached_top150

    kospi200 = get_kospi200_universe()

    # ── 장외 시간: KIS API 호출 없이 FDR 순서로 150개 반환 ─────────
    if not market_open:
        top150 = kospi200[:150]
        log.info(f"[UNIVERSE] 장외 시간 — FDR 시가총액 정렬 기준 상위 {len(top150)}개 사용 "
                 f"(KIS API 500 오류 방지)")
        # 오늘 캐시가 없으므로 FDR 결과로 캐시 초기화
        if not _cached_top150:
            _cached_top150 = top150
            _cached_top150_at = today_str
        return top150

    # ── 장중: KIS API로 실시간 시가총액 조회 후 정렬 ─────────────────
    results = []
    fail_count = 0
    for code in kospi200:
        try:
            info = get_current_price(code)
            market_cap = info.get("market_cap", 0)
            results.append({"code": code, "market_cap": market_cap})
            time.sleep(0.05)  # KIS API 초당 20건 제한 고려
        except Exception as e:
            fail_count += 1
            log.warning(f"[UNIVERSE] 시가총액 조회 실패 ({code}): {e}")

    if fail_count > 0:
        log.info(f"[UNIVERSE] 시가총액 조회 완료 — 성공: {len(results)}, 실패: {fail_count}")

    if not results:
        log.error("[UNIVERSE] 시가총액 업데이트 전체 실패 — KOSPI 200 원본 반환 (최대 150개).")
        return kospi200[:150]

    # 시가총액 내림차순 정렬 후 150개 추출
    results.sort(key=lambda x: x["market_cap"], reverse=True)
    top150 = [x["code"] for x in results[:150]]

    # 캐시 업데이트
    _cached_top150 = top150
    _cached_top150_at = today_str

    log.info(f"[UNIVERSE] 시총 상위 {len(top150)}개 필터링 완료 "
             f"(1위: {top150[0]}, 마지막: {top150[-1]})")
    return top150


# ═══════════════════════════════════════════════════════════════════════
# 코스닥 150 에너지·반도체 관련 종목
# ═══════════════════════════════════════════════════════════════════════

_KOSDAQ_ENERGY_SEMI_FALLBACK = [
    "058470",   # 리노공업 (반도체 검사 소켓)
    "403870",   # HPSP (반도체 장비)
    "036930",   # 주성엔지니어링 (반도체 장비)
    "322310",   # 오로스테크놀로지 (반도체 장비)
    "240810",   # 원익IPS (반도체 장비)
    "357780",   # 솔브레인 (반도체 소재)
    "131970",   # 테스나 (반도체 후공정)
    "089030",   # 테크윙 (반도체 장비)
    "054450",   # 텔레칩스 (팹리스)
    "033640",   # 네패스 (반도체 후공정)
    "095340",   # ISC (반도체 검사)
    "396270",   # 넥스틴 (반도체 장비)
    "078600",   # 대주전자재료 (2차전지 소재)
    "336260",   # 두산퓨얼셀 (수소연료전지)
    "247540",   # 에코프로비엠 (2차전지 양극재)
    "086520",   # 에코프로 (2차전지)
    "096610",   # 알에프세미 (반도체/에너지)
    "117580",   # 대성에너지
    "281740",   # 레이크머티리얼즈 (2차전지 소재)
]

_SECTOR_KEYWORDS = [
    '반도체', '에너지', '2차전지', '배터리', '태양광', '수소',
    '연료전지', '풍력', '전력', '양극재', '음극재', '소재',
    '장비', '팹리스', '전기차', '전해질', '분리막',
]

_cached_kosdaq: list[str] = []
_cached_kosdaq_at: str = ""


def get_kosdaq150_energy_semi() -> list[str]:
    """코스닥 시총 상위 150개 중 에너지·반도체 관련 종목 추출."""
    global _cached_kosdaq, _cached_kosdaq_at

    today_str = datetime.now().strftime("%Y%m%d")
    if _cached_kosdaq and _cached_kosdaq_at == today_str:
        log.info(f"[UNIVERSE] 코스닥 에너지·반도체 캐시 재사용 ({len(_cached_kosdaq)}종목)")
        return _cached_kosdaq

    log.info("[UNIVERSE] 코스닥 150 에너지·반도체 종목 추출 시작...")

    try:
        df = fdr.StockListing('KOSDAQ')
        if df is None or df.empty:
            raise ValueError("빈 응답")

        code_col = next((c for c in df.columns if c in ('Code', 'Symbol', 'ISU_SRT_CD')), None)
        name_col = next((c for c in df.columns if c in ('Name', '종목명', 'ISU_ABBRV')), None)
        cap_col  = next((c for c in df.columns if 'cap' in c.lower() or '시가총액' in c), None)
        sect_col = next((c for c in df.columns if 'sect' in c.lower() or '업종' in c or 'Industry' in c), None)

        if not code_col or not name_col:
            raise ValueError(f"컬럼 없음: {list(df.columns)}")

        if cap_col:
            df = df.sort_values(cap_col, ascending=False)
        top150 = df.head(150)

        fb_set = set(_KOSDAQ_ENERGY_SEMI_FALLBACK)
        matched = []
        for _, row in top150.iterrows():
            code = str(row[code_col]).zfill(6)
            name = str(row.get(name_col, ''))
            sect = str(row.get(sect_col, '')) if sect_col else ''
            txt  = f"{name} {sect}".lower()

            if code in fb_set or any(kw in txt for kw in _SECTOR_KEYWORDS):
                matched.append(code)

        seen = set()
        result = []
        for c in matched:
            if c not in seen:
                seen.add(c)
                result.append(c)

        if result:
            _cached_kosdaq = result
            _cached_kosdaq_at = today_str
            log.info(f"[UNIVERSE] 코스닥 에너지·반도체 {len(result)}종목 추출 완료")
            return result

    except Exception as e:
        log.warning(f"[UNIVERSE] 코스닥 추출 실패: {e} → Fallback 사용")

    _cached_kosdaq = _KOSDAQ_ENERGY_SEMI_FALLBACK[:]
    _cached_kosdaq_at = today_str
    log.info(f"[UNIVERSE] 코스닥 에너지·반도체 Fallback {len(_KOSDAQ_ENERGY_SEMI_FALLBACK)}종목 사용")
    return _KOSDAQ_ENERGY_SEMI_FALLBACK[:]
