"""
AutoStock 통합 실행 스크립트 (autostart.py)
==========================================
텔레그램 컨트롤러 + AutoStock 매매 프로그램을 한 번에 시작합니다.

사용법:
  python3 autostart.py          # 둘 다 시작
  python3 autostart.py ctrl     # 텔레그램 컨트롤러만 시작
  python3 autostart.py trade    # 매매 프로그램만 시작
  python3 autostart.py stop     # 둘 다 중지
  python3 autostart.py status   # 상태 확인
"""

import os
import sys
import time
import signal
import subprocess
from pathlib import Path
from datetime import datetime

SCRIPT_DIR   = Path(__file__).parent.resolve()
LOG_DIR      = SCRIPT_DIR / "logs"
TRADE_PID    = LOG_DIR / "autostock.pid"
CTRL_PID     = LOG_DIR / "controller.pid"
TRADE_LOG    = LOG_DIR / "autostock.log"
CTRL_LOG     = LOG_DIR / "controller.log"
TRADE_ERR    = LOG_DIR / "autostock_error.log"

GREEN  = "\033[0;32m"
RED    = "\033[0;31m"
YELLOW = "\033[1;33m"
RESET  = "\033[0m"

def ok(m):   print(f"{GREEN}✅ {m}{RESET}")
def warn(m): print(f"{YELLOW}⚠️  {m}{RESET}")
def err(m):  print(f"{RED}❌ {m}{RESET}")
def info(m): print(f"   {m}")


def _pid_alive(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def _load_env() -> dict:
    env_file = SCRIPT_DIR / ".env"
    env = os.environ.copy()
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip("'\"")
    env["PYTHONUNBUFFERED"] = "1"
    env["TZ"] = "Asia/Seoul"
    return env


def _start_proc(script: Path, pid_file: Path, log_file: Path, err_file: Path,
                label: str) -> bool:
    """백그라운드 프로세스 시작"""
    pid = _pid_alive(pid_file)
    if pid:
        warn(f"{label} 이미 실행 중 (PID {pid})")
        return True

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = _load_env()

    with open(log_file, "a", encoding="utf-8") as out, \
         open(err_file, "a", encoding="utf-8") as er:
        kwargs = {"cwd": str(SCRIPT_DIR), "env": env, "stdout": out, "stderr": er}
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        proc = subprocess.Popen([sys.executable, str(script)], **kwargs)

    pid_file.write_text(str(proc.pid))
    time.sleep(2)

    if _pid_alive(pid_file):
        ok(f"{label} 시작 완료 (PID {proc.pid})")
        return True
    else:
        err(f"{label} 시작 실패! 오류 로그 확인:")
        if err_file.exists():
            lines = err_file.read_text(errors="replace").splitlines()
            for ln in lines[-5:]:
                info(ln)
        return False


def _stop_proc(pid_file: Path, label: str):
    """프로세스 종료"""
    pid = _pid_alive(pid_file)
    if not pid:
        warn(f"{label} 실행 중이지 않음")
        return

    info(f"{label} 종료 중 (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(8):
            time.sleep(1)
            try:
                os.kill(pid, 0)
            except OSError:
                ok(f"{label} 정상 종료")
                break
        else:
            os.kill(pid, signal.SIGKILL)
            ok(f"{label} 강제 종료")
    except OSError:
        pass
    finally:
        if pid_file.exists():
            pid_file.unlink()


def cmd_start_all():
    print("\n🚀 AutoStock 전체 시스템 시작")
    print("=" * 45)
    # 1. 텔레그램 컨트롤러
    _start_proc(
        script   = SCRIPT_DIR / "telegram_controller.py",
        pid_file = CTRL_PID,
        log_file = CTRL_LOG,
        err_file = LOG_DIR / "controller_error.log",
        label    = "텔레그램 컨트롤러",
    )
    time.sleep(1)
    # 2. 매매 프로그램
    _start_proc(
        script   = SCRIPT_DIR / "main.py",
        pid_file = TRADE_PID,
        log_file = TRADE_LOG,
        err_file = TRADE_ERR,
        label    = "AutoStock 매매 프로그램",
    )
    print("\n📱 텔레그램에서 <도움말> 또는 <help> 를 전송하면 제어 명령어를 볼 수 있습니다.")


def cmd_start_ctrl():
    print("\n🤖 텔레그램 컨트롤러만 시작")
    print("=" * 45)
    _start_proc(
        script   = SCRIPT_DIR / "telegram_controller.py",
        pid_file = CTRL_PID,
        log_file = CTRL_LOG,
        err_file = LOG_DIR / "controller_error.log",
        label    = "텔레그램 컨트롤러",
    )


def cmd_start_trade():
    print("\n📈 AutoStock 매매 프로그램만 시작")
    print("=" * 45)
    _start_proc(
        script   = SCRIPT_DIR / "main.py",
        pid_file = TRADE_PID,
        log_file = TRADE_LOG,
        err_file = TRADE_ERR,
        label    = "AutoStock 매매 프로그램",
    )


def cmd_stop_all():
    print("\n⏹️  AutoStock 전체 중지")
    print("=" * 45)
    _stop_proc(TRADE_PID, "AutoStock 매매 프로그램")
    _stop_proc(CTRL_PID,  "텔레그램 컨트롤러")
    ok("전체 중지 완료")


def cmd_status():
    print("\n📊 AutoStock 상태")
    print("=" * 45)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 텔레그램 컨트롤러
    cpid = _pid_alive(CTRL_PID)
    if cpid:
        print(f"  🤖 텔레그램 컨트롤러: {GREEN}실행 중{RESET} (PID {cpid})")
    else:
        print(f"  🤖 텔레그램 컨트롤러: {RED}중지{RESET}")

    # 매매 프로그램
    tpid = _pid_alive(TRADE_PID)
    if tpid:
        print(f"  📈 AutoStock 매매:     {GREEN}실행 중{RESET} (PID {tpid})")
    else:
        print(f"  📈 AutoStock 매매:     {RED}중지{RESET}")

    print(f"\n  🕐 조회 시각: {now}")
    print("\n  📋 최근 로그:")
    if TRADE_LOG.exists():
        lines = TRADE_LOG.read_text(errors="replace").splitlines()
        for ln in lines[-5:]:
            print(f"     {ln}")
    else:
        warn("  로그 파일 없음")

    print("\n  💡 빠른 명령어:")
    print("     python3 autostart.py          # 전체 시작")
    print("     python3 autostart.py stop     # 전체 중지")
    print("     python3 autostart.py ctrl     # 컨트롤러만 시작")


def print_help():
    print(__doc__)


COMMANDS = {
    "start":  cmd_start_all,
    "ctrl":   cmd_start_ctrl,
    "trade":  cmd_start_trade,
    "stop":   cmd_stop_all,
    "status": cmd_status,
}

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "start"
    fn = COMMANDS.get(arg)
    if fn:
        fn()
    else:
        print_help()
