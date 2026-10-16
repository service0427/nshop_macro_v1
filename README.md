# 🛒 N-Shop Macro Automation V1 (20-Device Parallel Phone Farm Node)

> **안드로이드 실단말기 20대 물리 폰팜 환경에서 네이버 공식 모바일 앱(`com.nhn.android.search`)을 100% 단독 구동하여, 네이버 FDS를 완벽히 통과하는 순수 오가닉 유효타(트래픽/순위 점수)를 안정적으로 창출하는 고속 병렬 자동화 시스템입니다.**

---

## 🏛️ 시스템 핵심 아키텍처 (Dual-Network & Parallel Multi-Process)

```text
 ┌────────────────────────────────────────────────────────────────────────┐
 │   중앙 서버 (Central Controller & Token Vault) : 114.207.112.173:8000   │
 │   - MariaDB (nshop_api_v1) : 상품 DB(nshop_list), 작업 관리(tasks)      │
 │   - nshop-pool-daemon     : 1,200초(20분) 숙성 NNB/BUC 토큰 실시간 채굴  │
 │   - nshop-api             : REST API (/api/v1/allocate, /report)       │
 └────────────────────────────────────┬───────────────────────────────────┘
                                      │ HTTP REST API (Token & Task Lease)
                                      ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │   로컬 호스트 노드 (Phone Farm Master Host) : Ubuntu Linux (Host PC)     │
 │                                                                        │
 │   [마스터 통합 러너] run.py (단일 진입점, 직관적 플래그 시스템)         │
 │   • 20개 독립 OS 프로세스 (독립 GIL, 독립 메모리, 전용 이벤트 루프)      │
 │   • 듀얼 네트워크 컨트롤러 (NetworkController)                         │
 │     ├─ [모드 1] LTE 동글 모드 (--net-mode lte, 포트 31411)            │
 │     └─ [모드 2] MikroTik WireGuard 유선 모드 (--net-mode wg, 포트 31412)│
 │   • 정책 라우팅 격리 (Table 51820) : PC 메인 유선망(enp42s0) 100% 보존  │
 └────────────────────────────────────┬───────────────────────────────────┘
                                      │ USB 3.0 Hub (gnirehtet 역테더링 중계)
                                      ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │   안드로이드 실단말기 팜 (Galaxy Z Flip 3 등 20대 물리 기기 동시 타격)   │
 │   • Wi-Fi 0% OFF (전원 USB 역테더링으로 고유 공인 IP 통신 관통)        │
 │   • Zygote Root Hooking   : Frida 기반 OS/Java 레벨 루팅 및 지문 은닉   │
 │   • 9대 고유식별자 무결성  : SSAID, NAPP_DI, NNB, BUC, ADID, GPS 등     │
 │   • 네이버 공식 모바일 앱 : 100% 단독 실행, 순수 오가닉 검색 및 랜딩      │
 │   • 개별 단말기 60초 하드 타임아웃 & 회차당 최소 60초 완충 보장         │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## 🚫 개발 및 운영 절대 원칙 (Core Directives)

1. **[절대 철칙 1] 광고(CPC / 파워링크 / 쇼핑검색광고) 분석 및 클릭 절대 금지**
   - 본 매크로는 **오직 순수 오가닉(일반 스마트스토어 / 가격비교 카탈로그) 상품만을 타겟팅**합니다.
   - 검색광고 분석이나 광고 클릭 제안은 시스템 존재 목적을 부정하는 치명적 오류입니다.
2. **[절대 철칙 2] 네이버 공식 앱(`com.nhn.android.search`) 100% 단독 구동 원칙**
   - 크롬, 웨일, 파이어폭스, 삼성인터넷 등 외부 브라우저 대체는 영구 금지합니다.
   - 모든 네비게이션과 클릭은 네이버 앱 내부에서 해결합니다.
3. **[원칙 3] 1회용 완전 클린 기동 (Round-Robin 프로필 복원 금지)**
   - 매 타격 시 `pm clear` 및 고유 식별자 전면 교체를 수행하며 과거 세션을 임의로 복원하지 않습니다.
4. **[원칙 4] PC 메인 유선 네트워크 무결성 보존**
   - WireGuard 터널링 시 기본 라우팅 테이블(Main Table)을 절대 오염시키지 않으며, `Table 51820` 마킹 정책 라우팅으로 분리 격리하여 SSH 및 중앙 API 통신 끊김 0%를 유지합니다.

---

## 🚀 마스터 통합 엔트리포인트 (`run.py`) CLI 완전 가이드

더 이상 여러 스크립트를 번갈아 실행할 필요 없이, **오직 `run.py` 단일 실행 파일에 직관적인 플래그를 조합**하여 모든 테스트와 실전 타격을 제어합니다.

```bash
python3 run.py [옵션 플래그...]
```

### 1️⃣ 네트워크 모드 설정 (Network & IP)

| 플래그 | 인자 | 설명 | 기본값 |
| :--- | :--- | :--- | :--- |
| `--net-mode` | `lte` \| `wg` | 네트워크 모드 선택 (`lte`: 화웨이 LTE 동글, `wg`: 원격 MikroTik WireGuard) | `lte` |
| `--router-num` | 문자열 (예: `001`) | WireGuard 모드 시 타겟 MikroTik 라우터 번호 (`001`: 파주, `002`: 계산, `004`: 청라 등) | `001` |
| `--router-list` | 콤마 구분 (예: `001,002,004`) | WireGuard 모드 시 회차별로 원격지 라우터를 자동 순환 타격 | `None` |
| `--no-toggle` | (플래그) | 회차 간 공인 IP 토글을 수행하지 않고 현재 IP 그대로 유지 | `False` |
| `--min-cycle-dur` | 초 (실수) | 회차당 최소 완충 소요시간 (초). 타격이 일찍 끝나도 지정 초를 채우고 안전 토글 | `60.0` |

### 2️⃣ 스케줄 및 종료 조건 (Schedule & Termination)

| 플래그 | 인자 | 설명 | 기본값 |
| :--- | :--- | :--- | :--- |
| `--until` | `HH:MM` (예: `23:50`) | 당일 목표 시각에 도달하면 현재 회차 마감 후 안전하게 자동 종료 | `None` |
| `--cycles` | 정수 (예: `10`) | 지정한 횟수만큼 사이클을 반복 실행한 후 자동 종료 | `None` |
| `--once` | (플래그) | 단 1회 사이클(20대 동시 타격)만 즉시 실행하고 종료 (`--cycles 1`과 동일) | `False` |
| `--interval` | 초 (정수) | 토글 후 다음 회차 시작 전 추가 대기 시간 (초) | `5` |

### 3️⃣ 작업 및 타겟 파라미터 수동 오버라이딩 (Task Overrides)

중앙 API에서 실시간 할당받는 것이 기본 동작이며, 아래 플래그를 입력하면 **입력된 파라미터가 최우선으로 강제 덮어쓰기**됩니다:

| 플래그 | 인자 | 설명 |
| :--- | :--- | :--- |
| `--keyword` | 문자열 | 검색 키워드 강제 지정 (예: `"보관백"`, `"실리콘 수영가방..."`) |
| `--nvmid` | 문자열 | 타겟 상품의 `nv_mid` 강제 지정 (예: `"41733443548"`) |
| `--compare-id` | 문자열 | 가격비교 카탈로그 매칭용 `compare_id` 강제 지정 |
| `--store` | 문자열 | 스토어명 / 몰명 강제 지정 (예: `"블루라팡"`, `"키지다이브"`) |
| `--dwell` | 정수 | 상세페이지 체류 시간 (초, 기본: `10`) |
| `--scroll-mode` | `real_swipe` \| `js` \| `none` | 상세페이지 스크롤 모드 (기본: `real_swipe`) |
| `--timeout` | 초 (실수) | 개별 단말기 하드 타임아웃 제한 (초, 기본: `60.0`) |
| `--no-wake` | (플래그) | 단말기 화면 언락 및 펼침 절차 생략 |
| `--task-id` | 정수/문자열 | 특정 Task ID 수동 강제 지정 |
| `--nnb` / `--buc` | 문자열 | 특정 NNB / BUC 쿠키 토큰 수동 지정 |

### 4️⃣ 단말기 대상 제어 (Device Target)

| 플래그 | 인자 | 설명 | 기본값 |
| :--- | :--- | :--- | :--- |
| `-c`, `--count` | 정수 | 온라인 단말기 중 투입할 대수 | `20` |
| `-d`, `--device` | 시리얼 목록 | 특정 단말기만 지정 (단일 또는 콤마 구분: `R3CR70FFFEK,R3CR70K98XZ`) | 전체 풀 |

### 5️⃣ 보조 진단 및 유틸리티 명령 (Diagnostics & Utilities)

| 플래그 | 설명 |
| :--- | :--- |
| `--check` | 20대 단말기 연결 상태 진단표 출력 후 즉시 종료 |
| `--battery` | 20대 단말기 배터리 잔량 및 충전 상태 일괄 점검 후 즉시 종료 |
| `--ip-only` | 현재 설정된 네트워크 모드(LTE 또는 WG)의 실측 Egress 공인 IP만 확인 후 종료 |
| `--wake` | 20대 단말기 화면 언락 및 펼침 상태 동기화만 단독 실행 후 종료 |
| `--clear-app` | 20대 단말기 네이버 공식 앱 force-stop 일괄 종료만 수행 후 종료 |
| `--wifi-off` | 20대 단말기 Wi-Fi 일괄 강제 비활성화(OFF) 후 종료 (순수 USB 테더링 보장) |
| `--grid` | 20대 단말기 실시간 화면 그리드 관제(scrcpy) 기동 |
| `--dry-run` | 실제 단말기 클릭 없이 네트워크 점검 및 중앙 API 작업 할당 계획표만 검증 후 종료 |

---

## 💡 실전 명령어 치트시트 (Cheat Sheet)

### 📌 1. 진단 및 상태 점검
```bash
# 20대 단말기 연결 상태 확인
python3 run.py --check

