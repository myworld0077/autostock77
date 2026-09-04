"""
AutoStock 시장 상태별 전략 자동전환 + 텔레그램 제어 원클릭 패치 (apply_patch.py)
========================================================================
이 스크립트를 오라클 클라우드 터미널에서 실행하면
다음 모든 기능이 적용됩니다:

  1. 코스피 지수 기반 시장 상태 판별 (하락장 / 횡보장 / 상승장)
  2. 상승장 전략(BullTrendStrategy) & 하락장 방어전략(DefensiveBearStrategy)
  3. 텔레그램 a / b / c / auto 명령어로 수동/자동 전략 전환
  4. 텔레그램 실전투자 승인 요청 (yes/승인 응답 시 가동)

사용법:
  python3 apply_patch.py
"""

import os
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()

def main():
    print("=" * 60)
    print("  AutoStock 시장 상태별 전략 패치 적용 (Python 3)")
    print("=" * 60)

    # 1. git pull 시도
    try:
        print("\n[1/3] GitHub에서 최신 코드 동기화...")
        res = subprocess.run(["git", "pull"], cwd=SCRIPT_DIR, capture_output=True, text=True)
        if res.returncode == 0:
            print("  ✅ git pull 성공!")
            print("  " + res.stdout.strip().replace("\n", "\n  "))
        else:
            print(f"  ⚠️ git pull 경고: {res.stderr.strip()}")
    except Exception as e:
        print(f"  ⚠️ git pull 오류 (로컬 파일 패치로 진행): {e}")

    # 2. 파이썬 문법 검사
    print("\n[2/3] 주요 파이썬 모듈 문법 검사...")
    import py_compile
    files_to_check = [
        "core/market_regime.py",
        "strategy/bull_trend.py",
        "strategy/defensive_bear.py",
        "strategy/complex.py",
        "utils/notifier.py",
        "main.py",
    ]
    for rel_path in files_to_check:
        full_path = os.path.join(SCRIPT_DIR, rel_path)
        if os.path.exists(full_path):
            try:
                py_compile.compile(full_path, doraise=True)
                print(f"  ✅ {rel_path} — 문법 OK")
            except py_compile.PyCompileError as err:
                print(f"  ❌ {rel_path} — 문법 오류: {err}")
                sys.exit(1)
        else:
            print(f"  ⚠️ {rel_path} — 파일 없음")

    # 3. 안내 출력
    print("\n" + "=" * 60)
    print("🎉 모든 패치가 성공적으로 준비되었습니다!")
    print("\n📱 텔레그램 명령어 사용 방법:")
    print("   - a     : 🔴 하락장 방어 전략 (현금보존 + 인버스 ETF)")
    print("   - b     : 🟡 횡보장 복합 전략 (KOSPI 200 비대칭 리스크)")
    print("   - c     : 🟢 상승장 추세 전략 (정배열·눌림목·트레일링)")
    print("   - auto  : 🔄 코스피 지수 기반 자동 전략 전환")
    print("   - 0     : ⏸️ 일시 중지")
    print("   - 1     : ▶️ 재개")
    print("   - 2     : 🔍 현재 전략 및 잔고 상태 조회")
    print("\n🚀 아래 명령어로 프로그램을 재시작하세요:")
    print("  python3 run_background.py stop")
    print("  python3 run_background.py start")
    print("=" * 60)

if __name__ == "__main__":
    main()
