"""
AutoStock 오라클 클라우드 패치 적용 스크립트 (apply_patch.py)
=============================================================
이 파일을 오라클 클라우드 터미널에서 실행하면
수정된 utils/notifier.py 코드가 즉시 서버에 반영됩니다.

사용법:
  python3 apply_patch.py
"""

import os
import sys
import shutil
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
TARGET = os.path.join(SCRIPT_DIR, "utils", "notifier.py")

NEW_POLL_FUNC = '''

def _poll_reply(
    approve_words: list,
    reject_words: list,
    timeout: int,
    start_offset: int,
    start_time: int = 0,
) -> tuple:
    """
    timeout 초 동안 텔레그램 메시지를 1초 간격 짧은 폴링으로 확인.
    - 롱폴링 제거 -> 1초 간격 재폴링으로 즉각 반응
    - start_time 기준으로 과거 메시지 무시
    Returns: ('approve' | 'reject' | 'timeout', last_update_id)
    """
    import requests as _req
    from config.settings import settings as _cfg

    token   = _cfg.TELEGRAM_TOKEN
    chat_id = str(_cfg.TELEGRAM_CHAT_ID)
    if not token or not chat_id:
        return 'timeout', start_offset

    deadline = time.time() + timeout
    offset   = start_offset  # 전송 직후 재획득한 offset 그대로 사용

    while time.time() < deadline:
        try:
            resp = _req.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": offset, "limit": 10,
                        "allowed_updates": ["message"]},
                timeout=5,
            )
            for upd in resp.json().get("result", []):
                offset = max(offset, upd["update_id"] + 1)
                msg = upd.get("message", {})

                # 같은 채팅방만
                if str(msg.get("chat", {}).get("id", "")) != chat_id:
                    continue
                # 전송 이전 메시지 무시 (5초 여유)
                if start_time and msg.get("date", 0) < start_time - 5:
                    continue

                text = msg.get("text", "").strip().lower()
                if any(w in text for w in approve_words):
                    return 'approve', offset
                if any(w in text for w in reject_words):
                    return 'reject', offset
        except Exception:
            pass

        time.sleep(1)   # 1초 간격 재폴링

    return 'timeout', offset


def request_real_trading_approval(timeout_seconds: int = 180) -> bool:
    """
    실전투자 전환 시 텔레그램으로 6자리 코드를 전송하고
    사용자가 해당 코드를 텔레그램에서 답장하면 즉시 승인.
    - 1초 간격 폴링으로 즉각 인식
    - 메시지 전송 후 offset 재획득으로 누락 방지
    - 기본 대기: 180초(3분)
    """
    import random, string
    from utils.logger import log as _log
    from utils.notifier import send_message, _get_cfg, _timed_input

    token, chat_id = _get_cfg()
    has_telegram = bool(token and chat_id)

    _log.warning("=" * 55)
    _log.warning("  [실전투자] 실제 자금이 사용됩니다!")
    _log.warning("  REAL_CANO, REAL_APP_KEY 계좌로 주문이 발생합니다.")
    _log.warning("=" * 55)

    if not has_telegram:
        _log.warning("[WARN] 텔레그램 미설정 - 콘솔 확인으로 진행합니다.")
        ui = _timed_input("실전투자 시작? (Y + Enter): ", timeout_seconds)
        if ui and ui.strip().upper() == "Y":
            _log.info("[REAL] 콘솔 승인 완료.")
            return True
        _log.info("[REAL] 취소.")
        return False

    # 6자리 코드 생성
    code = "".join(random.choices(string.digits, k=6))
    msg = (
        f"\\U0001f534 <b>[실전투자 승인 요청]</b>\\n"
        f"━━━━━━━━━━━━━━\\n"
        f"AutoStock 실전투자를 시작하려 합니다.\\n\\n"
        f"\\u2705 아래 코드를 이 채팅방에 <b>그대로 입력 후 전송</b>하세요.\\n\\n"
        f"   \\U0001f449 <code>{code}</code>\\n\\n"
        f"\\u23f1 유효시간: {timeout_seconds}초 ({timeout_seconds // 60}분)"
    )

    # ★ 핵심: 전송 시각 기록
    start_time = int(time.time())

    # ★ 핵심: 전송 후 offset 재획득
    send_message(msg, force=True)
    time.sleep(0.5)

    import requests as _req
    try:
        r = _req.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"limit": 1, "offset": -1}, timeout=5
        )
        updates = r.json().get("result", [])
        last_id = updates[-1]["update_id"] + 1 if updates else 0
    except Exception:
        last_id = 0

    _log.warning(f"[TELEGRAM] 승인 코드 전송 완료 ({code}) - 텔레그램에서 {code} 을 전송해 주세요. ({timeout_seconds}초 대기)")

    result, _ = _poll_reply(
        approve_words=[code],
        reject_words=["취소", "no", "cancel"],
        timeout=timeout_seconds,
        start_offset=last_id,
        start_time=start_time,
    )

    if result == "approve":
        _log.info("[REAL] ✅ 텔레그램 승인 성공 - 실전투자 시작.")
        send_message("✅ <b>실전투자 승인 완료</b>\\nAutoStock 실전투자를 시작합니다.", force=True)
        return True
    else:
        _log.warning("[REAL] ❌ 승인 실패/시간초과 - 실전투자 취소.")
        send_message(
            f"❌ <b>실전투자 취소</b>\\n"
            f"승인 시간({timeout_seconds}초) 초과 또는 취소됨.\\n"
            "다시 시작: <code>python3 run_background.py start</code>",
            force=True,
        )
        return False
'''


def main():
    print("=" * 55)
    print("  AutoStock 실전투자 승인 버그 패치 적용")
    print("=" * 55)

    if not os.path.exists(TARGET):
        print(f"❌ 파일 없음: {TARGET}")
        sys.exit(1)

    # 백업
    bak = TARGET + ".bak2"
    shutil.copy2(TARGET, bak)
    print(f"✅ 원본 백업: {bak}")

    # 읽기
    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    # _poll_reply 함수 시작 위치
    marker = "\ndef _poll_reply("
    idx = src.find(marker)
    if idx == -1:
        print("❌ _poll_reply 함수를 찾을 수 없습니다. 수동 확인 필요")
        sys.exit(1)

    # request_real_trading_approval 다음에 나오는 _timed_input 위치를 끝으로 설정
    end_marker = "\n\ndef _timed_input("
    end_idx = src.find(end_marker, idx)
    if end_idx == -1:
        print("❌ _timed_input 함수를 찾을 수 없습니다. 수동 확인 필요")
        sys.exit(1)

    # 두 함수를 새 코드로 교체
    new_src = src[:idx] + NEW_POLL_FUNC + src[end_idx:]

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(new_src)
    print("✅ utils/notifier.py 패치 완료!")

    # 문법 검사
    import py_compile
    try:
        py_compile.compile(TARGET, doraise=True)
        print("✅ 문법 검사 OK")
    except py_compile.PyCompileError as e:
        print(f"❌ 문법 오류 발생: {e}")
        print("   백업 파일로 복구합니다...")
        shutil.copy2(bak, TARGET)
        sys.exit(1)

    print("\n" + "=" * 55)
    print("🎉 패치 완료! 이제 재시작해 주세요:")
    print("")
    print("  python3 run_background.py stop")
    print("  python3 run_background.py start")
    print("")
    print("📱 텔레그램에 6자리 코드가 오면 바로 전송하세요.")
    print("   1초 이내에 즉시 인식하여 실전투자가 시작됩니다!")
    print("=" * 55)


if __name__ == "__main__":
    main()