# 20대 단말기 배터리 잔량 및 충전 상태 확인
python3 run.py --battery

# 현재 공인 IP 확인 (LTE)
python3 run.py --ip-only

# 현재 공인 IP 확인 (파주 MikroTik WireGuard)
python3 run.py --net-mode wg --router-num 001 --ip-only

# 모의 실행 검증 (타격 없이 네트워크 및 API 작업 배정 계획 확인)
python3 run.py --dry-run
python3 run.py --net-mode wg --router-num 001 --dry-run
```

### 📌 2. 단일 회차 테스트 (`--once`)
```bash
# [API 실시간 할당] LTE 동글로 20대 전원 1회 즉시 실행
python3 run.py --net-mode lte --once

# [API 실시간 할당] MikroTik 파주 001번 유선망으로 20대 1회 즉시 실행
python3 run.py --net-mode wg --router-num 001 --once

# [수동 오버라이딩] 특정 상품을 20대 전원으로 1회 즉시 타격
python3 run.py --keyword "보관백" --nvmid "41733443548" --store "블루라팡" --once

# [단일 기기 점검] 특정 단말기 1대만 1회 즉시 실행
python3 run.py -d R3CR70FFFEK --once
```

### 📌 3. 반복 사이클 실행 (`--cycles`)
```bash
# LTE 동글로 10회 연속 사이클 타격 (회차마다 4초 고속 토글 + 60초 완충 보장)
python3 run.py --net-mode lte --cycles 10

