"""
감시 종목 동적 관리 모듈
========================

코스피 150 유니버스에서 매 사이클 최우선 10개 종목을 선정합니다.
"""
import FinanceDataReader as fdr
import pandas as pd
from typing import List, Set
from utils.logger import log

def get_dynamic_watchlist(universe_codes: List[str], held_codes: Set[str], max_slots: int) -> List[str]:
    """
    KOSPI 150 유니버스에서 보유한 종목을 제외하고,
    유동성(거래대금)과 상승 모멘텀(일대비 변동률)이 우수한 상위 N개 종목을 동적으로 선정합니다.

    Args:
        universe_codes (list): KOSPI 150 종목 코드 리스트
        held_codes (set): 현재 보유 중인 종목 코드 세트
        max_slots (int): 선정할 최대 종목 수 (10 - 보유종목수)

    Returns:
        list: 동적 감시 종목 코드 리스트
    """
    if max_slots <= 0:
        log.info("[WATCHLIST] 남은 슬롯이 없으므로 감시 종목을 선정하지 않습니다.")
        return []

    try:
        df = fdr.StockListing('KOSPI')
        if df is None or df.empty:
            log.warning("[WATCHLIST] FDR StockListing 결과가 비어있습니다. 기존 유니버스 앞부분을 사용합니다.")
            candidates = [c for c in universe_codes if c not in held_codes]
            return candidates[:max_slots]

        df['Code'] = df['Code'].astype(str).str.zfill(6)

        # 1. 유니버스에 속하고 현재 보유하지 않은 종목 필터링
        df_filtered = df[df['Code'].isin(universe_codes) & ~df['Code'].isin(held_codes)].copy()

        if df_filtered.empty:
            log.warning("[WATCHLIST] 필터링된 후보 종목이 없습니다.")
            return []

        # 2. 데이터 타입 변환 및 결측치 처리
        df_filtered['ChagesRatio'] = pd.to_numeric(df_filtered['ChagesRatio'], errors='coerce').fillna(0.0)
        df_filtered['Amount'] = pd.to_numeric(df_filtered['Amount'], errors='coerce').fillna(0.0)

        # 3. 거래대금(Amount) 기준 상위 50개 선정 (최소 유동성 확보)
        # 만약 후보가 50개보다 적으면 전체 사용
        df_liquid = df_filtered.sort_values(by='Amount', ascending=False).head(min(50, len(df_filtered)))

        # 4. 상위 50개 중 일간 상승률(ChagesRatio) 기준 내림차순 정렬하여 최종 N개 선정
        df_final = df_liquid.sort_values(by='ChagesRatio', ascending=False)

        selected_codes = df_final['Code'].head(max_slots).tolist()

        # 로그 출력
        log.info(f"[WATCHLIST] 동적 감시 종목 {len(selected_codes)}개 선정 (보유 제외, 남은 슬롯: {max_slots})")
        for code in selected_codes:
            row = df_final[df_final['Code'] == code].iloc[0]
            log.info(f"   - {code} ({row['Name']}): 대비 {row['ChagesRatio']:.2f}% | 거래대금: {row['Amount']/1e8:.1f}억")

        return selected_codes

    except Exception as e:
        log.error(f"[WATCHLIST] 동적 감시 종목 선정 실패: {e}. 유니버스 기본 정렬을 사용합니다.")
        candidates = [c for c in universe_codes if c not in held_codes]
        return candidates[:max_slots]
