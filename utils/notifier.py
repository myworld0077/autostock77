"""
텔레그램 알림 모듈

알림 종류:
  - 프로그램 시작 / 정상 종료 / 오류 종료
  - API 인증 실패 (키 오류)
  - 매수 / 매도 체결
  - 실전투자 전환 승인 요청 (텔레그램 버튼 또는 코드 입력)

텔레그램 미설정 시 모든 함수는 조용히 무시됩니다.
"""
import time
import requests
from datetime import datetime
from utils.logger import log


def _get_cfg():
    """설정 지연 로드 (순환 임포트 방지)"""
    from config.settings import settings
    return settings.TELEGRAM_TOKEN, settings.TELEGRAM_CHAT_ID


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """텔레그램 메시지 전송. 성공 시 True 반환 (휴장일 발송 원천 차단 적용)."""
    # ─── 휴장일 발송 원천 차단 2중 안전 장치 ───
    try:
        from core.calendar import is_trading_day, verify_market_open_strict
        
        # 1차 검증: 주말, 공휴일, 연말 휴장일, KIS API 판정 기준 휴장일인지 확인
        if not is_trading_day():
            log.warning(f"[TELEGRAM] 🚫 휴장일 전송 차단 (is_trading_day=False) | 메시지 요약: {text[:40].strip()}...")
            return False
            
        # 2차 검증: KIS API 실패 시 보수적으로 영업일 처리된 경우, 실제 현재가 조회를 통한 최종 교차 검증
        if not verify_market_open_strict():
            log.warning(f"[TELEGRAM] 🚫 2중 실시간 검증 실패로 전송 차단 | 메시지 요약: {text[:40].strip()}...")
            return False
            
    except Exception as e:
        # 혹시 모를 모듈 임포트 에러나 조회 예외 시 안전을 위해 차단 처리
        log.warning(f"[TELEGRAM] 🚫 영업일 검증 중 오류 발생으로 전송 차단: {e} | 메시지 요약: {text[:40].strip()}...")
        return False

    token, chat_id = _get_cfg()
    if not token or not chat_id:
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    
    # 텔레그램 서버 일시 장애 또는 인터넷 순단 대비 최대 3회 재시도 (지수 대기)
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=5)
            if resp.status_code == 200:
                return True
            log.warning(f"[TELEGRAM] 전송 지연/오류 재시도 ({attempt+1}/3): HTTP {resp.status_code} {resp.text[:50]}")
        except Exception as e:
            log.warning(f"[TELEGRAM] 전송 지연/오류 재시도 ({attempt+1}/3): {e}")
        
        if attempt < 2:
            sleep_time = 2 ** attempt + 1
            time.sleep(sleep_time)
            
    log.error(f"[TELEGRAM] ❌ 최종 전송 실패 | 메시지 요약: {text[:40].strip()}...")
    return False


# ── 프로그램 생명주기 알림 ──────────────────────────────────────────

def notify_start(mode: str, strategy: str, watch_count: int):
    """프로그램 시작 알림"""
    mode_str = "🧪 모의투자" if mode == "paper" else "🔴 실전투자"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"🚀 <b>AutoStock 시작</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"모드: {mode_str}\n"
        f"전략: {strategy}\n"
        f"감시종목: {watch_count}개\n"
        f"시각: {now_str}"
    )
    if send_message(msg):
        log.info("[TELEGRAM] 프로그램 시작 알림 전송")


def notify_stop(reason: str = "정상 종료"):
    """프로그램 종료 알림"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"🛑 <b>AutoStock 종료</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"사유: {reason}\n"
        f"시각: {now_str}"
    )
    if send_message(msg):
        log.info("[TELEGRAM] 프로그램 종료 알림 전송")


def notify_error(error_msg: str):
    """오류 발생 알림"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"⚠️ <b>AutoStock 오류</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"{error_msg}\n"
        f"시각: {now_str}"
    )
    send_message(msg)


