"""
운영 시간(세션) 변경 파이썬 3 패치 스크립트 (apply_session_patch.py)
===============================================================
- NXT 프리마켓: 08:00 ~ 08:50
- KRX 정규장:   09:00 ~ 15:30
- NEX 애프터마켓: 15:40 ~ 20:00
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
MAIN_FILE = os.path.join(SCRIPT_DIR, "main.py")

def main():
    if not os.path.exists(MAIN_FILE):
        print(f"❌ main.py 파일을 찾을 수 없습니다: {MAIN_FILE}")
        sys.exit(1)

    with open(MAIN_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    target_old = """    SESSIONS = [
        (9,  0, 15, 30, "KRX 정규장"),
    ]"""

    target_new = """    SESSIONS = [
        (8,  0,  8, 50, "NXT 프리마켓"),
        (9,  0, 15, 30, "KRX 정규장"),
        (15, 40, 20,  0, "NEX 애프터마켓"),
    ]"""

    if target_old in content:
        content = content.replace(target_old, target_new)
        with open(MAIN_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        print("✅ main.py 세션 설정(NXT/KRX/NEX) 변경 완료!")
    elif "NXT 프리마켓" in content:
        print("ℹ️ 이미 세션 설정이 적용되어 있습니다.")
    else:
        print("⚠️ 세션 설정 위치를 찾을 수 없습니다. 수동 확인이 필요합니다.")

if __name__ == "__main__":
    main()
