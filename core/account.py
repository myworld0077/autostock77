"""
계좌 관리 모듈
- 예수금 조회
- 보유 종목 조회
"""
from core.api import api
from config.settings import settings
from utils.logger import log


def _to_int(value, default: int = 0) -> int:
    """KIS API가 '29450.0000' 같은 소수점 문자열을 반환해도 안전하게 int로 변환."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def get_balance() -> dict:
    """
    예수금(주문가능 현금) 조회

    Returns:
        {
            'cash': 주문가능현금,
            'total_eval': 총평가금액,
            'total_profit': 총평가손익,
            'profit_rate': 총수익률,
        }
    """
    tr_id = "VTTC8434R" if settings.is_paper else "TTTC8434R"
    params = {
        "CANO": settings.account_prefix,
        "ACNT_PRDT_CD": settings.account_suffix,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }
    data = api.get("/uapi/domestic-stock/v1/trading/inquire-balance", tr_id, params)

    if data.get("rt_cd") != "0":
        err_msg = data.get("msg1", "알 수 없는 오류")
        log.error(f"[ACCOUNT] 잔고 조회 실패: {err_msg}")
        return {"cash": 0, "total_eval": 0, "total_profit": 0, "profit_rate": 0.0}

    output2 = data.get("output2", [{}])
    summary = output2[0] if output2 else {}

    return {
        "cash":         _to_int(summary.get("dnca_tot_amt", 0)),
        "total_eval":   _to_int(summary.get("scts_evlu_amt", 0)),
        "total_profit": _to_int(summary.get("evlu_pfls_smtl_amt", 0)),
        "profit_rate":  float(summary.get("tot_evlu_pfls_rt", 0) or 0.0),
    }


def get_holdings() -> list[dict]:
    """
    보유 종목 목록 조회

    Returns:
        [
            {
                'code': 종목코드,
                'name': 종목명,
                'qty': 보유수량,
                'avg_price': 평균매입가,
                'cur_price': 현재가,
                'profit': 평가손익,
                'profit_rate': 수익률,
                'eval_amount': 평가금액,
            },
            ...
        ]
    """
    tr_id = "VTTC8434R" if settings.is_paper else "TTTC8434R"
    params = {
        "CANO": settings.account_prefix,
        "ACNT_PRDT_CD": settings.account_suffix,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }
    data = api.get("/uapi/domestic-stock/v1/trading/inquire-balance", tr_id, params)

    if data.get("rt_cd") != "0":
        err_msg = data.get("msg1", "알 수 없는 오류")
        log.error(f"[ACCOUNT] 보유종목 조회 실패: {err_msg}")
        return []

    holdings = []
    for item in data.get("output1", []):
        qty = _to_int(item.get("hldg_qty", 0))
        if qty <= 0:
            continue
        holdings.append({
            "code":        item.get("pdno", ""),
            "name":        item.get("prdt_name", ""),
            "qty":         qty,
            "avg_price":   _to_int(item.get("pchs_avg_pric", 0)),
            "cur_price":   _to_int(item.get("prpr", 0)),
            "profit":      _to_int(item.get("evlu_pfls_amt", 0)),
            "profit_rate": float(item.get("evlu_pfls_rt", 0) or 0.0),
            "eval_amount": _to_int(item.get("evlu_amt", 0)),
        })

    return holdings