def notify_auth_error(mode: str, error_code: str = ""):
    """API 인증 실패 알림"""
    key_var = "PAPER_APP_KEY" if mode == "paper" else "REAL_APP_KEY"
    secret_var = "PAPER_APP_SECRET" if mode == "paper" else "REAL_APP_SECRET"
    mode_str = "모의투자" if mode == "paper" else "실전투자"
    msg = (
        f"🔑 <b>API 인증 실패</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"모드: {mode_str}\n"
        f"오류코드: {error_code or '-'}\n\n"
        f"<b>해결 방법:</b>\n"
        f"1. KIS 개발자센터 접속\n"
        f"   https://apiportal.koreainvestment.com\n"
        f"2. {mode_str}용 APP_KEY 재발급\n"
        f"3. .env 파일 수정:\n"
        f"   {key_var}=새키\n"
        f"   {secret_var}=새시크릿"
    )
    send_message(msg)


# ── 급변동 / 긴급 하락 알림 ──────────────────────────────────────────

def notify_price_surge(
    stock_code: str, name: str,
    cur_price: int, prev_price: int,
    change_rate: float,
    is_held: bool = False,
):
    """급변동 알림 (보유종목 ±3% / 감시종목 ±5% 이상)"""
    if change_rate > 0:
        direction, emoji = "급등", "🚀"
    else:
        direction, emoji = "급락", "📉"

    held_tag = " [보유]" if is_held else " [감시]"
    msg = (
        f"{emoji} <b>[급변동] {name}({stock_code}) {direction}{held_tag}</b>\n"
        f"➡️ {prev_price:,}원 → {cur_price:,}원 ({change_rate:+.1f}%)"
    )
    if send_message(msg):
        log.warning(f"[ALERT] 급변동 알림 → {name}({stock_code}) {change_rate:+.1f}%")


def notify_emergency_drop(
    stock_code: str, name: str,
    qty: int, cur_price: int, avg_price: int,
    profit_rate: float,
):
    """긴급! 보유종목 10% 이상 손실 발생 통보"""
    loss_amt = (cur_price - avg_price) * qty
    msg = (
        f"🚨 <b>[긴급 손실] {name}({stock_code})</b>\n"
        f"📉 수익률: {profit_rate:+.1f}% (손실 {loss_amt:+,}원)\n"
        f"➡️ {qty:,}주 보유 | 단가 {avg_price:,}원 → 현재 {cur_price:,}원"
    )
    if send_message(msg):
        log.warning(
            f"[EMERGENCY] 긴급 손실 알림 → {name}({stock_code}) "
            f"{profit_rate:+.1f}% / {loss_amt:+,}원"
        )


# ── 거래 알림 ────────────────────────────────────────────────────────

def notify_buy(stock_code: str, name: str, qty: int, price: int):
    """매수 체결 알림"""
    msg = (
        f"🟢 <b>매수 체결</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"종목: {name} ({stock_code})\n"
        f"수량: {qty:,}주\n"
        f"가격: {price:,}원\n"
        f"금액: {qty * price:,}원\n"
        f"시각: {datetime.now().strftime('%H:%M:%S')}"
    )
    send_message(msg)


def notify_sell(stock_code: str, name: str, qty: int, price: int, profit_rate: float):
    """매도 체결 알림"""
    emoji = "📈" if profit_rate >= 0 else "📉"
    msg = (
        f"🔴 <b>매도 체결</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"종목: {name} ({stock_code})\n"
        f"수량: {qty:,}주\n"
        f"가격: {price:,}원\n"
        f"수익률: {emoji} {profit_rate:+.1f}%\n"
        f"시각: {datetime.now().strftime('%H:%M:%S')}"
    )
    send_message(msg)


# ── 수익률 리포트 ────────────────────────────────────────────────────

