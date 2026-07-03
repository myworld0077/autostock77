"""
AutoStock 백그라운드 관리 런처 (run_background.py)
===================================================
- 파이썬 3 (Python 3) 내장 라이브러리만을 사용하여 백그라운드 24시간 가동을 관리합니다.
- 터미널이나 SSH/클라우드 쉘 접속이 끊겨도 프로세스가 종료되지 않도록 세션을 분리(detaching)합니다.

사용법 (오라클 클라우드 터미널에 입력):
  python3 run_background.py start    # 백그라운드 24시간 실행 시작
  python3 run_background.py status   # 실행 상태 확인
  python3 run_background.py stop     # 백그라운드 실행 중지
  python3 run_background.py log      # 실시간 로그 확인
"""

import os
import sys
import subprocess
import signal
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
PID_FILE = os.path.join(SCRIPT_DIR, "logs", "autostock.pid")
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "autostock.log")
ERR_FILE = os.path.join(LOG_DIR, "autostock_error.log")

# 색상 출력용
GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
RESET = "\033[0m"

def log_info(msg):
    print(f"[INFO] {msg}")

def log_ok(msg):
    print(f"{GREEN}[OK] {msg}{RESET}")

def log_warn(msg):
    print(f"{YELLOW}[WARN] {msg}{RESET}")

def log_err(msg):
    print(f"{RED}[ERR] {msg}{RESET}")


def get_running_pid():
    """PID 파일 및 프로세스 실제 구동 여부 확인"""
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        # 해당 PID로 시그널 0을 보내 프로세스 존재 확인
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        # 파일은 있으나 실제 구동 중이 아니거나 읽기 실패한 경우
        return None


def start():
    """백그라운드로 main.py 실행 (세션 분리)"""
    # 디렉토리 생성
    os.makedirs(LOG_DIR, exist_ok=True)
    
    pid = get_running_pid()
    if pid:
        log_warn(f"AutoStock이 이미 백그라운드에서 실행 중입니다. (PID: {pid})")
        return

    log_info("AutoStock을 Python 3 백그라운드 모드로 시작합니다...")

    # 로그 파일 스트림 열기
    out = open(LOG_FILE, "a", encoding="utf-8")
    err = open(ERR_FILE, "a", encoding="utf-8")

    # 시스템 환경 변수 설정 (KST 타임존 강제 설정 및 버퍼링 끄기)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TZ"] = "Asia/Seoul"

    # Unix 계열 환경(리눅스/오라클 클라우드)에서 터미널이 끊겨도 유지되도록 세션 분리(start_new_session=True)
    kwargs = {}
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    else:
        # 윈도우 환경 대응
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    # main.py 실행
    proc = subprocess.Popen(
        [sys.executable, os.path.join(SCRIPT_DIR, "main.py")],
        stdout=out,
        stderr=err,
        cwd=SCRIPT_DIR,
        env=env,
        **kwargs
    )

    # PID 기록
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))

    time.sleep(2)
    
    # 기동 성공 여부 확인
    if get_running_pid():
        log_ok(f"AutoStock 백그라운드 기동 완료! (PID: {proc.pid})")
        log_info(f"실시간 로그 확인: python3 run_background.py log")
    else:
        log_err("백그라운드 기동에 실패했습니다. 에러 로그(logs/autostock_error.log)를 확인하세요.")


def stop():
    """백그라운드 프로세스 종료"""
    pid = get_running_pid()
    if not pid:
        log_warn("현재 실행 중인 백그라운드 프로세스가 없습니다.")
        if os.path.exists(PID_FILE):
            try:
                os.remove(PID_FILE)
            except OSError:
                pass
        return

    log_info(f"PID {pid} 프로세스를 종료하는 중...")
    try:
        # 정상 종료 시도 (SIGTERM)
        os.kill(pid, signal.SIGTERM)
        for _ in range(5):
            time.sleep(1)
            try:
                os.kill(pid, 0)
            except OSError:
                log_ok("정상적으로 종료되었습니다.")
                break
        else:
            # 반응이 없을 시 강제 종료 (SIGKILL)
            log_warn("프로세스가 정상 종료되지 않아 강제 종료(SIGKILL)를 수행합니다.")
            os.kill(pid, signal.SIGKILL)
    except OSError as e:
        log_err(f"프로세스 종료 중 오류 발생: {e}")

    # PID 파일 삭제
    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


def status():
    """상태 확인"""
    pid = get_running_pid()
    print("=" * 45)
    print("  AutoStock 백그라운드 상태 조회")
    print("=" * 45)
    if pid:
        print(f"  🟢 상태: {GREEN}실행 중 (Running){RESET}")
        print(f"  🔢 PID:  {pid}")
    else:
        print(f"  ⚫ 상태: {RED}정지됨 (Stopped){RESET}")
    print(f"  📁 경로: {SCRIPT_DIR}")
    print(f"  📝 로그: {LOG_FILE}")
    print("=" * 45)


def view_log():
    """tail -f 기능 구현 (실시간 로그 스트리밍)"""
    if not os.path.exists(LOG_FILE):
        log_warn("로그 파일이 아직 생성되지 않았습니다. 먼저 프로그램을 가동해 주세요.")
        return

    log_info("실시간 로그 모니터링을 시작합니다. (Ctrl+C를 누르면 빠져나갑니다.)\n")
    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        # 파일 끝으로 이동
        f.seek(0, os.SEEK_END)
        try:
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                print(line, end="")
        except KeyboardInterrupt:
            print("\n")
            log_info("로그 모니터링을 종료합니다.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1].lower()
    if cmd == "start":
        start()
    elif cmd == "stop":
        stop()
    elif cmd == "status":
        status()
    elif cmd == "log":
        view_log()
    else:
        print(f"알 수 없는 명령어: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
