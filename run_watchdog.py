"""
AutoStock 자가 복구 무한 왓치독 런처 (run_watchdog.py)
===================================================
- main.py 프로세스를 실행하고 무한 감시합니다.
- 비정상 다운(정지, crash) 발생 시 5초 후 자동으로 복원시킵니다.
- 강제 복원 즉시 사용자에게 텔레그램 알림을 발송합니다.
- 사용자가 Ctrl+C 또는 정상 명령 종료(0) 시에는 재기동하지 않고 안전하게 정지합니다.
"""
import sys
import os
import time
import subprocess
from datetime import datetime

# sys.path에 루트 추가
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(SCRIPT_DIR)

from utils.logger import log

def start_watchdog():
    log.info("🛡️  AutoStock 자가 복구 왓치독(Watchdog) 감시 가동 시작")
    log.info("   - main.py를 감시하여 불시 종료 시 5초 내 강제 복원합니다.")
    
    restart_count = 0
    
    while True:
        exit_code = -1
        proc = None
        try:
            log.info(f"🚀 AutoStock 매매 엔진 기동 (재기동 회차: {restart_count}회)")
            
            # main.py 실행 (sys.executable를 써서 현재 사용중인 파이썬 인터프리터 경로를 강제)
            proc = subprocess.Popen(
                [sys.executable, "main.py"],
                cwd=SCRIPT_DIR,
            )
            
            # 프로세스 대기
            exit_code = proc.wait()
            
            # 정상 종료 코드 (0: 정상 종료)
            if exit_code == 0:
                log.info("ℹ️  사용자 명령 또는 정상 절차에 의해 매매 엔진이 안전하게 종료되었습니다. 왓치독을 중단합니다.")
                break
                
            log.warning(f"⚠️  AutoStock 매매 엔진이 비정상 종료되었습니다! (종료 코드: {exit_code})")
            
        except KeyboardInterrupt:
            log.info("🛑 왓치독 감시기가 사용자에 의해 수동 종료되었습니다.")
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:
                    pass
            break
        except Exception as e:
            log.error(f"❌ 왓치독 예외 발생: {e}")
            
        # 비정상 종료 시 재기동 준비
        restart_count += 1
        log.info("⏳ 5초 후에 매매 엔진을 자동으로 복원 및 재시작합니다...")
        
        # 텔레그램으로 엔진 정지 및 복원 중 알림 전송 시도
        try:
            from utils.notifier import send_message
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            msg = (
                f"⚠️ <b>[AutoStock 경보] 엔진 다운 감지</b>\n"
                f"━━━━━━━━━━━━━━\n"
                f"매매 엔진 프로세스가 갑작스럽게 정지하였습니다.\n"
                f"사유: 비정상 종료 (코드: {exit_code})\n"
                f"복구: <b>5초 내 자동 부활 및 재기동</b>\n"
                f"시각: {now_str}"
            )
            send_message(msg)
        except Exception as telegram_err:
            log.warning(f"복원 텔레그램 전송 실패: {telegram_err}")
            
        time.sleep(5)

if __name__ == "__main__":
    start_watchdog()