def notify_profit_report(balance: dict, holdings: list):
    """
    현재 잔고 및 보유종목 수익률 리포트 전송.
    텔레그램 미설정이면 전송 생략.
    """
    token, chat_id = _get_cfg()
    if not token or not chat_id:
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_profit = balance.get('total_profit', 0)
    profit_emoji = "📈" if total_profit >= 0 else "📉"

    lines = [
        "📊 <b>수익률 리포트</b>",
        "━━━━━━━━━━━━━━",
        f"⏰ {now_str}",
        "",
        f"💰 예수금: {balance.get('cash', 0):,}원",
        f"📦 총평가: {balance.get('total_eval', 0):,}원",
        f"{profit_emoji} 총손익: {total_profit:+,}원",
    ]

    if holdings:
        lines.append("")
        lines.append(f"<b>📋 보유종목 ({len(holdings)}개)</b>")
        for h in holdings:
            r = h.get('profit_rate', 0)
            e = "🟢" if r >= 0 else "🔴"
            lines.append(
                f"{e} {h.get('name', '?')} | {r:+.1f}% | "
                f"{h.get('cur_price', 0):,}원 × {h.get('qty', 0):,}주"
            )
    else:
        lines.append("")
        lines.append("ℹ️ 보유 종목 없음")

    if send_message("\n".join(lines)):
        log.info("[TELEGRAM] 수익률 리포트 전송 완료")


def notify_daily_report(balance: dict, holdings: list, session_label: str = "장"):
    """
    일일 장종료 마감 리포트 전송.
    - session_label: 'KRX 정규장' 또는 '당일 전체' 등
    - 휴장일에는 호출하지 말 것 (호출 측에서 is_today_trading 체크)
    """
    token, chat_id = _get_cfg()
    if not token or not chat_id:
        return

    date_str = datetime.now().strftime("%Y-%m-%d")
    total_profit = balance.get('total_profit', 0)
    total_eval = balance.get('total_eval', 0)
    cash = balance.get('cash', 0)
    profit_emoji = "📈" if total_profit >= 0 else "📉"

    lines = [
        f"📅 <b>[{session_label} 종료] 일일 마감 리포트</b>",
        "━━━━━━━━━━━━━━",
        f"📆 {date_str}",
        "",
        f"💰 예수금:    {cash:,}원",
        f"📦 총평가금액: {total_eval:,}원",
        f"💼 총자산:    {cash + total_eval:,}원",
        f"{profit_emoji} 총평가손익: {total_profit:+,}원",
    ]

    if holdings:
        lines.append("")
        lines.append(f"<b>📋 보유종목 ({len(holdings)}개)</b>")
        for h in holdings:
            r = h.get('profit_rate', 0)
            profit = h.get('profit', 0)
            e = "🟢" if r >= 0 else "🔴"
            lines.append(
                f"{e} <b>{h.get('name', '?')}</b> ({h.get('code', '')})\n"
                f"   수익률: {r:+.1f}%  손익: {profit:+,}원\n"
                f"   현재가: {h.get('cur_price', 0):,}원 × {h.get('qty', 0):,}주"
            )
    else:
        lines.append("")
        lines.append("ℹ️ 보유 종목 없음")

    if send_message("\n".join(lines)):
        log.info(f"[TELEGRAM] [{session_label} 종료] 일일 마감 리포트 전송 완료")


