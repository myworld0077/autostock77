#!/bin/bash
# ============================================================
# AutoStock 오라클 클라우드 관리 스크립트 (sudo 불필요 버전)
# systemd --user 모드 사용 (root 권한 없이 24시간 운영)
#
# 사용법:
#   bash setup_oracle.sh install   # 최초 설치 (1회만)
#   bash setup_oracle.sh start     # 시작
#   bash setup_oracle.sh stop      # 중지
#   bash setup_oracle.sh restart   # 재시작
#   bash setup_oracle.sh status    # 상태 확인
#   bash setup_oracle.sh log       # 실시간 로그
#   bash setup_oracle.sh update    # git pull 후 재시작
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="autostock"
USER_SYSTEMD_DIR="${HOME}/.config/systemd/user"
SERVICE_FILE="${USER_SYSTEMD_DIR}/${SERVICE_NAME}.service"
LOG_FILE="${SCRIPT_DIR}/logs/autostock.log"
ERR_FILE="${SCRIPT_DIR}/logs/autostock_error.log"
PID_FILE="${SCRIPT_DIR}/logs/autostock.pid"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_ok()   { echo -e "${GREEN}[OK]${NC}   $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err()  { echo -e "${RED}[ERR]${NC}  $1"; }
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }

# ──────────────────────────────────────────────────────────────
# 공통: systemd --user 사용 가능 여부 확인
# ──────────────────────────────────────────────────────────────
use_systemd() {
    systemctl --user status > /dev/null 2>&1
    return $?
}

# ──────────────────────────────────────────────────────────────
# 1. 설치 (최초 1회)
# ──────────────────────────────────────────────────────────────
cmd_install() {
    log_info "=== AutoStock 설치 시작 (sudo 없는 사용자 모드) ==="

    # 로그 폴더 생성
    mkdir -p "${SCRIPT_DIR}/logs"
    log_ok "로그 폴더 생성: ${SCRIPT_DIR}/logs"

    # .env 확인
    if [ ! -f "${SCRIPT_DIR}/.env" ]; then
        log_err ".env 파일이 없습니다!"
        exit 1
    fi
    log_ok ".env 파일 확인 완료"

    # 파이썬 패키지
    log_info "파이썬 패키지 설치 중..."
    pip3 install --user -r "${SCRIPT_DIR}/requirements.txt" --quiet
    log_ok "파이썬 패키지 설치 완료"

    # systemd --user 사용 가능하면 서비스 등록
    if use_systemd; then
        mkdir -p "${USER_SYSTEMD_DIR}"
        PYTHON3_PATH=$(which python3)

        cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=AutoStock 자동매매 (래리 윌리엄스 변동성 돌파)
After=network.target

[Service]
Type=simple
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${PYTHON3_PATH} ${SCRIPT_DIR}/main.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
Environment=TZ=Asia/Seoul
EnvironmentFile=${SCRIPT_DIR}/.env
StandardOutput=append:${LOG_FILE}
StandardError=append:${ERR_FILE}

[Install]
WantedBy=default.target
EOF

        systemctl --user daemon-reload
        systemctl --user enable "${SERVICE_NAME}" 2>/dev/null
        log_ok "systemd --user 서비스 등록 완료"

        # linger 활성화 시도 (로그아웃 후에도 서비스 유지)
        loginctl enable-linger "$(whoami)" 2>/dev/null && \
            log_ok "linger 활성화: 로그아웃 후에도 서비스 유지됩니다" || \
            log_warn "linger 활성화 실패 — nohup 모드로 대신 운영합니다"
    else
        log_warn "systemd --user 사용 불가 → nohup 백그라운드 모드로 운영합니다"
    fi

    echo ""
    log_ok "=== 설치 완료! ==="
    echo "  시작:   bash setup_oracle.sh start"
    echo "  상태:   bash setup_oracle.sh status"
    echo "  로그:   bash setup_oracle.sh log"
}

# ──────────────────────────────────────────────────────────────
# 2. 시작
# ──────────────────────────────────────────────────────────────
cmd_start() {
    mkdir -p "${SCRIPT_DIR}/logs"

    # 이미 실행 중인지 확인
    if [ -f "${PID_FILE}" ]; then
        OLD_PID=$(cat "${PID_FILE}")
        if kill -0 "${OLD_PID}" 2>/dev/null; then
            log_warn "AutoStock이 이미 실행 중입니다. (PID: ${OLD_PID})"
            log_info "재시작하려면: bash setup_oracle.sh restart"
            return
        fi
    fi

    if use_systemd && [ -f "${SERVICE_FILE}" ]; then
        # systemd --user 모드
        systemctl --user start "${SERVICE_NAME}"
        sleep 2
        if systemctl --user is-active "${SERVICE_NAME}" > /dev/null 2>&1; then
            PID=$(systemctl --user show "${SERVICE_NAME}" -p MainPID --value 2>/dev/null)
            [ -n "${PID}" ] && echo "${PID}" > "${PID_FILE}"
            log_ok "AutoStock 시작 완료 (systemd --user | PID: ${PID})"
        else
            log_err "systemd 시작 실패 → nohup 모드로 재시도"
            _start_nohup
        fi
    else
        # nohup 모드 (Cloud Shell 등 systemd 없는 환경)
        _start_nohup
    fi
}

