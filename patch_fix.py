"""
AutoStock 실전투자 승인 버그 패치 스크립트 (patch_fix.py)
==========================================================
이 스크립트를 오라클 클라우드 터미널에서 한 번만 실행하면
다음 두 가지 버그가 즉시 수정됩니다:

  1. 텔레그램 승인번호를 보내도 인식 못하는 문제 (핵심 버그)
     - 기존: update_id 기반 필터링 → 직전 메시지 누락
     - 수정: 전송 시각(Unix timestamp) 기반 필터링으로 교체

  2. 승인 제한시간 120초 → 180초(3분)으로 연장

사용법:
  python3 patch_fix.py
"""

import os
import sys
import re
import shutil
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
NOTIFIER_FILE = os.path.join(SCRIPT_DIR, "utils", "notifier.py")
MAIN_FILE = os.path.join(SCRIPT_DIR, "main.py")


def backup_file(path: str):
    """원본 파일을 .bak으로 백업"""
    bak = path + ".bak"
    shutil.copy2(path, bak)
    print(f"  백업: {bak}")


def patch_notifier():
    """utils/notifier.py 의 _poll_reply 함수 핵심 버그 수정"""
    print("\n[1/2] utils/notifier.py 패치 중...")

    with open(NOTIFIER_FILE, "r", encoding="utf-8") as f:
        src = f.read()

    backup_file(NOTIFIER_FILE)

    # ── 패치 1: _poll_reply 함수 교체 ──────────────────────────
    # 기존 함수 시그니처(start_offset만 있는 버전)를 start_time 포함 버전으로 교체
    OLD_POLL_SIG = """def _poll_reply(
    approve_words: list,
    reject_words: list,
    timeout: int,
    start_offset: int,
) -> tuple:"""

    NEW_POLL_SIG = """def _poll_reply(
    approve_words: list,
    reject_words: list,
    timeout: int,
    start_offset: int,
    start_time: int = 0,
) -> tuple:"""

    # offset 계산 라인 교체: start_offset + 1 → 2칸 뒤로 물러나서 start_time으로 필터링
    OLD_OFFSET = "    offset = start_offset + 1  # 이미 본 메시지 건너뜀"
    NEW_OFFSET = "    offset = max(0, start_offset - 5)  # 뒤로 물러나 start_time 기반 필터링"

    # 메시지 처리 루프에 시각 필터 추가
    OLD_FILTER = """                # 같은 채팅방에서 온 메시지만 처리
                if str(msg.get("chat", {}).get("id", "")) != chat_id_str:
                    continue
                text = msg.get("text", "").strip().lower()"""

    NEW_FILTER = """                # 같은 채팅방만 허용
                if str(msg.get("chat", {}).get("id", "")) != chat_id_str:
                    continue
                # 요청 이전에 보낸 메시지는 완전히 무시 (5초 여유)
                if start_time and msg.get("date", 0) < start_time - 5:
                    continue
                text = msg.get("text", "").strip().lower()"""

    changed = False
    for old, new, label in [
        (OLD_POLL_SIG, NEW_POLL_SIG, "_poll_reply 시그니처"),
        (OLD_OFFSET, NEW_OFFSET, "offset 계산"),
        (OLD_FILTER, NEW_FILTER, "시각 필터"),
    ]:
        if old in src:
            src = src.replace(old, new)
            print(f"  ✅ {label} 패치 성공")
            changed = True
        else:
            print(f"  ℹ️  {label} — 이미 패치됨 (스킵)")

    # ── 패치 2: request_real_trading_approval 내 start_time 전달 ──
    OLD_RT1 = "        last_id = _get_last_update_id()\n\n        send_message(msg, force=True)"
    NEW_RT1 = "        last_id = _get_last_update_id()\n        start_time = int(__import__('time').time())\n\n        send_message(msg, force=True)"

    OLD_RT2 = "        result, _ = _poll_reply(approve_words, reject_words, timeout_seconds, last_id)\n"
    NEW_RT2 = "        result, _ = _poll_reply(approve_words, reject_words, timeout_seconds, last_id, start_time)\n"

    for old, new, label in [
        (OLD_RT1, NEW_RT1, "start_time 정의"),
        (OLD_RT2, NEW_RT2, "_poll_reply start_time 전달"),
    ]:
        if old in src:
            src = src.replace(old, new)
            print(f"  ✅ {label} 패치 성공")
            changed = True
        else:
            print(f"  ℹ️  {label} — 이미 패치됨 (스킵)")

    # ── 패치 3: request_sell_confirmation 내 start_time 전달 ──
    OLD_SELL = "    result, _ = _poll_reply(approve_words, reject_words, timeout, last_id)\n"
    NEW_SELL = "    _st = int(__import__('time').time())\n    result, _ = _poll_reply(approve_words, reject_words, timeout, last_id, _st)\n"

    if OLD_SELL in src:
        src = src.replace(OLD_SELL, NEW_SELL)
        print("  ✅ sell_confirmation start_time 전달 패치 성공")
        changed = True
    else:
        print("  ℹ️  sell_confirmation — 이미 패치됨 (스킵)")

    if changed:
        with open(NOTIFIER_FILE, "w", encoding="utf-8") as f:
            f.write(src)
        print("  ✅ utils/notifier.py 저장 완료")
    else:
        print("  ℹ️  변경사항 없음")


def patch_main():
    """main.py 에서 실전투자 승인 타임아웃을 180초(3분)으로 연장"""
    print("\n[2/2] main.py 패치 중...")

    with open(MAIN_FILE, "r", encoding="utf-8") as f:
        src = f.read()

    backup_file(MAIN_FILE)

    OLD_TIMEOUT = "approved = notifier.request_real_trading_approval(timeout_seconds=120)"
    NEW_TIMEOUT = "approved = notifier.request_real_trading_approval(timeout_seconds=180)  # 3분으로 연장"

    if OLD_TIMEOUT in src:
        src = src.replace(OLD_TIMEOUT, NEW_TIMEOUT)
        with open(MAIN_FILE, "w", encoding="utf-8") as f:
            f.write(src)
        print("  ✅ 승인 타임아웃 120초 → 180초(3분) 연장 완료")
    elif "timeout_seconds=180" in src:
        print("  ℹ️  이미 180초로 설정되어 있음 (스킵)")
    else:
        print("  ⚠️  타임아웃 라인을 찾지 못했습니다. 수동 확인 필요")


def syntax_check():
    """파이썬 문법 검사"""
    print("\n[문법 검사]")
    import py_compile
    for path, label in [(NOTIFIER_FILE, "notifier.py"), (MAIN_FILE, "main.py")]:
        try:
            py_compile.compile(path, doraise=True)
            print(f"  ✅ {label} — 문법 OK")
        except py_compile.PyCompileError as e:
            print(f"  ❌ {label} — 문법 오류: {e}")
            sys.exit(1)


def main():
    print("=" * 55)
    print("  AutoStock 실전투자 승인 버그 패치 시작")
    print(f"  실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    patch_notifier()
    patch_main()
    syntax_check()

    print("\n" + "=" * 55)
    print("🎉 패치 완료! 이제 프로그램을 재시작해 주세요:")
    print("")
    print("  python3 run_background.py stop")
    print("  python3 run_background.py start")
    print("")
    print("📱 텔레그램에 6자리 코드가 오면 즉시 답장하세요.")
    print("   3분(180초) 이내에 응답하면 자동 승인됩니다!")
    print("=" * 55)


if __name__ == "__main__":
    main()
