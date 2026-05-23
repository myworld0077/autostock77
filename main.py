"""
AutoStock - 주식 자동매매 메인 엔진

운영 세션 (KST 기준, 한국투자증권 모의투자 기준):
    KRX 정규장    09:00 ~ 15:30
    ※ 모의투자는 정규장(09:00~15:30)만 지원

사용법:
    python main.py              # 복합 전략으로 실행
    python main.py --strategy volatility  # 변동성 돌파 전략
    python main.py --dashboard  # 웹 대시보드만 실행
"""
import sys
import time
import argparse
import schedule
import threading
from datetime import datetime, date as _date

from config.settings import settings
from core.market import get_current_price, get_daily_ohlcv
from core.account import get_balance, get_holdings
from core.order import buy_market, sell_market
from strategy.base import BaseStrategy
from strategy.ma_cross import MovingAverageCrossStrategy
from strategy.volatility import VolatilityBreakoutStrategy
from strategy.complex import Kospi200ComplexStrategy
from core.universe import get_kis_kospi200_top150, get_kosdaq150_energy_semi
from core.calendar import is_trading_day, trading_day_status, next_trading_day, verify_market_open_strict
from utils.logger import log
from utils import notifier
from core.keep_alive import prevent_sleep, allow_sleep


# ─── 감시 종목 리스트 (ma / volatility 전략용) ─────────────────────
WATCH_LIST = [
    "005930",   # 삼성전자
    "000660",   # SK하이닉스
    "035420",   # NAVER
    "035720",   # 카카오
    "051910",   # LG화학
    "005380",   # 현대차
    "000270",   # 기아차
    "068270",   # 셀트리온
    "207940",   # 삼성바이오로직스
    "028260",   # 삼성물산
]


# ─── 알림 임계값 상수 ──────────────────────────────────
SURGE_HELD_PCT = 3.0    # 보유종목 급변동 기준 (%)
SURGE_WATCH_PCT = 5.0    # 감시종목 급변동 기준 (%)
EMERGENCY_DROP = -10.0  # 긴급 하락 기준 (%)
SURGE_COOLDOWN_S = 1800   # 급변동 알림 쿨다운 (초, 30분)


