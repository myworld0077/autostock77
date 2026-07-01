#!/bin/bash
# ============================================================
# AutoStock 오라클 클라우드 설치/관리 스크립트
# 사용법:
#   bash setup_oracle.sh install   # 최초 설치 및 서비스 등록
#   bash setup_oracle.sh start     # 서비스 시작
#   bash setup_oracle.sh stop      # 서비스 중지
#   bash setup_oracle.sh restart   # 서비스 재시작
#   bash setup_oracle.sh status    # 현재 상태 확인
#   bash setup_oracle.sh log       # 실시간 로그 보기
#   bash setup_oracle.sh update    # git pull 후 재시작
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="autostock"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
LOG_FILE="${SCRIPT_DIR}/logs/autostock.log"
USER_NAME="$(whoami)"

# 색상
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err()  { echo -e "${RED}[ERR]${NC} $1"; }
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }

# ──────────────────────────────────────────────────────────
# 1. 설치 (최초 1회)
# ──────────────────────────────────────────────────────────
cmd_install() {
    log_info "=== AutoStock 오라클 클라우드 설치 시작 ==="

    # 로그 폴더 생성
    mkdir -p "${SCRIPT_DIR}/logs"
    log_ok "로그 폴더 생성: ${SCRIPT_DIR}/logs"

    # .env 파일 확인
    if [ ! -f "${SCRIPT_DIR}/.env" ]; then
        log_err ".env 파일이 없습니다! 먼저 .env를 생성하세요."
        log_warn "  예) cp ${SCRIPT_DIR}/.env.example ${SCRIPT_DIR}/.env && nano ${SCRIPT_DIR}/.env"
        exit 1
    fi
    log_ok ".env 파일 확인 완료"

    # 파이썬 패키지 설치
    log_info "파이썬 패키지 설치 중..."
    pip3 install --user -r "${SCRIPT_DIR}/requirements.txt" --quiet
    log_ok "파이썬 패키지 설치 완료"

    # systemd 서비스 파일 생성
    log_info "systemd 서비스 파일 생성 중..."
    sudo tee "${SERVICE_FILE}" > /dev/null << EOF
[Unit]
Description=AutoStock 자동매매 시스템 (래리 윌리엄스 변동성 돌파)
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${SCRIPT_DIR}
ExecStart=$(which python3) ${SCRIPT_DIR}/main.py
Restart=always
RestartSec=10
StartLimitIntervalSec=120
StartLimitBurst=5

Environment=PYTHONUNBUFFERED=1
Environment=TZ=Asia/Seoul
EnvironmentFile=${SCRIPT_DIR}/.env

StandardOutput=append:${SCRIPT_DIR}/logs/autostock.log
StandardError=append:${SCRIPT_DIR}/logs/autostock_error.log

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable "${SERVICE_NAME}"
    log_ok "systemd 서비스 등록 완료: ${SERVICE_FILE}"

    echo ""
    log_ok "=== 설치 완료! ==="
    echo ""
    echo "  시작:    bash setup_oracle.sh start"
    echo "  상태:    bash setup_oracle.sh status"
    echo "  로그:    bash setup_oracle.sh log"
}

# ──────────────────────────────────────────────────────────
# 2. 시작
# ──────────────────────────────────────────────────────────
cmd_start() {
    sudo systemctl start "${SERVICE_NAME}"
    sleep 2
    STATUS=$(sudo systemctl is-active "${SERVICE_NAME}")
    if [ "$STATUS" = "active" ]; then
        log_ok "AutoStock 서비스 시작 완료 (상태: active)"
        log_info "실시간 로그: bash setup_oracle.sh log"
    else
        log_err "서비스 시작 실패! 상태 확인:"
        sudo systemctl status "${SERVICE_NAME}" --no-pager
    fi
}

# ──────────────────────────────────────────────────────────
# 3. 중지
# ──────────────────────────────────────────────────────────
cmd_stop() {
    sudo systemctl stop "${SERVICE_NAME}"
    log_ok "AutoStock 서비스 중지 완료"
}

# ──────────────────────────────────────────────────────────
# 4. 재시작
# ──────────────────────────────────────────────────────────
cmd_restart() {
    log_info "AutoStock 서비스 재시작 중..."
    sudo systemctl restart "${SERVICE_NAME}"
    sleep 2
    sudo systemctl status "${SERVICE_NAME}" --no-pager -l
}

# ──────────────────────────────────────────────────────────
# 5. 상태 확인
# ──────────────────────────────────────────────────────────
cmd_status() {
    echo ""
    echo "=== AutoStock 서비스 상태 ==="
    sudo systemctl status "${SERVICE_NAME}" --no-pager -l
    echo ""
    echo "=== 최근 로그 (20줄) ==="
    if [ -f "${LOG_FILE}" ]; then
        tail -n 20 "${LOG_FILE}"
    else
        log_warn "로그 파일 없음: ${LOG_FILE}"
    fi
}

# ──────────────────────────────────────────────────────────
# 6. 실시간 로그
# ──────────────────────────────────────────────────────────
cmd_log() {
    if [ -f "${LOG_FILE}" ]; then
        log_info "실시간 로그 (Ctrl+C 로 종료):"
        tail -f "${LOG_FILE}"
    else
        log_warn "로그 파일 없음. 서비스 먼저 시작하세요: bash setup_oracle.sh start"
    fi
}

# ──────────────────────────────────────────────────────────
# 7. 업데이트 (git pull + 재시작)
# ──────────────────────────────────────────────────────────
cmd_update() {
    log_info "GitHub에서 최신 코드 내려받는 중..."
    cd "${SCRIPT_DIR}" && git pull
    if [ $? -ne 0 ]; then
        log_err "git pull 실패! 인터넷 연결 또는 git 설정을 확인하세요."
        exit 1
    fi
    log_ok "코드 업데이트 완료"

    log_info "패키지 업데이트 중..."
    pip3 install --user -r "${SCRIPT_DIR}/requirements.txt" --quiet

    cmd_restart
    log_ok "=== 업데이트 및 재시작 완료 ==="
}

# ──────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────
case "$1" in
    install)  cmd_install ;;
    start)    cmd_start ;;
    stop)     cmd_stop ;;
    restart)  cmd_restart ;;
    status)   cmd_status ;;
    log)      cmd_log ;;
    update)   cmd_update ;;
    *)
        echo ""
        echo "  AutoStock 오라클 클라우드 관리 스크립트"
        echo ""
        echo "  사용법: bash setup_oracle.sh [명령]"
        echo ""
        echo "  install  - 최초 설치 및 서비스 등록 (1회만 실행)"
        echo "  start    - 서비스 시작 (PC 꺼도 24시간 자동 운영)"
        echo "  stop     - 서비스 중지"
        echo "  restart  - 서비스 재시작"
        echo "  status   - 현재 상태 확인"
        echo "  log      - 실시간 로그 보기"
        echo "  update   - 최신 코드 반영 후 재시작"
        echo ""
        ;;
esac
