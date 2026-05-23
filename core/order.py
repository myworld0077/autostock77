"""
주문 실행 모듈
- 시장가/지정가 매수·매도
"""
from core.api import api
from config.settings import settings
from utils.logger import log


def buy_market(stock_code: str, qty: int) -> dict:
    """시장가 매수"""
    return _place_order(stock_code, qty, order_type="buy", price=0)


def buy_limit(stock_code: str, qty: int, price: int) -> dict:
    """지정가 매수"""
    return _place_order(stock_code, qty, order_type="buy", price=price)


def sell_market(stock_code: str, qty: int) -> dict:
    """시장가 매도"""
    return _place_order(stock_code, qty, order_type="sell", price=0)


def sell_limit(stock_code: str, qty: int, price: int) -> dict:
    """지정가 매도"""
    return _place_order(stock_code, qty, order_type="sell", price=price)


def _place_order(stock_code: str, qty: int, order_type: str, price: int) -> dict:
    """
    공통 주문 처리

    Args:
        stock_code: 종목코드
        qty: 수량
        order_type: 'buy' | 'sell'
        price: 0이면 시장가, 양수면 지정가

    Returns:
        {'success': bool, 'msg': str, 'order_no': str}
    """
    is_buy = order_type == "buy"
    is_market = price == 0

    # tr_id 결정 (KIS 공식 문서 기준)
    # 모의투자: 매수=VTTC0801U, 매도=VTTC0802U
    # 실전투자: 매수=TTTC0802U, 매도=TTTC0801U
    if settings.is_paper:
        tr_id = "VTTC0801U" if is_buy else "VTTC0802U"
    else:
        tr_id = "TTTC0802U" if is_buy else "TTTC0801U"

    body = {
        "CANO": settings.account_prefix,
        "ACNT_PRDT_CD": settings.account_suffix,
        "PDNO": stock_code,
        "ORD_DVSN": "01" if is_market else "00",  # 01=시장가, 00=지정가
        "ORD_QTY": str(qty),
        "ORD_UNPR": "0" if is_market else str(price),
    }

    side = "매수" if is_buy else "매도"
    price_type = "시장가" if is_market else f"지정가({price:,}원)"
    log.info(f"[ORDER] {side} 주문 → {stock_code} / {qty}주 / {price_type}")

    try:
        data = api.post("/uapi/domestic-stock/v1/trading/order-cash", tr_id, body)
        rt_cd = data.get("rt_cd", "")
        msg = data.get("msg1", "")
        order_no = data.get("output", {}).get("ODNO", "")

        if rt_cd == "0":
            log.info(f"[ORDER] ✅ {side} 체결 성공 - 주문번호: {order_no}")
            return {"success": True, "msg": msg, "order_no": order_no}
        else:
            log.warning(f"[ORDER] ❌ {side} 실패 - {msg}")
            return {"success": False, "msg": msg, "order_no": ""}
    except Exception as e:
        log.error(f"[ORDER] 주문 오류: {e}")
        return {"success": False, "msg": str(e), "order_no": ""}
