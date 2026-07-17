#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF 유니버스 관리 모듈 (Oracle Cloud Linux 호환)
- 나스닥 반도체 레버리지/인버스 2배 ETF (한국거래소 상장)
- 삼성전자 레버리지/인버스 ETF
- 레버리지 <-> 인버스 페어 매핑
"""
from typing import Dict, List, Tuple, Optional

# ─── 나스닥 반도체 ETF ──────────────────────────────────────────────────────
# 방향: LEVERAGE(2배 상승), INVERSE(하락/헤지)

# 나스닥 반도체 레버리지 2배 ETF
NASDAQ_SEMI_LEVERAGE: List[str] = [
    "305080",   # TIGER 미국필라델피아반도체레버리지(합성)   ← SOX 2배
    "441680",   # ACE 미국반도체레버리지(합성)               ← SOX 2배
]

# 나스닥 반도체 인버스 ETF
NASDAQ_SEMI_INVERSE: List[str] = [
    "371460",   # TIGER 미국필라델피아반도체인버스(합성)     ← SOX -1배
    "442580",   # ACE 미국반도체인버스(합성)                  ← SOX -1배
]

# ─── 삼성전자 ETF ────────────────────────────────────────────────────────────
# 삼성전자 레버리지 2배 ETF
SAMSUNG_LEVERAGE: List[str] = [
    "284430",   # KODEX 삼성전자레버리지 (삼성전자 2배)
]

# 삼성전자 인버스 ETF (-1배, 2배 인버스 미상장으로 대체)
SAMSUNG_INVERSE: List[str] = [
    "395160",   # KODEX 삼성전자인버스 (-1배)
]

# ─── 전체 ETF 목록 ──────────────────────────────────────────────────────────
ALL_LEVERAGE_ETF: List[str] = NASDAQ_SEMI_LEVERAGE + SAMSUNG_LEVERAGE
ALL_INVERSE_ETF:  List[str] = NASDAQ_SEMI_INVERSE  + SAMSUNG_INVERSE
ALL_ETF:          List[str] = ALL_LEVERAGE_ETF + ALL_INVERSE_ETF

# ─── 레버리지 ↔ 인버스 페어 매핑 ────────────────────────────────────────────
# key: 레버리지 코드 → value: 대응 인버스 코드
LEVERAGE_TO_INVERSE: Dict[str, str] = {
    "305080": "371460",   # TIGER 반도체레버리지 ↔ TIGER 반도체인버스
    "441680": "442580",   # ACE  반도체레버리지  ↔ ACE  반도체인버스
    "284430": "395160",   # KODEX 삼성전자레버리지 ↔ KODEX 삼성전자인버스
}

# 역방향 매핑 (인버스 → 레버리지)
INVERSE_TO_LEVERAGE: Dict[str, str] = {v: k for k, v in LEVERAGE_TO_INVERSE.items()}

# ─── ETF 종목명 매핑 (로그용) ───────────────────────────────────────────────
ETF_NAMES: Dict[str, str] = {
    "305080": "TIGER미국반도체레버리지",
    "371460": "TIGER미국반도체인버스",
    "441680": "ACE미국반도체레버리지",
    "442580": "ACE미국반도체인버스",
    "284430": "KODEX삼성전자레버리지",
    "395160": "KODEX삼성전자인버스",
}

# ─── 섹터 구분 ───────────────────────────────────────────────────────────────
SECTOR_MAP: Dict[str, str] = {
    "305080": "NASDAQ_SEMI",
    "371460": "NASDAQ_SEMI",
    "441680": "NASDAQ_SEMI",
    "442580": "NASDAQ_SEMI",
    "284430": "SAMSUNG",
    "395160": "SAMSUNG",
}


# ─── 유틸 함수 ───────────────────────────────────────────────────────────────

def is_leverage(code: str) -> bool:
    """레버리지 ETF 여부"""
    return code in ALL_LEVERAGE_ETF


def is_inverse(code: str) -> bool:
    """인버스 ETF 여부"""
    return code in ALL_INVERSE_ETF


def is_etf(code: str) -> bool:
    """ETF 여부 (레버리지+인버스 모두)"""
    return code in ALL_ETF


def get_pair(code: str) -> Optional[str]:
    """대응하는 레버리지/인버스 페어 코드 반환"""
    if code in LEVERAGE_TO_INVERSE:
        return LEVERAGE_TO_INVERSE[code]
    if code in INVERSE_TO_LEVERAGE:
        return INVERSE_TO_LEVERAGE[code]
    return None


def get_etf_name(code: str) -> str:
    """ETF 종목명 반환 (없으면 코드 반환)"""
    return ETF_NAMES.get(code, code)


def get_sector(code: str) -> str:
    """섹터 반환"""
    return SECTOR_MAP.get(code, "UNKNOWN")


def get_etf_watchlist(
    use_nasdaq_semi: bool = True,
    use_samsung: bool = True,
    include_inverse: bool = True,
) -> Tuple[List[str], List[str]]:
    """
    ETF 감시 종목 목록 반환

    Args:
        use_nasdaq_semi: 나스닥 반도체 ETF 포함 여부
        use_samsung: 삼성전자 ETF 포함 여부
        include_inverse: 인버스 ETF 포함 여부

    Returns:
        (leverage_list, inverse_list)
    """
    lev: List[str] = []
    inv: List[str] = []

    if use_nasdaq_semi:
        lev.extend(NASDAQ_SEMI_LEVERAGE)
        if include_inverse:
            inv.extend(NASDAQ_SEMI_INVERSE)

    if use_samsung:
        lev.extend(SAMSUNG_LEVERAGE)
        if include_inverse:
            inv.extend(SAMSUNG_INVERSE)

    return lev, inv