_start_nohup() {
    log_info "nohup 백그라운드 모드로 시작..."
    export TZ=Asia/Seoul
    export PYTHONUNBUFFERED=1

    # .env 로드
    if [ -f "${SCRIPT_DIR}/.env" ]; then
        set -a
        source "${SCRIPT_DIR}/.env"
        set +a
    fi

    nohup python3 "${SCRIPT_DIR}/main.py" \
        >> "${LOG_FILE}" 2>> "${ERR_FILE}" &

    BGPID=$!
    echo "${BGPID}" > "${PID_FILE}"
    sleep 2

    if kill -0 "${BGPID}" 2>/dev/null; then
        log_ok "AutoStock 시작 완료 (nohup | PID: ${BGPID})"
        log_info "로그: bash setup_oracle.sh log"
        log_warn "주의: Cloud Shell 세션 종료 시 프로세스가 종료될 수 있습니다."
        log_warn "      오라클 VM 인스턴스(Compute)에서 실행 시 완전한 24시간 운영 가능"
    else
        log_err "시작 실패! 에러 로그 확인:"
        tail -n 20 "${ERR_FILE}" 2>/dev/null
    fi
}

# ──────────────────────────────────────────────────────────────
# 3. 중지
# ──────────────────────────────────────────────────────────────
cmd_stop() {
    # systemd 모드
    if use_systemd && systemctl --user is-active "${SERVICE_NAME}" > /dev/null 2>&1; then
        systemctl --user stop "${SERVICE_NAME}"
        log_ok "systemd 서비스 중지 완료"
    fi

    # PID 파일로 프로세스 종료
    if [ -f "${PID_FILE}" ]; then
        PID=$(cat "${PID_FILE}")
        if kill -0 "${PID}" 2>/dev/null; then
            kill "${PID}"
            sleep 1
            kill -9 "${PID}" 2>/dev/null
            log_ok "AutoStock 프로세스 종료 완료 (PID: ${PID})"
        else
            log_warn "이미 종료된 프로세스입니다 (PID: ${PID})"
        fi
        rm -f "${PID_FILE}"
    else
        # PID 파일 없으면 프로세스 이름으로 찾아서 종료
        PIDS=$(pgrep -f "python3.*main.py" 2>/dev/null)
        if [ -n "${PIDS}" ]; then
            echo "${PIDS}" | xargs kill 2>/dev/null
            log_ok "AutoStock 프로세스 종료 완료"
        else
            log_warn "실행 중인 AutoStock 프로세스가 없습니다."
        fi
    fi
}

# ──────────────────────────────────────────────────────────────
# 4. 재시작
# ──────────────────────────────────────────────────────────────
cmd_restart() {
    log_info "AutoStock 재시작 중..."
    cmd_stop
    sleep 2
    cmd_start
}

# ──────────────────────────────────────────────────────────────
# 5. 상태 확인
# ──────────────────────────────────────────────────────────────
cmd_status() {
    echo ""
    echo "========================================="
    echo "  AutoStock 운영 상태"
    echo "========================================="

    # 실행 여부
    RUNNING=false
    ACTIVE_PID=""

    if [ -f "${PID_FILE}" ]; then
        PID=$(cat "${PID_FILE}")
        if kill -0 "${PID}" 2>/dev/null; then
            RUNNING=true
            ACTIVE_PID="${PID}"
        fi
    fi

    # pgrep으로 재확인
    PIDS=$(pgrep -f "python3.*main.py" 2>/dev/null)
    if [ -n "${PIDS}" ]; then
        RUNNING=true
        ACTIVE_PID="${PIDS}"
    fi

    if ${RUNNING}; then
        echo -e "  상태:  ${GREEN}🟢 실행 중${NC} (PID: ${ACTIVE_PID})"
    else
        echo -e "  상태:  ${RED}⚫ 정지됨${NC}"
    fi

    # systemd 상태
    if use_systemd && [ -f "${SERVICE_FILE}" ]; then
        SYSSTAT=$(systemctl --user is-active "${SERVICE_NAME}" 2>/dev/null)
        echo "  systemd: ${SYSSTAT}"
    else
        echo "  모드:  nohup 백그라운드"
    fi

    echo "  로그:  ${LOG_FILE}"
    echo "========================================="

    echo ""
    echo "=== 최근 로그 (20줄) ==="
    if [ -f "${LOG_FILE}" ]; then
        tail -n 20 "${LOG_FILE}"
    else
        log_warn "로그 파일 없음: ${LOG_FILE}"
        log_info "서비스 시작 후 로그가 생성됩니다: bash setup_oracle.sh start"
    fi
}

# ──────────────────────────────────────────────────────────────
# 6. 실시간 로그
# ──────────────────────────────────────────────────────────────
cmd_log() {
    if [ -f "${LOG_FILE}" ]; then
        log_info "실시간 로그 (Ctrl+C 로 종료):"
        tail -f "${LOG_FILE}"
    else
        log_warn "로그 파일 없음. 서비스를 먼저 시작하세요:"
        echo "  bash setup_oracle.sh start"
    fi
}

# ──────────────────────────────────────────────────────────────
# 7. 업데이트
# ──────────────────────────────────────────────────────────────
cmd_update() {
    log_info "최신 코드 내려받는 중..."
    cd "${SCRIPT_DIR}" && git pull
    if [ $? -ne 0 ]; then
        log_err "git pull 실패!"
        exit 1
    fi
    log_ok "코드 업데이트 완료"

    pip3 install --user -r "${SCRIPT_DIR}/requirements.txt" --quiet
    log_ok "패키지 업데이트 완료"

    cmd_restart
}

# ──────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────
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
        echo "  AutoStock 오라클 클라우드 관리 (sudo 불필요)"
        echo ""
        echo "  사용법: bash setup_oracle.sh [명령]"
        echo ""
        echo "  install  - 최초 설치 (1회만 실행)"
        echo "  start    - 서비스 시작"
        echo "  stop     - 서비스 중지"
        echo "  restart  - 재시작"
        echo "  status   - 상태 확인"
        echo "  log      - 실시간 로그 보기"
        echo "  update   - 최신 코드 반영 후 재시작"
        echo ""
        ;;
esac
