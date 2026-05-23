"""
Windows 시스템 절전 모드 진입 방지 모듈
"""
import sys
from utils.logger import log

def prevent_sleep():
    """
    Windows 환경에서 시스템이 자동으로 절전 모드(Sleep)에 진입하는 것을 방지합니다.
    """
    if sys.platform != "win32":
        return

    try:
        import ctypes
        # ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001)
        # 설정을 해제하기 전까지 시스템 절전 모드 진입을 강제 차단합니다.
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        
        result = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        if result == 0:
            log.warning("[KEEP-ALIVE] Windows 절전 모드 방지 설정 실패")
        else:
            log.info("[KEEP-ALIVE] ✅ Windows 시스템 절전 모드 자동 진입 방지 활성화 완료")
    except Exception as e:
        log.warning(f"[KEEP-ALIVE] 절전 모드 방지 API 호출 실패: {e}")

def allow_sleep():
    """
    Windows 절전 모드 차단 설정을 해제하고 기본값으로 되돌립니다.
    """
    if sys.platform != "win32":
        return

    try:
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        log.info("[KEEP-ALIVE] Windows 절전 모드 방지 설정 해제")
    except Exception as e:
        log.warning(f"[KEEP-ALIVE] 절전 모드 해제 실패: {e}")
