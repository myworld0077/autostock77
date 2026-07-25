"""
AutoStock 오라클 클라우드 관리 스크립트 (Python 3 전용)
========================================================
setup_oracle.sh 를 대체하는 Python 3 관리 도구입니다.

사용법:
  python3 setup_oracle.py install   # 최초 설치 (1회만)
  python3 setup_oracle.py start     # 백그라운드 실행 시작
  python3 setup_oracle.py stop      # 실행 중지
  python3 setup_oracle.py restart   # 재시작
  python3 setup_oracle.py status    # 상태 및 최근 로그 확인
  python3 setup_oracle.py log       # 실시간 로그 스트리밍
  python3 setup_oracle.py update    # git pull 후 재시작
"""

import os
import sys
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent.resolve()
LOG_DIR     = SCRIPT_DIR / "logs"
LOG_FILE    = LOG_DIR / "autostock.log"
ERR_FILE    = LOG_DIR / "autostock_error.log"
PID_FILE    = LOG_DIR / "autostock.pid"
ENV_FILE    = SCRIPT_DIR / ".env"
MAIN_PY     = SCRIPT_DIR / "main.py"
RUN_BG_PY   = SCRIPT_DIR / "run_background.py"

# ── 색상 출력 ──────────────────────────────────────────────────────
GREEN  = "\033[0;32m"
RED    = "\033[0;31m"
YELLOW = "\033[1;33m"
BLUE   = "\033[0;34m"
RESET  = "\033[0m"

def ok(msg):   print(f"{GREEN}[OK]{RESET}   {msg}")
def warn(msg): print(f"{YELLOW}[WARN]{RESET} {msg}")
def err(msg):  print(f"{RED}[ERR]{RESET}  {msg}")
def info(msg): print(f"{BLUE}[INFO]{RESET} {msg}")


# ── 공통 유틸 ──────────────────────────────────────────────────────

def get_running_pid() -> int | None:
    """PID 파일로 실행 중인 프로세스 확인"""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)   # 프로세스 존재 확인 (시그널 0)
        return pid
    except (OSError, ValueError):
        return None


def _run(cmd: list, capture: bool = False):
    """subprocess.run 래퍼"""
    kwargs = {"cwd": SCRIPT_DIR, "text": True}
    if capture:
        kwargs["capture_output"] = True
    return subprocess.run(cmd, **kwargs)


# ── 명령어 구현 ────────────────────────────────────────────────────

def cmd_install():
    """최초 1회 설치: 의존성 설치, .env 확인, 로그 폴더 생성"""
    info("=== AutoStock 설치 시작 (Python 3 전용) ===")

    # 로그 폴더
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ok(f"로그 폴더 생성: {LOG_DIR}")

    # .env 확인
    if not ENV_FILE.exists():
        err(".env 파일이 없습니다! 먼저 .env 를 생성하세요.")
        info(f"예: nano {ENV_FILE}")
        sys.exit(1)
    ok(".env 파일 확인 완료")

    # 파이썬 패키지 설치
    req = SCRIPT_DIR / "requirements.txt"
    if req.exists():
        info("파이썬 패키지 설치 중...")
        _run([sys.executable, "-m", "pip", "install", "--user", "-r", str(req), "-q"])
        ok("파이썬 패키지 설치 완료")
    else:
        warn("requirements.txt 없음 — 패키지 설치 생략")

    print()
    ok("=== 설치 완료! ===")
    print("  시작:   python3 setup_oracle.py start")
    print("  상태:   python3 setup_oracle.py status")
    print("  로그:   python3 setup_oracle.py log")


