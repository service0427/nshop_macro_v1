# 🛒 N-Shop Macro Automation V1 (Production Phone Farm Node)

> **안드로이드 실단말기(11대+) 폰팜 환경에서 네이버 공식 모바일 앱(`com.nhn.android.search`)을 100% 단독 구동하여, 네이버 FDS를 완벽히 통과하는 순수 오가닉 유효타(트래픽/순위 점수)를 안정적으로 창출하는 분산 자동화 시스템입니다.**

---

## 🏛️ 시스템 핵심 아키텍처

```text
 ┌────────────────────────────────────────────────────────────────────────┐
 │   중앙 서버 (Central Controller & Token Vault) : 114.207.112.173:8000   │
 │   - MariaDB (nshop_api_v1) : 상품 DB(nshop_list), 작업 관리(tasks)      │
 │   - nshop-pool-daemon     : 1,200초(20분) 숙성 NNB/BUC 토큰 실시간 채굴  │
 │   - nshop-api             : REST API (/api/v1/task/assign, /report)   │
 └────────────────────────────────────┬───────────────────────────────────┘
                                      │ HTTP REST API (Token & Task Lease)
                                      ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │   로컬 호스트 노드 (Phone Farm Node) : Ubuntu Linux (Host PC)            │
 │   - run.py (통합 진입점)   : api, batch, test, server, check 모드 지원  │
 │   - src/client            : CDP 핀포인트 터치, Zygote Root Hooking     │
 │   - src/manager           : 중앙 서버 SSH 직접 제어 및 무중단 배포 도구 │
 │   - src/api_server        : 원격 중앙 서버 소스코드 로컬 미러 (Git 추적)│
 └────────────────────────────────────┬───────────────────────────────────┘
                                      │ USB 3.0 Hub / ADB & CDP Protocol
                                      ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │   안드로이드 실단말기 팜 (Galaxy Z Flip 3 등 11대+ 물리 기기)           │
 │   - Zygote Root Hooking   : Frida 기반 OS/Java 레벨 루팅 및 지문 은닉   │
 │   - 9대 고유식별자 무결성  : SSAID, NAPP_DI, NNB, BUC, ADID, GPS 등     │
 │   - 네이버 공식 모바일 앱 : 100% 단독 실행, 순수 오가닉 검색 및 랜딩      │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## 🚫 개발 및 운영 절대 원칙

1. **[절대 철칙 1] 광고(CPC / 파워링크 / 쇼핑검색광고) 분석 및 클릭 절대 금지**
   - 본 매크로는 **오직 순수 오가닉(일반 스마트스토어 / 가격비교 카탈로그) 상품만을 타겟팅**합니다.
   - 검색광고 분석이나 광고 클릭 제안은 일체 배제합니다.
2. **[절대 철칙 2] 네이버 공식 앱(`com.nhn.android.search`) 100% 단독 구동 원칙**
   - 크롬, 웨일, 파이어폭스, 삼성인터넷 등 외부 브라우저 대체는 영구 금지합니다.
   - 모든 네비게이션과 클릭은 네이버 앱 내부에서 해결합니다.
3. **[원칙 3] MITM 프록시 영구 폐기 및 CDP + Frida Zygote 정면 돌파**
   - 네트워크를 가로채는 MITM 프록시는 일체 사용하지 않으며, 단말기 로컬 Chrome DevTools Protocol(CDP)과 Zygote 소프트 리셋으로 100% 순수 패킷을 유지합니다.
4. **[원칙 4] 1회용 완전 클린 기동 (Round-Robin 프로필 복원 금지)**
   - 매 타격 시 `pm clear` 및 고유 식별자 전면 교체를 수행하며 과거 세션을 임의로 복원하지 않습니다.

---

## 🌟 신규 서버 및 단말기 4단계 셋업 워크플로우

새로운 클라이언트 PC 및 신규 단말기 투입 시 **`install/` 디렉터리의 01~04 스크립트를 번호 순서대로 실행**합니다:

```text
 🖥️ [01단계] OS 최적화  ➔ ./install/01_install_os.sh   (SSH 키, 타임존, 절전 방지, USB 상시전원, 커널 튜닝)
 ⚙️ [02단계] PM2 서비스 ➔ ./install/02_pm2_setup.sh    (Node/PM2, Python 의존성 설치, 무한가동 등록)
 📱 [03단계] 단말기 세팅 ➔ ./install/03_device_init.sh  (화면 잠금 해제, 상시 켜짐, Magisk DenyList, BSSID 방어)
 🔍 [04단계] 종합 진단  ➔ ./install/04_device_check.sh (배터리, 화면, 패키지, 무선 스캔, 네이버앱 100% 전수 점검)
