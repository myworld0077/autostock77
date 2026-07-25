"""
AutoStock 실전투자 전환 및 업데이트 스크립트 (update_real.py)
============================================================
- 이 스크립트를 오라클 클라우드 터미널에서 실행하면 다음 작업을 자동으로 처리합니다:
  1. 기존 백그라운드 프로그램 안전하게 종료
  2. Git Pull을 통한 최신 패치(주말 텔레그램 조회 허용 등) 반영
  3. .env 파일의 TRADE_MODE를 'real' (실전투자)로 자동 전환
  4. 백그라운드 모드로 재가동

사용법:
  python3 update_real.py
"""

import os
import sys
import subprocess
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
ENV_FILE = os.path.join(SCRIPT_DIR, ".env")

def run_command(cmd, desc):
    print(f"🔄 {desc} 진행 중...")
    try:
        result = subprocess.run(cmd, cwd=SCRIPT_DIR, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ {desc} 성공")
            if result.stdout.strip():
                print(result.stdout.strip())
        else:
            print(f"⚠️ {desc} 주의/경고 (코드 {result.returncode})")
            if result.stderr.strip():
                print(result.stderr.strip())
    except Exception as e:
        print(f"❌ {desc} 실패: {e}")

def modify_env_to_real():
    print("🔄 .env 파일을 실전투자(real) 모드로 전환 중...")
    if not os.path.exists(ENV_FILE):
        print("❌ .env 파일이 존재하지 않습니다. 먼저 .env 파일을 생성해 주세요.")
        sys.exit(1)
        
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        modified = False
        new_lines = []
        for line in lines:
            if line.strip().startswith("TRADE_MODE"):
                new_lines.append("TRADE_MODE='real'\n")
                modified = True
            else:
                new_lines.append(line)
                
        if not modified:
            new_lines.insert(0, "TRADE_MODE='real'\n")
            
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
            
        print("✅ .env 파일 실전투자(real) 모드 전환 완료!")
    except Exception as e:
        print(f"❌ .env 파일 수정 중 오류 발생: {e}")
        sys.exit(1)

def main():
    print("====================================================")
    print("  AutoStock 실전투자 전환 및 자동 업데이트 시작")
    print("====================================================")
    
    # 1. 백그라운드 프로그램 종료
    run_command([sys.executable, "run_background.py", "stop"], "기존 프로그램 종료")
    time.sleep(2)
    
    # 2. git pull로 최신 코드 가져오기
    run_command(["git", "pull"], "최신 소스코드 다운로드(Git Pull)")
    time.sleep(1)
    
    # 3. .env 파일 수정
    modify_env_to_real()
    time.sleep(1)
    
    # 4. 백그라운드로 프로그램 재가동
    print("🔄 백그라운드 자동매매 프로그램 시작 중...")
    # start_new_session=True 처리를 위해 run_background.py의 start()를 서브프로세스로 실행
    proc = subprocess.Popen(
        [sys.executable, "run_background.py", "start"],
        cwd=SCRIPT_DIR
    )
    proc.wait()
    
    print("\n====================================================")
    print("🎉 실전투자 가동 처리가 완료되었습니다!")
    print("   - 텔레그램 채팅창에 6자리 승인코드가 오면 터미널에 입력해 주세요.")
    print("====================================================")

if __name__ == "__main__":
    main()
