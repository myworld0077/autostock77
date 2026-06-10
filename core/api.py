"""
한국투자증권 REST API 클라이언트
- 토큰 발급/갱신 (모의투자/실전투자 자동 분기)
- 토큰 파일 캐시 (모드별 분리 저장)
- 공통 GET/POST 요청 헬퍼
"""
import os
import json
import time
import requests
from typing import Dict, Optional
from config.settings import settings
from utils.logger import log


class KoreaInvestAPI:
    """한국투자증권 Open API 래퍼"""

    def __init__(self):
        self._access_token: str = ""
        self._token_expires_at: float = 0
        self._current_mode: str = ""       # 토큰 발급 당시 모드 저장
        self._base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._load_cached_token()

    # ─── 토큰 파일 경로 (모드별 분리) ───────────────────────────

    @property
    def _token_file(self) -> str:
        mode = settings.TRADE_MODE          # 'paper' or 'real'
        return os.path.join(self._base_dir, f"token_{mode}.json")

    # ─── 프로퍼티 (항상 settings 최신값 반영) ───────────────────

    @property
    def base_url(self) -> str:
        return settings.BASE_URL

    @property
    def app_key(self) -> str:
        return settings.APP_KEY

    @property
    def app_secret(self) -> str:
        return settings.APP_SECRET

    # ─── 토큰 캐시 로드 ─────────────────────────────────────────

    def _load_cached_token(self):
        """모드에 맞는 캐시 파일에서 토큰 로드"""
        token_file = self._token_file
        if not os.path.exists(token_file):
            return
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 저장된 key가 현재 key와 일치하고, 1시간 이상 유효 시에만 사용
            if (data.get("app_key") == settings.APP_KEY
                    and data.get("expires_at", 0) > time.time() + 3600):
                self._access_token = data["access_token"]
                self._token_expires_at = data["expires_at"]
                self._current_mode = settings.TRADE_MODE
                remaining_h = (self._token_expires_at - time.time()) / 3600
                log.info(f"[AUTH] 캐시된 토큰 로드 완료 (잔여 {remaining_h:.1f}h)")
            else:
                log.info("[AUTH] 캐시된 토큰이 만료되었거나 키가 변경됨 → 재발급 예정")
        except Exception as e:
            log.warning(f"[AUTH] 토큰 파일 읽기 실패: {e}")

    # ─── 토큰 캐시 저장 ─────────────────────────────────────────

    def _save_token(self):
        try:
            with open(self._token_file, "w", encoding="utf-8") as f:
                json.dump({
                    "access_token": self._access_token,
                    "expires_at": self._token_expires_at,
                    "app_key": settings.APP_KEY,      # 키 변경 감지용
                    "trade_mode": settings.TRADE_MODE,
                }, f, indent=2)
        except Exception as e:
            log.warning(f"[AUTH] 토큰 파일 저장 실패: {e}")

    # ─── 토큰 발급 ──────────────────────────────────────────────

    def _issue_token(self):
        """OAuth 접근 토큰 발급 (실패 시 상세 오류 출력)"""
        mode_str = "모의투자" if settings.is_paper else "실전투자"
        log.info(f"[AUTH] {mode_str} 접근 토큰 발급 시도 → {self.base_url}")

        # ── 사전 검증 ──────────────────────────────────────────
        if not settings.APP_KEY or not settings.APP_SECRET:
            key_var = "PAPER_APP_KEY" if settings.is_paper else "REAL_APP_KEY"
            secret_var = "PAPER_APP_SECRET" if settings.is_paper else "REAL_APP_SECRET"
            raise ValueError(
                f"[AUTH] .env에 {key_var} 또는 {secret_var}가 설정되지 않았습니다. "
                f"KIS 개발자센터(https://apiportal.koreainvestment.com)에서 "
                f"{mode_str}용 키를 발급받아 .env에 입력하세요."
            )

        url = f"{self.base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        headers = {"content-type": "application/json"}

        try:
            resp = requests.post(url, json=body, headers=headers, timeout=10)
        except requests.exceptions.ConnectionError:
            raise ConnectionError(
                f"[AUTH] KIS 서버에 연결할 수 없습니다: {self.base_url}\n"
                "       인터넷 연결 또는 서버 주소를 확인하세요."
            )

        if resp.status_code == 403:
            err = resp.json() if resp.content else {}
            err_code = err.get("error_code", "")
            err_desc = err.get("error_description", resp.text)

            hints = {
                "EGW00103": (
                    f"유효하지 않은 AppKey입니다.\n"
                    f"  → {mode_str}용 APP_KEY가 .env에 올바르게 입력되어 있는지 확인하세요.\n"
                    f"  → 모의투자 키: PAPER_APP_KEY / 실전투자 키: REAL_APP_KEY\n"
                    f"  → KIS 개발자센터: https://apiportal.koreainvestment.com\n"
                    f"  → 현재 KEY(앞8자): {self.app_key[:8]}..."
                ),
                "EGW00104": "AppSecret이 잘못되었습니다. .env의 APP_SECRET을 확인하세요.",
                "EGW00121": "토큰 발급 횟수를 초과했습니다. 하루 1회만 발급 가능합니다.",
            }
            hint = hints.get(err_code, err_desc)
            log.error(f"[AUTH] 토큰 발급 실패 (HTTP 403 / {err_code})\n  {hint}")
            # 텔레그램으로 키 오류 알림
            try:
                from utils.notifier import notify_auth_error
                notify_auth_error(settings.TRADE_MODE, err_code)
            except Exception:
                pass
            resp.raise_for_status()

        if resp.status_code != 200:
            log.error(f"[AUTH] 토큰 발급 실패 (HTTP {resp.status_code}): {resp.text}")
            resp.raise_for_status()

        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + 82800   # 23h 후 갱신
        self._current_mode = settings.TRADE_MODE
        log.info(f"[AUTH] {mode_str} 접근 토큰 발급 완료 ✅")
        self._save_token()

    # ─── 유효 토큰 반환 ─────────────────────────────────────────

    @property
    def token(self) -> str:
        """유효한 토큰 반환. 만료·모드 변경 시 자동 재발급."""
        mode_changed = (self._current_mode != settings.TRADE_MODE)
        if mode_changed:
            log.info(f"[AUTH] 모드 변경 감지 ({self._current_mode} → {settings.TRADE_MODE}) → 토큰 재발급")
            self._access_token = ""
        if not self._access_token or time.time() >= self._token_expires_at:
            self._issue_token()
        return self._access_token

    # ─── hashkey ────────────────────────────────────────────────

    def _hashkey(self, body: dict) -> str:
        """POST 요청 시 필요한 hashkey 생성"""
        url = f"{self.base_url}/uapi/hashkey"
        headers = {
            "Content-Type": "application/json",
            "appKey": self.app_key,
            "appSecret": self.app_secret,
        }
        resp = requests.post(url, json=body, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()["HASH"]

    # ─── 공통 요청 ──────────────────────────────────────────────

    def _headers(self, tr_id: str) -> dict:
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }
        if settings.HTS_ID:
            headers["custtype"] = "P"
            headers["HTS_ID"] = settings.HTS_ID
        return headers

    def get(self, path: str, tr_id: str, params: Optional[Dict] = None) -> dict:
        """GET 요청 (최대 5회 재시도 / 500 에러는 즉시 포기 / 지수 백오프 적용)"""
        url = f"{self.base_url}{path}"
        headers = self._headers(tr_id)
        last_exc: Exception = RuntimeError("GET 요청 실패")
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=10)
                if resp.status_code == 500:
                    raise requests.exceptions.HTTPError(
                        f"500 Server Error (장외시간 서버 제한) — 재시도 없음",
                        response=resp,
                    )
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.HTTPError as e:
                last_exc = e
                if getattr(e.response, 'status_code', 0) == 500:
                    raise last_exc
                if attempt == max_attempts - 1:
                    log.error(f"[API] GET 요청 실패 (최종): {url} - {e}")
                else:
                    sleep_time = 2 ** attempt + 1
                    log.warning(f"[API] GET 요청 지연/오류 재시도 ({attempt+1}/{max_attempts}) - {sleep_time}초 대기: {e}")
                    time.sleep(sleep_time)
            except requests.exceptions.RequestException as e:
                last_exc = e
                if attempt == max_attempts - 1:
                    log.error(f"[API] GET 요청 실패 (최종): {url} - {e}")
                else:
                    sleep_time = 2 ** attempt + 1
                    log.warning(f"[API] GET 요청 지연/오류 재시도 ({attempt+1}/{max_attempts}) - {sleep_time}초 대기: {e}")
                    time.sleep(sleep_time)
        raise last_exc

    def post(self, path: str, tr_id: str, body: dict) -> dict:
        """POST 요청 (최대 5회 재시도 / 지수 백오프 적용)"""
        url = f"{self.base_url}{path}"
        last_exc: Exception = RuntimeError("POST 요청 실패")
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                headers = self._headers(tr_id)
                headers["hashkey"] = self._hashkey(body)
                resp = requests.post(url, headers=headers, json=body, timeout=10)
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                last_exc = e
                if attempt == max_attempts - 1:
                    log.error(f"[API] POST 요청 실패 (최종): {url} - {e}")
                else:
                    sleep_time = 2 ** attempt + 1
                    log.warning(f"[API] POST 요청 지연/오류 재시도 ({attempt+1}/{max_attempts}) - {sleep_time}초 대기: {e}")
                    time.sleep(sleep_time)
        raise last_exc


# 싱글턴 인스턴스
api = KoreaInvestAPI()