```

### 1️⃣ [01단계] Host OS 최적화
```bash
./install/01_install_os.sh
```
* Sudo 비밀번호 생략(NOPASSWD) 및 SSH 키 등록
* Asia/Seoul 타임존 및 NTP 동기화
* 시스템 절전/슬립(`sleep.target`, `suspend.target`) 마스킹
* USB 자동 절전(Autosuspend) 영구 비활성화 (단말기 ADB 연결 끊김 방지)
* 커널 네트워크/메모리 및 ulimit(65536) 최적화

### 2️⃣ [02단계] PM2 및 의존성 셋업
```bash
./install/02_pm2_setup.sh
```
* Node.js 20.x 및 PM2 설치
* Python 의존성(`requirements.txt`) 일괄 설치
* PM2 부팅 시 자동 시작(Systemd startup) 등록

### 3️⃣ [03단계] 단말기 일괄 초기화 & 안티디텍션 패치
단말기들을 USB 허브에 연결하고 화면에서 `[항상 허용]`을 터치한 후 실행:
```bash
# 연결된 모든 단말기 일괄 초기화
./install/03_device_init.sh

# 또는 특정 단말기만 개별 초기화
./install/03_device_init.sh R3CR70K98XZ
```
* 화면 상시 켜짐(`stay_on_while_plugged_in 7`) 및 잠금 해제
* ADB 디버깅 영구 인증(`adb_authorization_timeout 0`) 및 PC 키 저장
* 60Hz 고정, 다크 모드, 세로 화면 고정, 애니메이션 제거, 고속 충전 개방
* Magisk DenyList 활성화 (`com.nhn.android.search`, `com.google.android.gms`)
* 네이버 앱 위치 권한 박탈 및 AppOps ignore (작업실 BSSID 누출 차단)
* Bluetooth/Wi-Fi/BLE 백그라운드 탐색 0으로 비활성화

### 4️⃣ [04단계] 단말기 종합 정밀 진단
```bash
# 전체 단말기 종합 진단표 출력
python3 run.py check

# 또는 특정 단말기만 점검
python3 run.py check R3CR70K98XZ
```
* 연결된 모든 단말기의 하드웨어, 배터리, 잠금상태, 네이버앱 무결성, DenyList 적용 여부를 전수 점검하여 표로 출력합니다:
```text
====================================================================================================================
 📊 [Phone Farm 전체 단말기 종합 진단 결과표 (04_device_check.sh)]
====================================================================================================================
| 단말기 시리얼  | 모델명           | 배터리   | 네이버 공식앱 (100%)   | 구글 로그인    | 온보딩 종합 판정     |
|---------------|------------------|----------|------------------------|----------------|----------------------|
| R3CR70K98XZ   | SM-F711N         | 100%     | 🟢 v12.23.81         | 🟢정상     | 🟢 완벽 (즉시 투입 가능) |
====================================================================================================================
```

---

## 🎮 단일 통합 진입점 (`run.py`) 실행 가이드

모든 운영 및 테스트 작업은 루트의 단일 진입점 `run.py`로 통합 실행됩니다:

### (1) 중앙 API 기반 단일 작업 실행 (`api` 모드)
중앙 API에서 작업을 즉시 할당받아 지정 단말기에서 1회 타격을 실행하고 결과를 DB에 자동 보고합니다:
```bash
# 특정 단말기로 1회 API 작업 실행
python3 run.py api --device R3CR70K98XZ --dwell 15

# 또는 유휴 단말기 자동 선택
python3 run.py api --dwell 15
```

### (2) 다중 단말기 분산 배치 스케줄러 (`batch` 모드)
연결된 모든 단말기(11대+)를 대상으로 스토어 쿨다운 및 버스트 규칙을 준수하며 연속 자율 가동합니다:
```bash
# 전체 단말기 대상 연속 컨베이어 루프 가동
python3 run.py batch --max-loops 50 --concurrency 2 --dwell 15
```

### (3) 수동 개별 타겟 테스트 (`test` 모드)
중앙 API와 독립적으로 특정 키워드/상품에 대해 즉시 단말기 테스트를 수행합니다:
```bash
# 1. 단독 상품 테스트
python3 run.py test --keyword "보관백" --nvmid "41733443548" --device R3CR70K98XZ

# 2. 가격비교 카탈로그 상품 테스트
python3 run.py test --keyword "보관백" --nvmid "83750937930" --compare-id "41733443548" --store "블루라팡"
```

### (4) 중앙 API 서버 원격 관제 및 무중단 배포 (`server` 모드)
클라이언트 터미널에서 중앙 API 서버(`114.207.112.173`)를 SSH로 직접 관제하고 수정된 코드를 무중단 배포합니다:
```bash
# 1. 원격 서버 PM2 및 MariaDB 상태 조회
python3 run.py server status

# 2. 실시간 API 서버 로그 조회
python3 run.py server logs -n 50

# 3. 원격 PM2 nshop-api 리로드
python3 run.py server reload

# 4. MariaDB 쿼리 실행
python3 run.py server db "SELECT task_id, keyword, store_name, status FROM tasks ORDER BY task_id DESC LIMIT 5;"

# 5. 로컬 수정 파일 원격 서버로 배포 (SFTP 전송 + 문법검사 + PM2 리로드 자동 수행)
python3 run.py server push services/task_service.py

