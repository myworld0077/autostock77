"""
AutoStock - 주식 자동매매 프로그램 설정

TRADE_MODE=paper  → 모의투자 (PAPER_APP_KEY / PAPER_APP_SECRET / PAPER_CANO 사용)
TRADE_MODE=real   → 실전투자 (REAL_APP_KEY  / REAL_APP_SECRET  / REAL_CANO  사용)
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)


class Settings:
    """환경 변수 기반 설정 관리 — 모드에 따라 키/URL/계좌 자동 선택"""

    TRADE_MODE: str = os.getenv("TRADE_MODE", "paper").lower().strip()

    # ── 모의투자 자격증명 ──────────────────────────────────────
    _PAPER_APP_KEY: str = os.getenv("PAPER_APP_KEY", "")
    _PAPER_APP_SECRET: str = os.getenv("PAPER_APP_SECRET", "")
    _PAPER_CANO: str = os.getenv("PAPER_CANO", "")
    _PAPER_PRDT_CD: str = os.getenv("PAPER_ACNT_PRDT_CD", "01")
    _PAPER_BASE_URL: str = "https://openapivts.koreainvestment.com:29443"

    # ── 실전투자 자격증명 ──────────────────────────────────────
    _REAL_APP_KEY: str = os.getenv("REAL_APP_KEY", "")
    _REAL_APP_SECRET: str = os.getenv("REAL_APP_SECRET", "")
    _REAL_CANO: str = os.getenv("REAL_CANO", "")
    _REAL_PRDT_CD: str = os.getenv("REAL_ACNT_PRDT_CD", "01")
    _REAL_BASE_URL: str = "https://openapi.koreainvestment.com:9443"

    # ── 공통 ──────────────────────────────────────────────────
    HTS_ID: str = os.getenv("KIS_HTS_ID", "")
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    BUY_AMOUNT: int = int(os.getenv("BUY_AMOUNT", "100000"))
    MAX_STOCKS: int = int(os.getenv("MAX_STOCKS", "5"))

    # ── 모드별 동적 프로퍼티 ──────────────────────────────────

    @property
    def is_paper(self) -> bool:
        return self.TRADE_MODE == "paper"

    @property
    def APP_KEY(self) -> str:
        return self._PAPER_APP_KEY if self.is_paper else self._REAL_APP_KEY

    @property
    def APP_SECRET(self) -> str:
        if self.is_paper:
            return self._PAPER_APP_SECRET
        return self._REAL_APP_SECRET

    @property
    def CANO(self) -> str:
        return self._PAPER_CANO if self.is_paper else self._REAL_CANO

    @property
    def ACNT_PRDT_CD(self) -> str:
        return self._PAPER_PRDT_CD if self.is_paper else self._REAL_PRDT_CD

    @property
    def BASE_URL(self) -> str:
        return self._PAPER_BASE_URL if self.is_paper else self._REAL_BASE_URL

    @property
    def account_prefix(self) -> str:
        """계좌번호 앞 8자리"""
        return self.CANO

    @property
    def account_suffix(self) -> str:
        """계좌번호 뒤 2자리"""
        return self.ACNT_PRDT_CD

    def validate(self) -> bool:
        """필수 설정값 존재 여부 확인"""
        missing = []
        if not self.APP_KEY:
            key_name = "PAPER_APP_KEY" if self.is_paper else "REAL_APP_KEY"
            missing.append(key_name)
        if not self.APP_SECRET:
            mode_prefix = "PAPER" if self.is_paper else "REAL"
            key_name = f"{mode_prefix}_APP_SECRET"
            missing.append(key_name)
        if not self.CANO:
            key_name = "PAPER_CANO" if self.is_paper else "REAL_CANO"
            missing.append(key_name)

        if missing:
            from utils.logger import log
            mode_str = "모의투자(paper)" if self.is_paper else "실전투자(real)"
            log.error(f"[CONFIG] {mode_str} 모드 변수 누락: {', '.join(missing)}")
            return False
        return True

    def describe(self) -> str:
        """현재 설정 요약 문자열"""
        mode = "[Paper] 모의투자" if self.is_paper else "[Real] 실전투자"
        return (
            f"{mode} | 계좌: {self.CANO}-{self.ACNT_PRDT_CD} | "
            f"KEY: {self.APP_KEY[:8]}... | URL: {self.BASE_URL}"
        )


settings = Settings()
