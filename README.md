# AutoStock — 주식 자동매매 프로그램

한국투자증권 Open API 기반 주식 자동매매 프로그램입니다.

## 📂 프로젝트 구조

```
autostock/
├── main.py                 # 메인 실행 파일
├── requirements.txt        # 패키지 의존성
├── .env.example            # 환경변수 템플릿
├── config/
│   └── settings.py         # 설정 관리
├── core/
│   ├── api.py              # 한국투자증권 API 클라이언트
│   ├── market.py           # 시세 조회 (현재가, 일봉)
│   ├── account.py          # 계좌 관리 (잔고, 보유종목)
│   └── order.py            # 주문 실행 (매수/매도)
├── strategy/
│   ├── base.py             # 전략 추상 클래스
│   ├── ma_cross.py         # 이동평균선 크로스 전략
│   └── volatility.py       # 변동성 돌파 전략
├── utils/
│   ├── logger.py           # 로깅
│   └── notifier.py         # 텔레그램 알림
└── dashboard/
    ├── app.py              # Flask 웹 대시보드
    └── templates/
        └── index.html      # 대시보드 UI
```

## 🚀 시작하기

### 1. 패키지 설치

```bash
pip install -r requirements.txt
```

### 2. 환경 변수 설정

```bash
copy .env.example .env
```

`.env` 파일을 열어 한국투자증권에서 발급받은 API 키를 입력합니다:

```
APP_KEY=실제_앱키
APP_SECRET=실제_시크릿키
ACCOUNT_NO=계좌번호8자리-뒤2자리
```

> ⚠️ 기본 설정은 **모의투자(paper)** 모드입니다. 실전 전환 전 충분히 테스트하세요.

### 3. 실행

```bash
# 이동평균 전략으로 자동매매 (10분 간격)
python main.py

# 변동성 돌파 전략
python main.py --strategy volatility

# 5분 간격으로 실행
python main.py --interval 5

# 1회만 실행 후 종료
python main.py --once

# 웹 대시보드 실행
python main.py --dashboard
```

## 📊 매매 전략

### 이동평균선 크로스 (기본)
- **매수**: 5일 이동평균선이 20일 이동평균선을 상향 돌파 (골든크로스)
- **매도**: 데드크로스 / 수익률 +5% 익절 / -3% 손절

### 변동성 돌파
- **매수**: 당일 시가 + (전일 고가-저가) × 0.5 돌파 시
- **매도**: 다음 거래일 시가에 전량 매도

## 🔐 한국투자증권 API 키 발급

1. [한국투자증권 홈페이지](https://www.koreainvestment.com) 접속
2. 로그인 → **트레이딩 → Open API → KIS Developers** 이동
3. **앱 등록** → APP KEY / APP SECRET 발급
4. 모의투자 신청 (실전 전 필수)