def notify_trade_log_report(trade_log: list[dict]):
    """
    당일 매매내역 리포트 전송.
    - trade_log: AutoTrader.trade_log 리스트
    """
    token, chat_id = _get_cfg()
    if not token or not chat_id:
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_str = datetime.now().strftime("%Y-%m-%d")

    lines = [
        "📅 <b>[AutoStock] 당일 매매내역 리포트</b>",
        "━━━━━━━━━━━━━━",
        f"📆 날짜: {date_str}",
        f"⏰ 발송시각: {now_str}",
        ""
    ]

    buys = [t for t in trade_log if t.get("side") == "buy"]
    sells = [t for t in trade_log if t.get("side") == "sell"]

    total_buy_amt = 0
    total_sell_amt = 0

    # 1) 매수 내역
    lines.append(f"🟢 <b>매수 내역 ({len(buys)}건)</b>")
    if buys:
        for idx, b in enumerate(buys, 1):
            qty = b.get("qty", 0)
            price = b.get("price", 0)
            amt = qty * price
            total_buy_amt += amt
            
            t_str = b.get("time", "")
            try:
                t_dt = datetime.fromisoformat(t_str)
                t_formatted = t_dt.strftime("%H:%M")
            except Exception:
                t_formatted = t_str[-8:-3] if len(t_str) >= 8 else t_str

            market_tag = " [코스닥]" if b.get("market") == "KOSDAQ" else ""
            lines.append(
                f"{idx}. {t_formatted} <b>{b.get('name', '?')}</b> ({b.get('code', '')}){market_tag}\n"
                f"   수량: {qty:,}주 | 단가: {price:,}원\n"
                f"   금액: {amt:,}원"
            )
    else:
        lines.append("   - 매수 체결 내역 없음")

    lines.append("")

    # 2) 매도 내역
    lines.append(f"🔴 <b>매도 내역 ({len(sells)}건)</b>")
    if sells:
        for idx, s in enumerate(sells, 1):
            qty = s.get("qty", 0)
            price = s.get("price", 0)
            amt = qty * price
            total_sell_amt += amt

            t_str = s.get("time", "")
            try:
                t_dt = datetime.fromisoformat(t_str)
                t_formatted = t_dt.strftime("%H:%M")
            except Exception:
                t_formatted = t_str[-8:-3] if len(t_str) >= 8 else t_str

            profit_rate = s.get("profit_rate")
            profit_str = ""
            if profit_rate is not None:
                emoji = "📈" if profit_rate >= 0 else "📉"
                profit_str = f" | 수익률: {emoji} {profit_rate:+.1f}%"

            lines.append(
                f"{idx}. {t_formatted} <b>{s.get('name', '?')}</b> ({s.get('code', '')})\n"
                f"   수량: {qty:,}주 | 단가: {price:,}원{profit_str}\n"
                f"   금액: {amt:,}원"
            )
    else:
        lines.append("   - 매도 체결 내역 없음")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━")
    lines.append("💰 <b>총 거래 요약</b>")
    lines.append(f"• 총 매수금액: {total_buy_amt:,}원")
    lines.append(f"• 총 매도금액: {total_sell_amt:,}원")

    # 매매내역이 아예 없는 경우 심플하게 전송
    if not buys and not sells:
        lines = [
            "📅 <b>[AutoStock] 당일 매매내역 리포트</b>",
            "━━━━━━━━━━━━━━",
            f"📆 날짜: {date_str}",
            f"⏰ 발송시각: {now_str}",
            "",
            "ℹ️ 금일 매매 내역이 존재하지 않습니다."
        ]

    if send_message("\n".join(lines)):
        log.info("[TELEGRAM] 당일 매매내역 리포트 전송 완료")


# ── 텔레그램 폴링 헬퍼 ─────────────────────────────────────────────

def _get_last_update_id() -> int:
    """현재 텔레그램의 마지막 update_id 반환 (오래된 메시지 무시용)"""
    token, _ = _get_cfg()
    if not token:
        return 0
    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        resp = requests.get(url, params={"limit": 1, "offset": -1}, timeout=5)
        updates = resp.json().get("result", [])
        return updates[-1]["update_id"] if updates else 0
    except Exception:
        return 0


def check_commands(start_offset: int) -> tuple:
    """
    텔레그램에서 전송된 명령어(0: 중지, 1: 가동, 2: 상태조회)를 확인.
    수신된 명령어 전체 리스트를 반환하여 연속 명령어도 모두 처리.
    Returns: (commands: list[str], new_offset: int)
             commands 가 빈 리스트면 수신 명령어 없음.
    """
    token, chat_id = _get_cfg()
    if not token or not chat_id:
        return [], start_offset

    chat_id_str = str(chat_id)
    # ★ 버그 수정: start_offset=0 은 falsy 이므로 'if start_offset'이 None을 반환해
    #   오래된 메시지가 재처리됨. 항상 start_offset+1 을 offset으로 사용.
    offset = start_offset + 1

    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        params = {"timeout": 1, "allowed_updates": ["message"], "offset": offset}

        resp = requests.get(url, params=params, timeout=3)
        if resp.status_code != 200:
            return [], start_offset

        updates = resp.json().get("result", [])
        commands: list[str] = []
        new_offset = start_offset
        for upd in updates:
            new_offset = upd["update_id"]
            msg = upd.get("message", {})
            if str(msg.get("chat", {}).get("id", "")) != chat_id_str:
                continue
            text = msg.get("text", "").strip()
            if text in ["0", "1", "2"]:
                # 연속된 중복 명령어는 1번만 처리 (예: 1,1,1 -> 1)
                if not commands or commands[-1] != text:
                    commands.append(text)

        return commands, new_offset
    except Exception:
        return [], start_offset