# 6. 원격 최신 파일 로컬 미러(src/api_server/)로 가져오기
python3 run.py server pull services/task_service.py
```

### (5) 11대 화면 실시간 바둑판 관제 (`start_scrcpy_grid.sh`)
연결된 모든 단말기 화면을 모니터에 그리드 형태로 띄워 실시간 모니터링합니다:
```bash
./install/start_scrcpy_grid.sh
```

---

## 🛡️ 9대 고유식별자 무결성 감사 기준

매 타격 기동 시, Zygote 수준에서 아래 9개 식별자가 직전 회차와 100% 독립적인지 전수 감사를 수행하며, 단 1건이라도 동일값이 검출되면 즉시 안전 차단합니다:

1. **SSAID (Android ID)**: Android OS 시스템 식별자 (64-bit Hex)
2. **NAPP_DI**: 네이버 공식 앱 기기 무결성 쿠키
3. **NNB**: 네이버 공용 풀에서 1,200초 이상 숙성된 고유 식별 토큰
4. **BUC**: HMAC-SHA256 세션 위변조 방지 서명
5. **DA_DD (Google ADID)**: Google Advertising ID (UUID)
6. **DA_DV (AppSetId)**: Google Developer AppSet ID (UUID)
7. **GPS 가상 위치**: 실사용자 행정동 기준 랜덤 좌표 및 직전 위치 대비 이동거리 검증
8. **Google 계정**: 단말기 연동 실제 계정
9. **공인 Egress IP**: LTE 라우터 공인 IP (당일 1회 및 3시간 쿨다운 엄수)

---

## 📂 최종 디렉터리 구조 (Clean Modular Model)

```text
nshop_macro_v1/
├── api/                          # 🌐 [중앙 API 서버 개발 전용 폴더 (원격 114.207.112.173 미러 & 개발)]
│   ├── app.py                    # Flask API 메인 엔드포인트
│   ├── config.py                 # DB 및 토큰 풀 설정
│   ├── database.py               # MariaDB 커넥션 관리
│   ├── daemon_pool_maintainer.py # NNB 패킷 채굴/숙성 데몬
│   ├── ecosystem.config.js       # PM2 프로세스 정의
│   ├── deploy.py                 # 원격 서버 무중단 배포/동기화 도구 (push/pull/reload/status)
│   ├── services/                 # task_service.py, nnb_service.py
│   ├── routes/                   # task.py, nnb.py, keyword.py
│   ├── core/                     # 토큰 채굴 및 패킷 파서
│   └── utils/                    # 헬퍼 유틸리티
│
├── src/                          # 📱 [폰팜 매크로 엔진 소스코드 전용]
│   ├── core/                     # API 통신, NNB 프로바이더, 디바이스 선정
│   ├── device/                   # ADB 제어, 수술적 초기화, 9대 식별자 감사
│   ├── browser/                  # CDP 클라이언트, Frida Runner, Zygote Hook 번들
│   ├── pipeline/                 # 메인 10단계 컨베이어 파이프라인 (conveyor_executor)
│   └── assets/                   # cdp_clean_agent.js
│
├── install/                      # ⚙️ [호스트 OS 및 단말기 팜 셋업 스크립트 & 바이너리]
│   ├── 01_install_os.sh          # [01단계] Linux OS 서버 최적화
│   ├── 02_pm2_setup.sh           # [02단계] PM2 무한가동 서비스 등록
│   ├── 03_device_init.sh         # [03단계] 단말기 팜 일괄 초기화 & 안티디텍션
│   ├── 04_device_check.sh        # [04단계] 단말기 종합 정밀 건강 진단기
│   ├── start_scrcpy_grid.sh      # 단말기 화면 그리드 바둑판 관제 스크립트
│   ├── apks/                     # 오프라인 앱 설치 바이너리 (.gitignore)
│   └── bin/                      # frida-server 바이너리 (.gitignore)
│
├── config/                       # 🔧 [설정 관리]
│   ├── settings.py               # 전역 경로 및 상수 설정
│   └── .env.example              # 중앙 API 접속 및 환경변수 템플릿
│
├── docs/                         # 📚 [통합 기술 및 운영 문서]
│   ├── NEW_DEVICE_SETUP.md       # 신규 단말기 온보딩 및 하드웨어 셋업 가이드
│   └── API_SERVER_DEVELOPMENT.md # 중앙 API 서버 아키텍처 및 REST 명세서
│
├── logs/                         # 📋 [런타임 로그 & 증빙 캡처 (.gitignore)]
│   ├── captures/                 # 타격 전/후 증빙 스크린샷 (*.png)
│   └── data/                     # 실행 이력 json
│
├── backups/                      # 🗄️ [레거시 아카이브 & 대용량 덤프 (.gitignore)]
│
├── run.py                        # 🚀 [단일 통합 실행 진입점 (api / batch / test / server / check)]
├── requirements.txt              # Python 필수 라이브러리 목록
├── README.md                     # 본 종합 기술 문서
├── AGENTS.md / GEMINI.md         # AI 에이전트 절대 철칙 및 운영 가이드라인
└── .gitignore                    # Git 형상관리 예외 규칙
```