class AutoTrader:
    """자동매매 엔진"""

    KOSDAQ_RATIO = 0.10  # 코스닥 에너지·반도체 투자 비중 한도 (총자산의 10%)

    def __init__(self, strategy: BaseStrategy, watch_list: list[str],
                 kosdaq_watch_list: list[str] | None = None):
        self.strategy = strategy
        self.watch_list = watch_list
        self.kosdaq_watch_list = kosdaq_watch_list or []
        self.trade_log: list[dict] = []         # 거래 이력
        self._price_cache: dict[str, int] = {}  # 이전 사이클 가격 (급변동 감지용)
        self._emergency_alerted: set[str] = set()       # 긴급 알림 발송 완료 종목
        self._surge_alerted: dict[str, float] = {}      # 급변동 알림 발송 시각 (쿨다운)

    # ── 급변동 감지 헬퍼 ──────────────────────────────────
    def _check_surge(self, code: str, name: str, cur_price: int, is_held: bool):
        """이전 사이클 대비 급변동 여부 확인 후 알림 전송"""
        prev = self._price_cache.get(code)
        if prev and prev > 0:
            change = (cur_price - prev) / prev * 100
            threshold = SURGE_HELD_PCT if is_held else SURGE_WATCH_PCT
            if abs(change) >= threshold:
                now_ts = time.time()
                last_t = self._surge_alerted.get(code, 0)
                if now_ts - last_t >= SURGE_COOLDOWN_S:  # 30분 쿨다운
                    notifier.notify_price_surge(code, name, cur_price, prev, change, is_held)
                    self._surge_alerted[code] = now_ts
        self._price_cache[code] = cur_price

    # ── 긴급 하락 감지 헬퍼 ──────────────────────────────
    def _check_emergency_drop(self, h: dict):
        """보유종목 -10% 이상 손실 시 긴급 알림 (회복 시 재알림 가능)"""
        code = h["code"]
        rate = h["profit_rate"]
        if rate <= EMERGENCY_DROP:
            if code not in self._emergency_alerted:
                notifier.notify_emergency_drop(
                    code, h["name"], h["qty"],
                    h["cur_price"], h["avg_price"], rate
                )
                self._emergency_alerted.add(code)
        else:
            # -10% 위로 회복되면 다음 하락 시 재알림 허용
            self._emergency_alerted.discard(code)

    def run_cycle(self, is_paused: bool = False):
        """1 사이클: 매도 체크 → 매수 체크 (is_paused면 매매는 스킵하고 모니터링만)"""
        log.info("=" * 50)
        state_msg = " (일시중지 - 모니터링만 수행)" if is_paused else ""
        log.info(f"📊 자동매매 사이클 시작 | 전략: {self.strategy.name}{state_msg}")
        log.info(f"   시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log.info("=" * 50)

        # 0) 잔고 확인
        try:
            balance = get_balance()
            log.info(f"💰 예수금: {balance['cash']:,}원 | "
                     f"총평가: {balance['total_eval']:,}원 | "
                     f"손익: {balance['total_profit']:,}원")
        except Exception as e:
            log.error(f"잔고 조회 실패: {e}")
            return

        # ── 자산 비중 관리 ──
        total_asset = balance["cash"] + balance["total_eval"]
        max_normal_invest = total_asset * 0.6  # 정상 매수 한도 (60%)
        max_total_invest = total_asset * 0.8   # 예비군 포함 매수 한도 (80%) - 절대 보존 20%

        # 1) 보유 종목: 급락 물타기 + 매도 체크
        sold_codes: set[str] = set()
        try:
            holdings = get_holdings()
            for h in holdings:
                code = h["code"]
                try:
                    # 긴급 -10% 하락 통보 (알림만, 매도 결정은 전략에 위임)
                    self._check_emergency_drop(h)
                    # 급변동 감지 (보유종목 ±3%)
                    self._check_surge(code, h["name"], h["cur_price"], is_held=True)

                    # [추가] 수익 시 현찰 보유: 예비군 투입 상태(>60%)일 때 0.5% 이상 수익 시 강제 익절
                    force_sell = False
                    if balance["total_eval"] > max_normal_invest and h["profit_rate"] > 0.5:
                        log.info(f"💡 예비군 투입 상태 + 수익 전환 → 현찰 보유를 위한 강제 익절: {h['name']}")
                        force_sell = True

                    df = get_daily_ohlcv(code)
                    if force_sell or self.strategy.should_sell(code, df, h["cur_price"], h["avg_price"]):
                        if is_paused:
                            log.info(f"  ⏸️ 일시중지 중 - 매도 조건 충족이나 보류: {h['name']}({code})")
                        else:
                            result = sell_market(code, h["qty"])
                            if result["success"]:
                                sold_codes.add(code)
                                notifier.notify_sell(
                                    code, h["name"], h["qty"],
                                    h["cur_price"], h["profit_rate"]
                                )
                                self.trade_log.append({
                                    "time": datetime.now().isoformat(),
                                    "side": "sell",
                                    "code": code,
                                    "name": h["name"],
                                    "qty": h["qty"],
                                    "price": h["cur_price"],
                                    "profit_rate": h["profit_rate"],
                                })
                                balance["total_eval"] -= (h["qty"] * h["cur_price"])
                                balance["cash"] += (h["qty"] * h["cur_price"])
                                continue  # 매도 성공 시 물타기 체크 안 함

                    # [추가] 예비군성격 20% 급락시 투입 (물타기)
                    if (h["profit_rate"] <= EMERGENCY_DROP
                            and balance["total_eval"] < max_total_invest):
                        if is_paused:
                            log.info(f"  ⏸️ 일시중지 중 - 급락 물타기 조건 충족이나 보류: {h['name']}({code})")
                        else:
                            available_reserve = max_total_invest - balance["total_eval"]
                            target_reserve_amt = min(available_reserve, total_asset * 0.1)

                            qty = int(target_reserve_amt // h["cur_price"])
                            if qty > 0 and (qty * h["cur_price"] <= balance["cash"]):
                                log.info(f"🚨 급락 감지! 예비군 투입 (물타기) → {h['name']} {qty}주 매수")
                                r = buy_market(code, qty)
                                if r["success"]:
                                    notifier.notify_buy(code, h["name"], qty, h["cur_price"])
                                balance["total_eval"] += (qty * h["cur_price"])
                                balance["cash"] -= (qty * h["cur_price"])

                except Exception as e:
                    log.error(f"매도/물타기 처리 오류 ({code}): {e}")
                time.sleep(0.5)
        except Exception as e:
            log.error(f"보유종목 조회 실패: {e}")
            holdings = []

        # 2) 감시 종목 매수 체크 (정상 한도 60% 내에서만 매수)
        held_codes = {h["code"] for h in holdings} - sold_codes
        normal_cash_available = max_normal_invest - balance["total_eval"]

        if len(held_codes) >= settings.MAX_STOCKS:
            log.info(f"⚠️ 최대 보유 종목 수({settings.MAX_STOCKS}) 도달 - 매수 스킵")
        elif normal_cash_available <= 0:
            log.info("⚠️ 정상 매수 한도(자산 60%) 소진 - 현금 40% 보존을 위해 신규 매수 스킵")
        else:
            for code in self.watch_list:
                if code in held_codes:
                    continue  # 이미 보유 중

                try:
                    price_info = get_current_price(code)
                    cur_price = price_info["price"]
                    name = price_info["name"]

                    # 급변동 감지 (감시종목 ±5%)
                    self._check_surge(code, name, cur_price, is_held=False)

                    df = get_daily_ohlcv(code)
                    if self.strategy.should_buy(code, df, cur_price):
                        if is_paused:
                            log.info(f"  ⏸️ 일시중지 중 - 매수 조건 충족이나 보류: {name}({code})")
                        else:
                            # 현금 40% 상시 보유를 위해 정상 가용 금액(normal_cash_available) 내에서 분할 매수
                            remaining_slots = max(1, settings.MAX_STOCKS - len(held_codes))
                            target_buy_amt = normal_cash_available // remaining_slots

                            qty = int(target_buy_amt // cur_price)
                            if qty <= 0:
                                msg = f"  {name}({code}) - 매수 금액 부족 (현재가: {cur_price:,}원, 할당금액: {target_buy_amt:,}원)"
                                log.info(msg)
                                continue

                            if qty * cur_price > balance["cash"]:
                                qty = int(balance["cash"] // cur_price)
                                if qty <= 0:
                                    log.info(f"  {name}({code}) - 예수금 부족")
                                    continue

                            result = buy_market(code, qty)
                            if result["success"]:
                                normal_cash_available -= (qty * cur_price)
                                balance["total_eval"] += (qty * cur_price)
                                balance["cash"] -= (qty * cur_price)
                                held_codes.add(code)  # 보유 목록 업데이트 (슬롯 계산용)
                                notifier.notify_buy(code, name, qty, cur_price)
                                self.trade_log.append({
                                    "time": datetime.now().isoformat(),
                                    "side": "buy",
                                    "code": code,
                                    "name": name,
                                    "qty": qty,
                                    "price": cur_price,
                                })
                    else:
                        log.info(f"  ⏸️ {name}({code}) - 현재가: {cur_price:,}원 → 매수 조건 미충족")
                except Exception as e:
                    log.error(f"매수 처리 오류 ({code}): {e}")
                time.sleep(0.5)

        # 3) 코스닥 에너지·반도체 매수 체크 (총자산의 10% 한도)
        kosdaq_set = set(self.kosdaq_watch_list)
        if kosdaq_set and len(held_codes) < settings.MAX_STOCKS:
            # 현재 코스닥 보유 금액 계산
            kosdaq_held_eval = sum(
                h["qty"] * h["cur_price"]
                for h in holdings
                if h["code"] in kosdaq_set and h["code"] not in sold_codes
            )
            kosdaq_limit = total_asset * self.KOSDAQ_RATIO  # 총자산의 10%
            kosdaq_available = kosdaq_limit - kosdaq_held_eval

            if kosdaq_available <= 0:
                log.info(f"⚠️ 코스닥 에너지·반도체 투자한도 소진 "
                         f"(보유: {kosdaq_held_eval:,.0f}원 / 한도: {kosdaq_limit:,.0f}원)")
            else:
                log.info(f"🔋 코스닥 에너지·반도체 매수 체크 "
                         f"(가용: {kosdaq_available:,.0f}원 / 한도: {kosdaq_limit:,.0f}원)")
                for code in self.kosdaq_watch_list:
                    if code in held_codes:
                        continue
                    if len(held_codes) >= settings.MAX_STOCKS:
                        break
                    if kosdaq_available <= 0:
                        break

                    try:
                        price_info = get_current_price(code)
                        cur_price = price_info["price"]
                        name = price_info["name"]

                        self._check_surge(code, name, cur_price, is_held=False)

                        df = get_daily_ohlcv(code)
                        if self.strategy.should_buy(code, df, cur_price):
                            if is_paused:
                                log.info(f"  ⏸️ 일시중지 - 코스닥 매수 보류: {name}({code})")
                            else:
                                qty = int(min(kosdaq_available, balance["cash"]) // cur_price)
                                if qty <= 0:
                                    continue

                                result = buy_market(code, qty)
                                if result["success"]:
                                    cost = qty * cur_price
                                    kosdaq_available -= cost
                                    balance["total_eval"] += cost
                                    balance["cash"] -= cost
                                    held_codes.add(code)
                                    notifier.notify_buy(code, name, qty, cur_price)
                                    self.trade_log.append({
                                        "time": datetime.now().isoformat(),
                                        "side": "buy",
                                        "code": code,
                                        "name": name,
                                        "qty": qty,
                                        "price": cur_price,
                                        "market": "KOSDAQ",
                                    })
                    except Exception as e:
                        log.error(f"코스닥 매수 오류 ({code}): {e}")
                    time.sleep(0.5)

        # 사이클 완료
        log.info("✅ 사이클 완료\n")
        # ⚠️ notify_profit_report는 매 사이클 자동 전송 안 함 (중복 전송 방지)
        #    → 08:30 장전 / 15:35 일일 마감 리포트 스케줄로만 전송


def main():
    prevent_sleep()
    parser = argparse.ArgumentParser(description="AutoStock 주식 자동매매")
    parser.add_argument("--strategy", choices=["ma", "volatility", "complex"], default="complex",
                        help="매매 전략 (ma: 이동평균, volatility: 변동성 돌파, complex: 코스피200 복합)")
    parser.add_argument("--interval", type=int, default=10,
                        help="매매 체크 주기 (분)")
    parser.add_argument("--once", action="store_true",
                        help="1회만 실행 후 종료")
    parser.add_argument("--dashboard", action="store_true",
                        help="웹 대시보드 실행")
    args = parser.parse_args()

    # 대시보드 모드
    if args.dashboard:
        from dashboard.app import run_dashboard
        run_dashboard()
        return

    # 설정 검증
    if not settings.validate():
        log.error("❌ .env 설정 오류 — 위 메시지를 확인하고 .env 파일을 수정하세요.")
        log.error("   모의투자: PAPER_APP_KEY / PAPER_APP_SECRET / PAPER_CANO")
        log.error("   실전투자: REAL_APP_KEY  / REAL_APP_SECRET  / REAL_CANO")
        sys.exit(1)
    log.info(f"[CONFIG] {settings.describe()}")

    # ─── 6월 5일까지 모의투자 강제 및 사용자 권한 확인 ───
    current_date = datetime.now().date()
    target_date = _date(2026, 6, 5)

    if current_date <= target_date:
        if settings.TRADE_MODE != "paper":
            log.warning("⚠️ [안전 조치] 2026년 6월 5일까지는 강제로 '모의투자(paper)' 모드로 실행됩니다.")
            settings.TRADE_MODE = "paper"
            log.warning("👉 주의: .env에 PAPER_APP_KEY, PAPER_APP_SECRET, PAPER_CANO 가 설정되어 있어야 합니다.")
    else:
        if settings.TRADE_MODE != "paper":
            log.warning("[REAL] 6월 5일이 경과하여 '실전투자(real)' 모드 진입이 가능합니다.")
            approved = notifier.request_real_trading_approval(timeout_seconds=120)
            if not approved:
                log.info("[REAL] 사용자가 실전투자 실행을 취소했습니다.")
                notifier.notify_stop("실전투자 승인 거부 또는 시간 초과")
                sys.exit(0)
            log.info("[REAL] 승인 완료 → 실전투자를 시작합니다.")

    # 전략 및 감시 종목 선택
    kosdaq_watch_list = []
    if args.strategy == "complex":
        strategy = Kospi200ComplexStrategy()
        watch_list = get_kis_kospi200_top150()
        log.info("  KOSPI 200 종목 중 시총 상위 150위를 한국투자증권 API로 갱신하여 감시합니다.")
        # 코스닥 에너지·반도체 종목 (총자산의 10% 한도)
        kosdaq_watch_list = get_kosdaq150_energy_semi()
        log.info(f"  코스닥 에너지·반도체 {len(kosdaq_watch_list)}종목 추가 감시 (투자한도: 총자산 10%)")
    elif args.strategy == "volatility":
        strategy = VolatilityBreakoutStrategy(k=0.5)
        watch_list = WATCH_LIST
    else:
        strategy = MovingAverageCrossStrategy(short_window=5, long_window=20)
        watch_list = WATCH_LIST

    mode_label = "paper" if settings.is_paper else "real"
    log.info("=" * 50)
    log.info("  AutoStock 자동매매 시작")
    log.info(f"  모드: {'[Paper] 모의투자' if settings.is_paper else '[Real] 실전투자'}")
    log.info(f"  감시 종목: KOSPI {len(watch_list)}개 + KOSDAQ {len(kosdaq_watch_list)}개")
    log.info(f"  1회 매수 금액: {settings.BUY_AMOUNT:,}원")
    if kosdaq_watch_list:
        log.info(f"  코스닥 비중 한도: 총자산의 {AutoTrader.KOSDAQ_RATIO*100:.0f}%")
    log.info("=" * 50)

    # 텔레그램: 프로그램 시작 알림
    notifier.notify_start(mode_label, strategy.name, len(watch_list) + len(kosdaq_watch_list))

    trader = AutoTrader(strategy=strategy, watch_list=watch_list,
                        kosdaq_watch_list=kosdaq_watch_list)

    if args.once:
        trader.run_cycle()
        return

    # ─── 세션 정의 ────────────────────────────────────────────
    # (시작H, 시작M, 종료H, 종료M, 세션명)
    SESSIONS = [
        (9,  0, 15, 30, "KRX 정규장"),
    ]

    def get_current_session(dt: datetime) -> str | None:
        """현재 시각이 속한 세션명 반환. 장외 시간이면 None."""
        t = dt.hour * 60 + dt.minute
        for sh, sm, eh, em, name in SESSIONS:
            if sh * 60 + sm <= t <= eh * 60 + em:
                return name
        return None

    # ─── 오늘 영업일 확인 + 현재 세션 계산 ──────────────────────────
    now = datetime.now()
    today = now.date()
    session: str | None = get_current_session(now)

    last_session: str | None = session
    last_date: _date = today
    is_today_trading: bool = is_trading_day(today)  # 당일 영업일 여부 캐싱
    is_paused_by_user: bool = False
    morning_report_sent_date: _date | None = None   # 장전 리포트 당일 전송 완료 날짜
    trade_report_sent_date: _date | None = None     # 15:40 매매내역 리포트 당일 전송 완료 날짜

    # 영업일 상태 로그 (캐싱된 is_today_trading 사용 — 재호출 방지)
    if is_today_trading:
        log.info(f"[CALENDAR] ✅ {today} 영업일")
    else:
        nd = next_trading_day(today)
        log.info(f"[CALENDAR] 🚫 {today} 휴장 → 다음 영업일: {nd}")
        log.info(f"[CALENDAR] 오늘은 휴장일. 다음 영업일: {nd} — 프로그램은 대기 상태로 실행됩니다.")

    run_lock = threading.Lock()
    def run_thread_job(paused_flag: bool):
        with run_lock:
            trader.run_cycle(paused_flag)

    # 스케줄 등록 (클로저가 is_today_trading/session/is_paused_by_user 상태를 읽도록)
    def conditional_run_cycle():
        # nonlocal 없이 읽기만 하므로 루프에서 갱신된 값이 자동 반영됨
        if is_today_trading and session:
            if run_lock.locked():
                log.warning("⚠️ 이전 매매 사이클이 아직 실행 중입니다. 이번 주기는 스킵합니다.")
                return
            threading.Thread(target=run_thread_job, args=(is_paused_by_user,), daemon=True).start()

    schedule.every(args.interval).minutes.do(conditional_run_cycle)

    # ── 리포트 스케줄링 ──
    def send_daily_report_job(label: str):
        if not is_trading_day(_date.today()):
            return
        try:
            from core.account import get_balance as _gb, get_holdings as _gh
            notifier.notify_daily_report(_gb(), _gh(), label)
        except Exception as _e:
            log.warning(f"마감 리포트 실패: {_e}")

    def send_morning_report_job():
        if not is_trading_day(_date.today()):
            return
        try:
            from core.account import get_balance as _gb, get_holdings as _gh
            notifier.notify_profit_report(_gb(), _gh())
        except Exception as _e:
            log.warning(f"장전 리포트 실패: {_e}")

    # 리포트 스케줄링 — ⚠️ 보조 백업 역할
    # 실제 리포트는 세션 전환 감지(L479~)를 주 트리거로 사용해 불발 방지
    # schedule.at()은 해당 시각이 이미 지났으면 다음 날 실행 → 단독 의존 시 불발 위험
    schedule.every().day.at("08:30").do(send_morning_report_job)
    schedule.every().day.at("15:35").do(lambda: send_daily_report_job("KRX 정규장"))

    # 운영 정보 로그
    log.info(f"⏰ {args.interval}분 간격 | 운영시간: 09:00-15:30 (KRX 정규장)")
    log.info("   📨 텔레그램 리포트: 장전 08:30 / 마감 15:30 이후")
    log.info("   (Ctrl+C 로 종료)")

    # 최초 1회 즉시 실행 (영업일 + 세션 중일 때만) — 캐싱된 is_today_trading 사용
    if is_today_trading and session:
        log.info(f"🟢 현재 세션: {session} — 즉시 1회 실행")
        threading.Thread(target=run_thread_job, args=(is_paused_by_user,), daemon=True).start()
    elif not is_today_trading:
        log.info("⏸️  휴장일 — 다음 영업일 세션 시작까지 대기 중...")
    else:
        log.info("⏸️  장외 시간 — 첫 세션 시작까지 대기 중...")

    # ── 텔레그램 제어 초기 상태 ──
    last_update_id: int = notifier._get_last_update_id()

    try:

        while True:
            # ── 텔레그램 제어 명령어 확인 (모든 수신 명령어에 즉시 응답) ──
            cmds, last_update_id = notifier.check_commands(last_update_id)
            for cmd in cmds:
                if cmd == "0":
                    if not is_paused_by_user:
                        is_paused_by_user = True
                        log.info("[USER CONTROL] 텔레그램 '0' 수신 → 자동매매 중지")
                        notifier.notify_status(False, changed=True)   # 즉시 응답: 상태 변경
                    else:
                        log.info("[USER CONTROL] 텔레그램 '0' 수신 (이미 중지 상태) → 즉시 응답")
                        notifier.notify_status(False, changed=False)  # 즉시 응답: 이미 중지
                elif cmd == "1":
                    if is_paused_by_user:
                        is_paused_by_user = False
                        log.info("[USER CONTROL] 텔레그램 '1' 수신 → 자동매매 가동")
                        notifier.notify_status(True, changed=True)    # 즉시 응답: 상태 변경
                    else:
                        log.info("[USER CONTROL] 텔레그램 '1' 수신 (이미 가동 상태) → 즉시 응답")
                        notifier.notify_status(True, changed=False)   # 즉시 응답: 이미 가동
                elif cmd == "2":  # 현재 가동 상태 조회
                    is_actually_running = (is_today_trading and bool(session) and not is_paused_by_user)
                    log.info(f"[USER CONTROL] 텔레그램 '2' 수신 → 즉시 상태 조회 응답 (가동={is_actually_running})")
                    
                    try:
                        from core.account import get_balance
                        balance_info = get_balance()
                    except Exception as e:
                        log.warning(f"상태 조회 중 잔고 조회 실패: {e}")
                        balance_info = None

                    notifier.notify_status_detail(            # 즉시 응답: 상세 상태
                        is_running=is_actually_running,
                        is_trading_day=is_today_trading,
                        session=session,
                        is_paused=is_paused_by_user,
                        balance=balance_info,
                    )

            now = datetime.now()
            today = now.date()

            # ─── 날짜 변경 감지 → 영업일 재확인 ──────────────────────
            if today != last_date:
                last_date = today
                morning_report_sent_date = None   # 날짜 변경 시 장전 리포트 플래그 리셋
                trade_report_sent_date = None     # 날짜 변경 시 15:40 매매내역 리포트 플래그 리셋
                trader.trade_log.clear()          # 이전 영업일의 매매내역 클리어
                is_today_trading = is_trading_day(today)
                status = trading_day_status(today)
                log.info(f"[CALENDAR] 날짜 변경 → {status}")
                if not is_today_trading:
                    nd = next_trading_day(today)
                    log.info(f"[CALENDAR] 휴장일 대기 중... 다음 영업일: {nd}")
                else:
                    # 영업일이면 유니버스 자동 갱신
                    if args.strategy == "complex":
                        trader.watch_list = get_kis_kospi200_top150()
                        trader.kosdaq_watch_list = get_kosdaq150_energy_semi()
                        log.info(f"[UNIVERSE] 새 영업일 유니버스 자동 갱신 완료: "
                                 f"KOSPI {len(trader.watch_list)}종목 + "
                                 f"KOSDAQ {len(trader.kosdaq_watch_list)}종목")

            # ─── 08:30 장전 리포트 주 트리거 (루프 시각 체크 + 당일 플래그) ──────────
            # schedule.at()은 시작 시각이 지나면 다음 날 실행하므로 단독 의존 금지
            if (is_today_trading
                    and now.hour == 8 and now.minute >= 30
                    and morning_report_sent_date != today):
                if verify_market_open_strict():
                    morning_report_sent_date = today
                    try:
                        from core.account import get_balance as _gb, get_holdings as _gh
                        notifier.notify_profit_report(_gb(), _gh())
                        log.info("[리포트] 08:30 장전 리포트 전송 완료")
                    except Exception as _e:
                        log.warning(f"08:30 장전 리포트 실패: {_e}")
                else:
                    # 교차 검증 실패 시 당일 플래그를 세워 루프 반복 방지
                    morning_report_sent_date = today

            # ─── 15:40 당일 매매내역 리포트 트리거 (루프 시각 체크 + 당일 플래그) ────────
            if (is_today_trading
                    and now.hour == 15 and now.minute >= 40
                    and trade_report_sent_date != today):
                if verify_market_open_strict():
                    trade_report_sent_date = today
                    try:
                        notifier.notify_trade_log_report(trader.trade_log)
                        log.info("[리포트] 15:40 당일 매매내역 리포트 전송 완료")
                    except Exception as _e:
                        log.warning(f"15:40 당일 매매내역 리포트 실패: {_e}")
                else:
                    trade_report_sent_date = today

            session = get_current_session(now)


            # ─── 세션 전환 감지 ───────────────────────────────────────
            if session != last_session:
                if session:
                    # ── 세션 시작 (09:00) ──
                    log.info(f"\U0001f514 세션 시작: {session}")
                    # ▶️ 08:30에 이미 전송된 경우 중복 스킵, 미전송이면 뺈챙 전송
                    if is_today_trading and morning_report_sent_date != today:
                        morning_report_sent_date = today
                        try:
                            from core.account import get_balance as _gb, get_holdings as _gh
                            notifier.notify_profit_report(_gb(), _gh())
                            log.info("[리포트] 세션 시작 시 장전 리포트 전송 (빨친 경우에만)")
                        except Exception as _e:
                            log.warning(f"세션 시작 리폤트 실패: {_e}")
                    else:
                        log.info("[리포트] 08:30 장전 리포트 이미 전송됨 — 세션 시작 중복 스킵")
                else:
                    # ── 세션 종료 (15:30 이후 장외 시간 진입) ──
                    log.info("\U0001f515 장외 시간 진입 — 다음 세션까지 대기")
                    # ▶️ 마감 리포트: 세션 종료 시 반드시 전송
                    #   schedule.at("15:35")는 프로그램 종료 시에 누락될 수 있으므로 세션 종료를 트리거로 사용
                    if is_today_trading and verify_market_open_strict():
                        try:
                            from core.account import get_balance as _gb, get_holdings as _gh
                            notifier.notify_daily_report(_gb(), _gh(), "KRX 정규장")
                            log.info("[리포트] 마감 리포트 전송 완료")
                        except Exception as _e:
                            log.warning(f"마감 리폤트 실패: {_e}")

                last_session = session

            # ─── 텔레그램 제어 및 리포트 등을 위한 스케줄 실행 ─────────────────
            # is_paused_by_user 상태에서는 매매(trader.run_cycle)가 돌지 않아야 함.
            # 하지만 08:50, 15:31 리포트는 전송되어야 하므로 run_pending() 자체는 항상 실행합니다.
            schedule.run_pending()

            time.sleep(1)
    except KeyboardInterrupt:
        allow_sleep()
        log.info("\n[STOP] 자동매매를 종료합니다.")
        notifier.notify_stop("사용자 수동 종료 (Ctrl+C)")
    except Exception as e:
        allow_sleep()
        log.error(f"[FATAL] 예상치 못한 오류로 종료: {e}")
        notifier.notify_stop(f"오류 종료: {e}")
        raise


if __name__ == "__main__":
    main()