def notify_status(is_running: bool, changed: bool = True):
    """
    가동/중지 상태 응답 알림.
    changed=True  → 상태가 실제로 변경됨
    changed=False → 이미 해당 상태였음 (중복 명령)
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if is_running:
        emoji   = "▶️"
        title   = "자동매매 <b>가동</b>"
        detail  = "✅ 매수·매도 자동 실행 중\n📅 운영시간: 09:00 ~ 15:30"
        if not changed:
            detail = "ℹ️ 이미 가동 중입니다.\n" + detail
        cmd_hint = "⏸️ 중지하려면 <code>0</code> 을 전송하세요."
    else:
        emoji   = "⏸️"
        title   = "자동매매 <b>중지</b>"
        detail  = "🚫 매수·매도가 일시 정지되었습니다."
        if not changed:
            detail = "ℹ️ 이미 중지 상태입니다.\n" + detail
        cmd_hint = "▶️ 재개하려면 <code>1</code> 을 전송하세요."

    msg = (
        f"{emoji} {title}\n"
        f"━━━━━━━━━━━━━━\n"
        f"{detail}\n"
        f"{cmd_hint}\n"
        f"⏰ {now_str}"
    )
    send_message(msg)
    state_str = "가동" if is_running else "중지"
    log.info(f"[TELEGRAM] 상태 응답 전송: {state_str} ({'변경' if changed else '유지'})")


def notify_status_detail(
    is_running: bool,
    is_trading_day: bool,
    session: str | None,
    is_paused: bool,
    balance: dict = None,
):
    """
    텔레그램 '2' 명령어: 현재 프로그램 가동 상태 상세 조회 응답.
    - 실제 매매 실행 여부 (영업일 + 세션 + 일시정지 종합 판단)
    - 잔고(수익률) 정보 표시 추가
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if is_running:
        status_emoji = "🟢"
        status_text  = "<b>매매 실행 중</b>"
    else:
        status_emoji = "🔴"
        status_text  = "<b>매매 중지 중</b>"

    trading_day_str = "✅ 영업일" if is_trading_day else "🚫 휴장일"
    session_str     = f"🕐 {session}" if session else "⏸️ 장외 시간"
    pause_str       = "⏸️ 사용자 일시정지" if is_paused else "▶️ 정상 운행"

    profit_str = ""
    if balance:
        total_eval = balance.get('total_eval', 0)
        cash = balance.get('cash', 0)
        total_profit = balance.get('total_profit', 0)
        profit_rate = balance.get('profit_rate', 0.0)
        total_asset = cash + total_eval
        profit_emoji = "📈" if total_profit >= 0 else "📉"
        profit_str = (
            f"━━━━━━━━━━━━━━\n"
            f"💰 예수금: {cash:,}원\n"
            f"💼 총자산: {total_asset:,}원\n"
            f"{profit_emoji} 총손익: {total_profit:+,}원 ({profit_rate:+.2f}%)\n"
        )

    msg = (
        f"{status_emoji} <b>AutoStock 상태 조회</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 매매 상태: {status_text}\n"
        f"📅 오늘: {trading_day_str}\n"
        f"🏛️ 세션: {session_str}\n"
        f"🎮 제어: {pause_str}\n"
        f"{profit_str}"
        f"━━━━━━━━━━━━━━\n"
        f"⏸️ 중지: <code>0</code>  ▶️ 재개: <code>1</code>  🔍 조회: <code>2</code>\n"
        f"⏰ {now_str}"
    )
    send_message(msg)
    log.info(f"[TELEGRAM] 상태 상세 조회 응답 전송 (가동={is_running})")