# MikroTik 파주 001번 유선망으로 3회 사이클 타격 (회차마다 원격 라우터 5초 토글)
python3 run.py --net-mode wg --router-num 001 --cycles 3

# [전국 라우터 자동 순환] 파주(001) -> 계산(002) -> 청라(004) 유선 IP 순환 타격
python3 run.py --net-mode wg --router-list 001,002,004 --cycles 6
```

### 📌 4. 목표 시각 자동 마감 실전 운영 (`--until`)
```bash
# 오늘 밤 23:50까지 무중단 자동 순환 가동 (시각 도달 시 안전 마감)
python3 run.py --net-mode lte --until 23:50

# 체류시간 15초 설정으로 퇴근 전 18:30까지 구동
python3 run.py --net-mode wg --router-num 001 --dwell 15 --until 18:30
```

### 📌 5. 단말기 제어 및 실시간 관제
```bash
# 20대 단말기 화면 언락 및 펼침
python3 run.py --wake

# 20대 단말기 네이버 앱 일괄 강제 종료
python3 run.py --clear-app

# 20대 단말기 Wi-Fi 일괄 강제 OFF
python3 run.py --wifi-off

# 20대 단말기 실시간 화면 그리드(scrcpy 바둑판) 관제
python3 run.py --grid
```

---

## 🛡️ 핵심 안전장치 & FDS 방어 기술

1. **개별 단말기 60초 하드 타임아웃 (`--timeout 60`)**:
   - 어떤 단말기에서 네이버 앱 무한 로딩이나 팝업 걸림이 발생하더라도, 60초 초과 시 해당 기기 앱을 강제 종료(`am force-stop`)하여 전체 배치의 대기 지연을 원천 차단합니다.
2. **회차당 최소 60초 완충 보장 (`--min-cycle-dur 60`)**:
   - 20대 단말기 타격이 30초 만에 조기 종료되더라도, 네트워크 안정화 및 네이버 FDS 체류 시간 비콘 완결성을 위해 잔여 시간(예: 30초)을 안전하게 대기한 후 토글합니다.
3. **정책 라우팅 기반 PC 메인망 100% 보존**:
   - MikroTik WireGuard 터널링 시 PC 메인 인터페이스(`enp42s0`, IP: 121.142.9.48)를 오염시키지 않으며, 개발자 SSH 연결 및 중앙 API 통신이 100% 끊김 없이 유지됩니다.
4. **9대 고유식별자 1회용 무결성 감사**:
   - 매 타격 시 `SSAID`, `NAPP_DI`, `NNB`, `BUC`, `ADID`, `AppSetId`, `GPS`, `Google계정`, `공인 Egress IP`의 독립성을 엄격히 유지합니다.

---

## 📂 프로젝트 디렉터리 구조

```text
nshop_macro_v1/
├── run.py                        # 🚀 [마스터 단일 통합 진입점 (Multi-Processing Runner)]
├── src/                          # 📱 [폰팜 매크로 엔진 소스코드]
│   ├── core/                     # API 통신 (api_client.py), NNB 프로바이더
│   ├── device/                   # network_controller.py (LTE/WG 통합 제어), device_selector.py
│   ├── browser/                  # CDP 클라이언트, Frida Runner, Zygote Hook 번들
│   └── pipeline/                 # 10단계 컨베이어 파이프라인 (conveyor_executor.py)
│
├── install/                      # ⚙️ [호스트 OS 및 단말기 팜 셋업 스크립트]
│   ├── 01_install_os.sh          # [01단계] Linux OS 서버 최적화
│   ├── 02_pm2_setup.sh           # [02단계] PM2 서비스 등록
│   ├── 03_device_init.sh         # [03단계] 단말기 팜 일괄 초기화 & 안티디텍션
│   ├── 04_device_check.sh        # [04단계] 단말기 종합 정밀 건강 진단기
│   └── start_scrcpy_grid.sh      # 20대 단말기 화면 그리드 바둑판 관제 스크립트
│
├── config/                       # 🔧 [설정 관리]
│   └── settings.py               # 중앙 API URL 및 전역 경로 설정
│
├── logs/                         # 📋 [런타임 로그 & 증빙 캡처]
│   ├── captures/                 # 타격 전/후 증빙 스크린샷 (*.png)
│   └── data/                     # 실행 이력 json 리포트
│
├── AGENTS.md / GEMINI.md         # AI 에이전트 절대 철칙 및 운영 가이드라인
├── README.md                     # 본 종합 가이드 문서
└── requirements.txt              # Python 필수 라이브러리 목록
```

---

## 📌 향후 테스트 및 운영 원칙
- **임시 스크립트 생성 금지**: 앞으로의 모든 테스트, 벤치마크, 검증 요구사항은 개별 스크립트를 생성하지 않고 **오직 `run.py`의 플래그 조합**으로 수행됩니다.
- 새로운 옵션이나 파라미터가 필요한 경우 `run.py`의 인자 파서에 표준 플래그로 추가하여 단일 진입점의 완성도를 지속 유지합니다.
