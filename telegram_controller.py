"""
AutoStock 텔레그램 컨트롤러 (telegram_controller.py)
=====================================================
오라클 클라우드 24시간 독립 실행 — 텔레그램으로 프로그램을 완전 제어합니다.

★ 이 파일 하나로 모든 제어가 가능합니다:
   python3 telegram_controller.py

명령어 (텔레그램에서 전송):
  시작 / start       → AutoStock 매매 프로그램 시작
  중지 / stop        → AutoStock 매매 프로그램 중지
  재시작 / restart   → 중지 후 재시작
  상태 / status / 2  → 현재 실행 상태 + 잔고 조회
  로그 / log         → 최근 로그 20줄 조회
  도움말 / help / ?  → 명령어 목록 출력
  ─── 매매 제어 (프로그램 실행 중) ───
  0                  → 매매 일시 중지 (보유 포지션 유지)
  1                  → 매매 재개
  a                  → 🔴 하락장 방어 전략으로 전환
  b                  → 🟡 횡보장 복합 전략으로 전환
  c                  → 🟢 상승장 추세 전략으로 전환
  auto               → 🔄 코스피 지수 기반 자동 전략 전환

사용법:
  오라클 클라우드 터미널에서:
    python3 telegram_controller.py        # 포그라운드 실행 (테스트)
    nohup python3 telegram_controller.py > logs/controller.log 2>&1 &   # 백그라운드
"""

import os
import sys
import time
import subprocess
import signal
from datetime import datetime
from pathlib import Path

# ── 경로 설정 ────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent.resolve()
LOG_DIR     = SCRIPT_DIR / "logs"
LOG_FILE    = LOG_DIR / "autostock.log"
ERR_FILE    = LOG_DIR / "autostock_error.log"
PID_FILE    = LOG_DIR / "autostock.pid"
CTRL_LOG    = LOG_DIR / "controller.log"
ENV_FILE    = SCRIPT_DIR / ".env"

# ── .env 로드 ────────────────────────────────────────────────────────────
def _load_env():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

_load_env()

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── 로그 출력 ─────────────────────────────────────────────────────────────
def _log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CTRL_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ── 텔레그램 API ─────────────────────────────────────────────────────────
import urllib.request
import urllib.parse
import json

def _tg_get(method: str, params: dict = None) -> dict:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return {}

def _tg_post(method: str, data: dict) -> dict:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return {}