def cmd_start():
    """백그라운드로 main.py 실행 (세션 분리)"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    pid = get_running_pid()
    if pid:
        warn(f"AutoStock이 이미 실행 중입니다. (PID: {pid})")
        info("재시작하려면: python3 setup_oracle.py restart")
        return

    info("AutoStock 백그라운드 모드로 시작 중...")

    out = open(LOG_FILE, "a", encoding="utf-8")
    err_f = open(ERR_FILE, "a", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TZ"] = "Asia/Seoul"

    # .env 로드
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip("'\"")

    kwargs = {"cwd": SCRIPT_DIR, "env": env, "stdout": out, "stderr": err_f}
    if sys.platform != "win32":
        kwargs["start_new_session"] = True   # 터미널 종료 후에도 유지
    else:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen([sys.executable, str(MAIN_PY)], **kwargs)
    PID_FILE.write_text(str(proc.pid))

    time.sleep(2)
    if get_running_pid():
        ok(f"AutoStock 시작 완료! (PID: {proc.pid})")
        info("실시간 로그: python3 setup_oracle.py log")
    else:
        err("시작 실패! 에러 로그를 확인하세요:")
        if ERR_FILE.exists():
            print(ERR_FILE.read_text(encoding="utf-8", errors="replace")[-1000:])


def cmd_stop():
    """실행 중인 프로세스 종료"""
    pid = get_running_pid()
    if not pid:
        warn("실행 중인 AutoStock 프로세스가 없습니다.")
        if PID_FILE.exists():
            PID_FILE.unlink()
        return

    info(f"PID {pid} 프로세스를 종료하는 중...")
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(6):
            time.sleep(1)
            try:
                os.kill(pid, 0)
            except OSError:
                ok("정상 종료되었습니다.")
                break
        else:
            warn("응답 없음 → SIGKILL 강제 종료")
            os.kill(pid, signal.SIGKILL)
    except OSError as e:
        err(f"종료 중 오류: {e}")

    if PID_FILE.exists():
        PID_FILE.unlink()


def cmd_restart():
    """중지 후 재시작"""
    info("재시작 중...")
    cmd_stop()
    time.sleep(2)
    cmd_start()


def cmd_status():
    """현재 상태 및 최근 로그 출력"""
    pid = get_running_pid()
    print()
    print("=" * 45)
    print("  AutoStock 운영 상태")
    print("=" * 45)
    if pid:
        print(f"  상태: {GREEN}🟢 실행 중{RESET} (PID: {pid})")
    else:
        print(f"  상태: {RED}⚫ 정지됨{RESET}")
    print(f"  경로: {SCRIPT_DIR}")
    print(f"  로그: {LOG_FILE}")
    print("=" * 45)
    print()
    print("=== 최근 로그 (20줄) ===")
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(lines[-20:]))
    else:
        warn(f"로그 파일 없음: {LOG_FILE}")
        info("서비스를 시작하세요: python3 setup_oracle.py start")


def cmd_log():
    """실시간 로그 스트리밍 (tail -f 구현)"""
    if not LOG_FILE.exists():
        warn("로그 파일이 없습니다. 먼저 프로그램을 시작하세요:")
        info("python3 setup_oracle.py start")
        return

    info("실시간 로그 모니터링 (Ctrl+C 로 종료):\n")
    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        f.seek(0, os.SEEK_END)   # 파일 끝으로 이동
        try:
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.3)
                    continue
                print(line, end="")
        except KeyboardInterrupt:
            print()
            info("로그 모니터링 종료.")


def cmd_update():
    """git pull 로 최신 코드 반영 후 재시작"""
    info("GitHub에서 최신 코드 다운로드 중...")
    result = _run(["git", "pull"], capture=True)
    if result.returncode != 0:
        err(f"git pull 실패!\n{result.stderr}")
        sys.exit(1)
    ok("코드 업데이트 완료")
    print(result.stdout.strip())

    req = SCRIPT_DIR / "requirements.txt"
    if req.exists():
        info("패키지 업데이트 중...")
        _run([sys.executable, "-m", "pip", "install", "--user", "-r", str(req), "-q"])
        ok("패키지 업데이트 완료")

    cmd_restart()
    ok("=== 업데이트 및 재시작 완료 ===")


# ── 메인 ──────────────────────────────────────────────────────────

def print_help():
    print(__doc__)

COMMANDS = {
    "install": cmd_install,
    "start":   cmd_start,
    "stop":    cmd_stop,
    "restart": cmd_restart,
    "status":  cmd_status,
    "log":     cmd_log,
    "update":  cmd_update,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print_help()
        sys.exit(0)
    COMMANDS[sys.argv[1]]()