def _poll_reply(
    approve_words: list,
    reject_words: list,
    timeout: int,
    start_offset: int,
) -> tuple:
    """
    timeout 초 동안 텔레그램 메시지를 폴링.
    Returns: ('approve' | 'reject' | 'timeout', last_update_id)
    """
    token, chat_id = _get_cfg()
    if not token or not chat_id:
        return 'timeout', start_offset

    chat_id_str = str(chat_id)
    deadline = time.time() + timeout
    offset = start_offset + 1  # 이미 본 메시지 건너뜀

    while time.time() < deadline:
        remaining = int(deadline - time.time())
        if remaining <= 0:
            break
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            resp = requests.get(
                url,
                params={
                    "offset": offset,
                    "timeout": min(5, remaining),
                    "allowed_updates": ["message"],
                },
                timeout=min(5, remaining) + 3,
            )
            updates = resp.json().get("result", [])
            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message", {})
                # 같은 채팅방에서 온 메시지만 처리
                if str(msg.get("chat", {}).get("id", "")) != chat_id_str:
                    continue
                text = msg.get("text", "").strip().lower()
                if any(w in text for w in approve_words):
                    return 'approve', offset
                if any(w in text for w in reject_words):
                    return 'reject', offset
        except Exception as e:
            log.debug(f"[TELEGRAM] 폴링 오류: {e}")
            time.sleep(2)

    return 'timeout', offset


# ── 매도 전 텔레그램 확인 ──────────────────────────────────────────

def request_sell_confirmation(
    stock_code: str,
    name: str,
    qty: int,
    cur_price: int,
    profit_rate: float,
    timeout: int = 60,
) -> bool:
    """
    매도 실행 전 텔레그램으로 확인 요청.

    Returns:
        True  → 매도 실행 (승인 or 시간초과 자동 매도)
        False → 매도 취소 (사용자 거부)

    텔레그램 미설정 → True (즉시 매도)
    timeout 내 응답 없으면 → True (자동 매도)
    '취소'/'아니오'/'n' 계열 → False
    '매도'/'예'/'y' 계열   → True
    """
    token, chat_id = _get_cfg()
    if not token or not chat_id:
        return True  # 텔레그램 없으면 즉시 매도

    emoji = "📈" if profit_rate >= 0 else "📉"
    direction = "익절" if profit_rate >= 0 else "손절"

    # 전송 전 마지막 update_id 기억 (오래된 메시지 무시)
    last_id = _get_last_update_id()

    msg = (
        f"🔔 <b>매도 확인 요청</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"종목: {name} ({stock_code})\n"
        f"수량: {qty:,}주\n"
        f"현재가: {cur_price:,}원\n"
        f"수익률: {emoji} {profit_rate:+.1f}% ({direction})\n\n"
        f"✅ <b>'{direction}'</b> 또는 <b>'매도'</b> → 매도 실행\n"
        f"❌ <b>'취소'</b> 또는 <b>'아니오'</b> → 매도 취소\n"
        f"⏱️ {timeout}초 내 응답 없으면 <b>자동 매도</b>"
    )
    send_message(msg)
    log.info(f"[TELEGRAM] 매도 확인 요청 전송 → {name}({stock_code}) / {profit_rate:+.1f}%")

    approve_words = ['매도', '예', '익절', '손절', 'y', 'yes', 'sell', '1']
    reject_words = ['취소', '아니오', '아니', 'n', 'no', 'cancel', '0']

    result, _ = _poll_reply(approve_words, reject_words, timeout, last_id)

    if result == 'approve':
        log.info(f"[TELEGRAM] 매도 승인 → {name}({stock_code}) 매도 실행")
        send_message(f"✅ <b>매도 승인</b>\n{name} ({stock_code}) 매도를 실행합니다.")
        return True
    elif result == 'reject':
        log.info(f"[TELEGRAM] 매도 취소 → {name}({stock_code}) 매도 스킵")
        send_message(f"❌ <b>매도 취소</b>\n{name} ({stock_code}) 매도를 취소했습니다.")
        return False
    else:  # timeout → 자동 매도
        log.info(f"[TELEGRAM] 매도 확인 시간 초과 → {name}({stock_code}) 자동 매도 실행")
        send_message(f"⏰ <b>시간 초과 → 자동 매도</b>\n{name} ({stock_code}) 매도를 실행합니다.")
        return True


