"""
시세 조회 모듈
- 현재가, 일봉/분봉 데이터
"""
import pandas as pd
from core.api import api


def get_current_price(stock_code: str) -> dict:
    """
    주식 현재가 조회

    Returns:
        {
            'code': 종목코드,
            'name': 종목명,
            'price': 현재가,
            'change': 전일 대비,
            'change_rate': 등락률,
            'volume': 거래량,
            'high': 고가,
            'low': 저가,
            'open': 시가,
        }
    """
    tr_id = "FHKST01010100"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",   # 주식
        "FID_INPUT_ISCD": stock_code,
    }
    data = api.get("/uapi/domestic-stock/v1/quotations/inquire-price", tr_id, params)
    output = data.get("output", {})

    return {
        "code": stock_code,
        "name": output.get("hts_kor_isnm", ""),
        "price": int(output.get("stck_prpr", 0)),
        "change": int(output.get("prdy_vrss", 0)),
        "change_rate": float(output.get("prdy_ctrt", 0)),
        "volume": int(output.get("acml_vol", 0)),
        "high": int(output.get("stck_hgpr", 0)),
        "low": int(output.get("stck_lwpr", 0)),
        "open": int(output.get("stck_oprc", 0)),
        "market_cap": int(output.get("hts_avls", 0)),
    }


def get_daily_ohlcv(stock_code: str, period: str = "D", count: int = 60) -> pd.DataFrame:
    """
    일봉/주봉/월봉 OHLCV 데이터 조회

    Args:
        stock_code: 종목코드
        period: D=일, W=주, M=월
        count: 최근 N개

    Returns:
        DataFrame (date, open, high, low, close, volume)
    """
    from datetime import datetime, timedelta

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=count * 2)).strftime("%Y%m%d")

    tr_id = "FHKST03010100"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
        "FID_INPUT_DATE_1": start_date,
        "FID_INPUT_DATE_2": end_date,
        "FID_PERIOD_DIV_CODE": period,
        "FID_ORG_ADJ_PRC": "0",  # 수정주가
    }
    data = api.get("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", tr_id, params)
    records = data.get("output2", [])

    rows = []
    for r in records[:count]:
        rows.append({
            "date": r.get("stck_bsop_date", ""),
            "open": int(r.get("stck_oprc", 0)),
            "high": int(r.get("stck_hgpr", 0)),
            "low": int(r.get("stck_lwpr", 0)),
            "close": int(r.get("stck_clpr", 0)),
            "volume": int(r.get("acml_vol", 0)),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
    return df
