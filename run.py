"""
AutoStock 컨트롤 런처
======================
  1  → 가동 (자동매매 시작)
  2  → 잔고 및 보유종목 조회
  0  → 중지 및 종료
"""
import subprocess
import sys
import os
from typing import Optional

# stdout UTF-8 강제 (Windows cp949 이모지 오류 방지)
import io
try:
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
_proc: Optional[subprocess.Popen] = None


def is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def start_program():
    global _proc
    if is_running():
        print("⚠️  이미 실행 중입니다. 먼저 '0'으로 종료하세요.")
        return
    print("\n🚀 AutoStock 시작 중...\n" + "=" * 50)
    _proc = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=SCRIPT_DIR,
    )
    print(f"✅ PID {_proc.pid} 로 시작됨. 종료하려면 '0' 입력.\n")


def stop_program():
    global _proc
    if not is_running():
        print("ℹ️  실행 중인 프로그램이 없습니다.")
        return
    print(f"\n🛑 PID {_proc.pid} 종료 중...")
    _proc.terminate()
    try:
        _proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _proc.kill()
        _proc.wait()
    print("✅ AutoStock 종료 완료.\n")
    _proc = None


def show_account_info():
    print("\n⏳ [잔고 및 보유종목 조회 중...]")
    try:
        from core.account import get_balance, get_holdings
        balance = get_balance()
        print(f"\n===== 💰 계좌 잔고 =====")
        print(f"주문가능현금 : {balance['cash']:,} 원")
        print(f"총 평가금액  : {balance['total_eval']:,} 원")
        print(f"총 평가손익  : {balance['total_profit']:,} 원 ({balance['profit_rate']:.2f}%)")
        
        holdings = get_holdings()
        print(f"\n===== 📊 보유 종목 ({len(holdings)}종목) =====")
        if not holdings:
            print("보유 중인 종목이 없습니다.")
        else:
            for item in holdings:
                print(f"- {item['name']} ({item['code']}): {item['qty']}주 | 수익: {item['profit']:,}원 ({item['profit_rate']:.2f}%)")
        print("============================\n")
    except Exception as e:
        print(f"❌ 조회 실패: {e}\n")


def print_menu():
    status = "🟢 실행 중" if is_running() else "⚫ 정지"
    print(f"\n{'='*40}")
    print(f"  AutoStock 컨트롤러  [{status}]")
    print(f"{'='*40}")
    print("  1  →  가동 (자동매매 시작)")
    print("  2  →  잔고 및 매매내역(보유) 조회")
    print("  0  →  중지 및 런처 종료")
    print(f"{'='*40}")


def main():
    print_menu()
    while True:
        # 프로세스 상태 자동 갱신
        if _proc is not None and _proc.poll() is not None:
            print(f"\n⚠️  프로그램이 종료되었습니다 (종료코드: {_proc.returncode})")

        try:
            cmd = input("명령 입력 (1/2/0): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n런처 종료.")
            stop_program()
            break

        if cmd == "1":
            start_program()
        elif cmd == "2":
            show_account_info()
        elif cmd == "0":
            stop_program()
            print("런처를 종료합니다.")
            break
        else:
            print("  ❓ 알 수 없는 명령입니다. (1=가동 / 2=잔고조회 / 0=중지)")


if __name__ == "__main__":
    main()