# ── 실전투자 텔레그램 승인 ────────────────────────────────────────────

def request_real_trading_approval(timeout_seconds: int = 120) -> bool:
    """
    실전투자 전환 시 텔레그램으로 승인 코드를 전송하고
    사용자가 콘솔에 코드를 입력해야 진행되는 2단계 확인.

    텔레그램 미설정 → 콘솔 Y/N 확인만 수행.
    timeout_seconds 내에 입력 없으면 자동 취소.

    Returns:
        True  → 사용자 승인
        False → 거부 또는 타임아웃
    """
    import random
    import string

    token, chat_id = _get_cfg()
    has_telegram = bool(token and chat_id)

    log.warning("=" * 55)
    log.warning("  [실전투자] 실제 자금이 사용됩니다!")
    log.warning("  REAL_CANO, REAL_APP_KEY 계좌로 주문이 발생합니다.")
    log.warning("=" * 55)

    if has_telegram:
        # 6자리 승인 코드 생성
        approval_code = "".join(random.choices(string.digits, k=6))
        msg = (
            f"🔴 <b>[실전투자 승인 요청]</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"AutoStock이 <b>실전투자</b> 모드로 시작하려 합니다.\n\n"
            f"승인 코드: <code>{approval_code}</code>\n\n"
            f"콘솔에 위 코드를 입력하면 실행됩니다.\n"
            f"코드 없이 Enter → 취소\n"
            f"유효시간: {timeout_seconds}초"
        )
        send_message(msg)
        log.warning(f"[TELEGRAM] 실전투자 승인 코드를 전송했습니다. ({timeout_seconds}초 내 입력)")
        prompt = f"텔레그램으로 받은 6자리 승인 코드를 입력하세요 ({timeout_seconds}초): "
    else:
        approval_code = None
        log.warning("[WARN] 텔레그램 미설정 — 콘솔 확인으로 진행합니다.")
        prompt = "실전투자를 시작하시겠습니까? (Y 입력 후 Enter, 취소는 그냥 Enter): "

    # 타임아웃이 있는 입력
    user_input = _timed_input(prompt, timeout_seconds)

    if user_input is None:
        log.warning("[REAL] 입력 시간 초과 — 실전투자를 취소합니다.")
        notify_error("실전투자 승인 시간 초과 → 자동 취소")
        return False

    if approval_code:
        # 승인 코드 검증
        if user_input.strip() == approval_code:
            log.info("[REAL] 승인 코드 일치 → 실전투자를 시작합니다.")
            send_message("✅ <b>실전투자 승인 완료</b>\nAutoStock 실전투자를 시작합니다.")
            return True
        else:
            log.warning("[REAL] 승인 코드 불일치 — 실전투자를 취소합니다.")
            send_message("❌ <b>실전투자 취소</b>\n승인 코드가 일치하지 않습니다.")
            return False
    else:
        # 텔레그램 없는 경우 Y/N 확인
        if user_input.strip().upper() == "Y":
            log.info("[REAL] 콘솔 승인 완료 → 실전투자를 시작합니다.")
            return True
        else:
            log.info("[REAL] 취소 — 프로그램을 종료합니다.")
            return False


def _timed_input(prompt: str, timeout: int) -> "Optional[str]":
    """타임아웃이 있는 입력 (Windows/Linux 공용)"""
    import threading
    result = [None]

    def _input_thread():
        try:
            result[0] = input(prompt)
        except EOFError:
            result[0] = ""

    t = threading.Thread(target=_input_thread, daemon=True)
    t.start()
    t.join(timeout)
    return result[0]