def send(text: str):
    """텔레그램 메시지 전송"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    _tg_post("sendMessage", {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    })

def get_updates(offset: int) -> list:
    """새 메시지 폴링"""
    data = _tg_get("getUpdates", {
        "offset": offset,
        "timeout": 3,
        "allowed_updates": ["message"],
    })
    return data.get("result", [])

# ── 프로세스 제어 ─────────────────────────────────────────────────────────
def _get_pid() -> int | None:
    """AutoStock main.py PID 확인"""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)   # 존재 확인
        return pid
    except (OSError, ValueError):
        return None

def _is_running() -> bool:
    return _get_pid() is not None

def _do_start() -> str:
    """AutoStock 시작"""
    if _is_running():
        return "⚠️ AutoStock이 이미 실행 중입니다.\n<code>상태</code> 명령어로 확인하세요."

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TZ"] = "Asia/Seoul"

    # .env 재로드
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip("'\"")

    with open(LOG_FILE, "a", encoding="utf-8") as out, \
         open(ERR_FILE, "a", encoding="utf-8") as err:
        kwargs = {"cwd": str(SCRIPT_DIR), "env": env, "stdout": out, "stderr": err}
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        proc = subprocess.Popen([sys.executable, str(SCRIPT_DIR / "main.py")], **kwargs)

    PID_FILE.write_text(str(proc.pid))
    time.sleep(2)

    if _is_running():
        _log(f"[START] AutoStock 시작 완료 PID={proc.pid}")
        return (
            f"✅ <b>AutoStock 시작 완료!</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"🆔 PID: {proc.pid}\n"
            f"⏰ 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"📱 매매 제어 명령어:\n"
            f"  <code>0</code> 중지  <code>1</code> 재개  <code>2</code> 상태\n"
            f"  <code>a</code> 하락장  <code>b</code> 횡보장  <code>c</code> 상승장"
        )
    else:
        _log("[START] 시작 실패")
        tail = _read_log_tail(5, ERR_FILE)
        return f"❌ <b>시작 실패!</b>\n오류 로그:\n<code>{tail}</code>"

def _do_stop() -> str:
    """AutoStock 중지"""
    pid = _get_pid()
    if not pid:
        return "⚠️ AutoStock이 실행 중이지 않습니다."

    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(8):
            time.sleep(1)
            try:
                os.kill(pid, 0)
            except OSError:
                break
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

        if PID_FILE.exists():
            PID_FILE.unlink()

        _log(f"[STOP] AutoStock 중지 완료 PID={pid}")
        return (
            f"⏹️ <b>AutoStock 중지 완료</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"▶️ 다시 시작하려면: <code>시작</code>"
        )
    except OSError as e:
        return f"❌ 중지 실패: {e}"

def _do_restart() -> str:
    """재시작"""
    stop_msg = _do_stop()
    time.sleep(2)
    start_msg = _do_start()
    return f"🔄 <b>재시작</b>\n{start_msg}"

def _read_log_tail(n: int = 20, path: Path = None) -> str:
    """로그 파일 마지막 n줄"""
    target = path or LOG_FILE
    if not target.exists():
        return "로그 파일 없음"
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:]) if lines else "로그 없음"
    except Exception as e:
        return f"로그 읽기 오류: {e}"

def _do_log() -> str:
    """최근 로그 조회"""
    tail = _read_log_tail(20)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"📋 <b>최근 로그 (20줄)</b>\n"
        f"⏰ {now_str}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<code>{tail}</code>"
    )

def _do_status() -> str:
    """상태 조회"""
    running = _is_running()
    pid = _get_pid()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    status_icon = "🟢" if running else "🔴"
    status_text = f"<b>실행 중</b> (PID: {pid})" if running else "<b>중지됨</b>"

    # 로그에서 마지막 수익률 라인 찾기
    balance_line = ""
    if running and LOG_FILE.exists():
        try:
            lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in reversed(lines[-100:]):
                if "예수금" in line or "잔고" in line:
                    balance_line = f"\n💰 {line.strip()}"
                    break
        except Exception:
            pass

    ctrl_cmd = (
        "\n━━━━━━━━━━━━━━\n"
        "📱 <b>제어 명령어</b>\n"
        "  <code>시작</code>   <code>중지</code>   <code>재시작</code>\n"
        "  <code>0</code> 중지  <code>1</code> 재개  <code>로그</code>\n"
        "  🔴<code>a</code> 하락장  🟡<code>b</code> 횡보장  🟢<code>c</code> 상승장"
    )

    return (
        f"{status_icon} <b>AutoStock 상태</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 상태: {status_text}\n"
        f"⏰ 조회: {now_str}"
        f"{balance_line}"
        f"{ctrl_cmd}"
    )

def _do_help() -> str:
    """도움말"""
    return (
        "🤖 <b>AutoStock 텔레그램 제어 명령어</b>\n"
        "━━━━━━━━━━━━━━\n"
        "🟢 <b>프로그램 제어</b>\n"
        "  <code>시작</code>      → AutoStock 시작\n"
        "  <code>중지</code>      → AutoStock 중지\n"
        "  <code>재시작</code>    → 재시작\n"
        "  <code>상태</code>      → 실행 상태 조회\n"
        "  <code>로그</code>      → 최근 로그 20줄\n"
        "  <code>도움말</code>    → 이 화면\n"
        "━━━━━━━━━━━━━━\n"
        "📈 <b>매매 제어 (실행 중일 때)</b>\n"
        "  <code>0</code> → ⏸️ 매매 일시 중지\n"
        "  <code>1</code> → ▶️ 매매 재개\n"
        "  <code>2</code> → 🔍 잔고/수익률 조회\n"
        "━━━━━━━━━━━━━━\n"
        "🔄 <b>전략 전환</b>\n"
        "  <code>a</code>    → 🔴 하락장 방어\n"
        "  <code>b</code>    → 🟡 횡보장 복합\n"
        "  <code>c</code>    → 🟢 상승장 추세\n"
        "  <code>auto</code> → 🔄 자동 판별\n"
        "━━━━━━━━━━━━━━\n"
        "💡 <b>단축 명령어</b>\n"
        "  start / stop / restart / status / log / help"
    )

# ── 명령어 처리 ───────────────────────────────────────────────────────────
# 컨트롤러가 직접 처리하는 프로그램 수준 명령어
CONTROLLER_CMDS = {
    "시작", "start",
    "중지", "stop",
    "재시작", "restart",
    "상태", "status",
    "로그", "log",
    "도움말", "help", "?",
}

def _handle(text: str) -> str | None:
    """
    명령어 처리.
    None 반환 → main.py 내부 폴러가 처리할 매매 제어 명령 (0/1/2/a/b/c/auto)
    """
    cmd = text.strip().lower()

    # 프로그램 제어
    if cmd in ("시작", "start"):
        return _do_start()
    if cmd in ("중지", "stop"):
        return _do_stop()
    if cmd in ("재시작", "restart"):
        return _do_restart()
    if cmd in ("상태", "status", "2"):
        return _do_status()
    if cmd in ("로그", "log"):
        return _do_log()
    if cmd in ("도움말", "help", "?"):
        return _do_help()

    # 매매 제어 명령어 (0/1/a/b/c/auto): main.py 내부 폴러가 처리 → 응답 없음
    # 단, 프로그램이 꺼져 있으면 안내
    if cmd in ("0", "1", "a", "b", "c", "auto"):
        if not _is_running():
            return (
                f"⚠️ AutoStock이 실행 중이지 않습니다.\n"
                f"먼저 <code>시작</code> 명령어로 프로그램을 시작하세요."
            )
        return None   # main.py가 처리

    if cmd == "2":
        return _do_status()   # 상태 조회는 컨트롤러도 처리

    # 알 수 없는 명령
    return (
        "❓ 알 수 없는 명령어입니다.\n"
        "<code>도움말</code> 또는 <code>help</code>를 입력하면 명령어 목록을 볼 수 있습니다."
    )

# ── 메인 루프 ─────────────────────────────────────────────────────────────
def main():
    _log("=" * 55)
    _log("  AutoStock 텔레그램 컨트롤러 시작")
    _log(f"  Python {sys.version.split()[0]}")
    _log("=" * 55)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        _log("❌ TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.")
        _log(f"   .env 파일 경로: {ENV_FILE}")
        sys.exit(1)

    # 시작 알림 전송
    send(
        "🤖 <b>AutoStock 텔레그램 컨트롤러 가동!</b>\n"
        "━━━━━━━━━━━━━━\n"
        "이제 텔레그램으로 프로그램을 제어할 수 있습니다.\n\n"
        "📋 <code>도움말</code> 또는 <code>help</code>로 명령어 목록 확인\n"
        "🚀 <code>시작</code>으로 AutoStock 매매 시작\n\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    # 최신 offset 획득 (과거 메시지 무시)
    updates = get_updates(-1)
    offset = updates[-1]["update_id"] + 1 if updates else 0
    _log(f"텔레그램 폴링 시작 (offset={offset})")

    last_heartbeat = time.time()

    while True:
        try:
            updates = get_updates(offset)
            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message", {})

                # 같은 채팅방만 처리
                if str(msg.get("chat", {}).get("id", "")) != str(TELEGRAM_CHAT_ID):
                    continue

                text = msg.get("text", "").strip()
                if not text:
                    continue

                _log(f"수신: '{text}'")
                reply = _handle(text)
                if reply:
                    send(reply)
                    _log(f"응답 전송 완료")

            # 10분마다 생존 확인 (프로그램이 중지된 경우 알림)
            now = time.time()
            if now - last_heartbeat >= 600:
                last_heartbeat = now
                if not _is_running():
                    send(
                        "⚠️ <b>AutoStock 매매 프로그램이 실행 중이지 않습니다!</b>\n"
                        "<code>시작</code> 명령어로 재가동하세요."
                    )
                    _log("[HEARTBEAT] 매매 프로그램 미가동 감지 — 알림 전송")

        except KeyboardInterrupt:
            _log("컨트롤러 종료 (Ctrl+C)")
            send("⏹️ <b>AutoStock 텔레그램 컨트롤러가 종료되었습니다.</b>")
            break
        except Exception as e:
            _log(f"[ERROR] {e}")
            time.sleep(5)

        time.sleep(1)


if __name__ == "__main__":
    main()
