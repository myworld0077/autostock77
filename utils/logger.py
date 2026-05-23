"""
로깅 유틸리티
- 콘솔 + 파일 동시 출력
- Windows cp949 환경에서 이모지 안전 처리
"""
import logging
import os
import sys
import io
from datetime import datetime

# ── Windows 콘솔 인코딩을 UTF-8로 강제 설정 ─────────────────────────
# 이모지·한글이 섞인 메시지를 print/logging 어느 경로로 출력해도
# UnicodeEncodeError 없이 처리되도록 stdout/stderr를 UTF-8 래퍼로 교체.
try:
    if sys.stdout and hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True
        )
    if sys.stderr and hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True
        )
except Exception:
    pass  # 이미 래핑된 경우 등 예외 무시

# logs 디렉토리 생성
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# 로그 파일명: logs/autostock_2026-05-02.log
log_filename = os.path.join(LOG_DIR, f"autostock_{datetime.now().strftime('%Y-%m-%d')}.log")

# 로거 설정
log = logging.getLogger("autostock")
log.setLevel(logging.DEBUG)

# 포맷
fmt = logging.Formatter(
    "[%(asctime)s] %(levelname)-7s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


class SafeStreamHandler(logging.StreamHandler):
    """Windows cp949 환경에서 인코딩 불가 문자를 '?'로 대체하여 출력"""
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            try:
                stream.write(msg + self.terminator)
                self.flush()
            except UnicodeEncodeError:
                enc = getattr(stream, 'encoding', None) or 'utf-8'
                safe_msg = msg.encode(enc, errors='replace').decode(enc, errors='replace')
                stream.write(safe_msg + self.terminator)
                self.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)


# 콘솔 핸들러 (cp949 안전)
console = SafeStreamHandler(sys.stdout)
console.setLevel(logging.INFO)
console.setFormatter(fmt)
log.addHandler(console)

# 파일 핸들러 (utf-8 저장 — 이모지 완전 지원)
file_handler = logging.FileHandler(log_filename, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(fmt)
log.addHandler(file_handler)
