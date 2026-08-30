# 🛒 N-Shop Macro Automation V1 (Phone Farm Distribution Node)

안드로이드 실단말기(5~60대) 폰팜 환경에서 **네이버 검색 결과 노출, 2단 스크린샷 아카이빙, 온디바이스 프로필 변조, WireGuard VPN 터널링 및 PM2 무중단 자동 재시작**을 지원하는 분산 매크로 클라이언트 시스템입니다.

---

## 🌟 2단계 원클릭 셋업 (Ultra-Simple 2-Step Setup)

새로운 클라이언트 PC 및 신규 서버 환경에서는 **오직 아래 2개의 스크립트만 순서대로 실행**하면 모든 셋업이 완료됩니다.

### 1️⃣ [1단계] 클라이언트 호스트 & PM2 무한 가동 셋업 (`pm2_setup.sh`)
호스트 PC에 필수 패키지(`adb`, `python3`, `nodejs`, `pm2`, `usbreset`)를 설치하고, 구글 드라이브에서 최신 APK를 자동 동기화한 뒤 **PM2에 데몬을 등록하여 PC 재부팅 시에도 자동으로 실행**되도록 설정합니다.

```bash
git clone https://github.com/service0427/nshop_macro_v1.git
cd nshop_macro_v1
chmod +x pm2_setup.sh device_init.sh
./pm2_setup.sh
```

---

### 2️⃣ [2단계] 안드로이드 단말기 일괄 초기화 (`device_init.sh`)
단말기들을 USB로 연결한 후 실행하면 **화면 잠금 해제(재부팅 시 잠김/꺼짐 방지), 필수 앱(네이버, WireGuard, ADBKeyboard) 자동 설치, 세로 화면 고정, 애니메이션 제거 및 권한 승인**을 원클릭으로 완료합니다.

```bash
# 연결된 모든 단말기 일괄 초기화
./device_init.sh

# 또는 특정 단말기만 초기화
./device_init.sh R3CR70SZ0JJ
```

---

## ⚙️ PM2 운영 및 관리 명령어 치트시트

| 작업 | 명령어 |
| :--- | :--- |
| **실시간 가동 로그 모니터링** | `pm2 logs nshop-macro-daemon` |
| **프로세스 및 CPU/메모리 상태** | `pm2 status` |
| **일시 정지 / 재개** | `pm2 stop nshop-macro-daemon` / `pm2 restart nshop-macro-daemon` |
| **데몬 완전 삭제** | `pm2 delete nshop-macro-daemon` |

---

## 📦 APK 패키지 및 구글 드라이브 연동 관리

* **필수 도구 (`essential_tools`)**: `ADBKeyboard`, `GPSEmulator`, `WireGuard`
* **네이버 앱 (`naver_app`)**: 최신 버전 (`v12.22.50`)

### 💡 추후 네이버 앱 신규 버전 패치 시:
새 네이버 앱 APK 압축본을 구글 드라이브에 업로드한 후, 파일 ID만 입력하면 신규 버전으로 자동 교체됩니다:
```bash
./scripts/download_apks.sh <신규_구글드라이브_FILE_ID>
./device_init.sh
```

---

## 📂 프로젝트 디렉터리 구조

```text
nshop_macro_v1/
├── pm2_setup.sh               # [1단계] 클라이언트 호스트 환경 & PM2 자동 셋업
├── device_init.sh             # [2단계] 안드로이드 단말기 잠금해제 & 앱 자동 셋업
├── ecosystem.config.js        # PM2 프로세스 정의 파일
├── daemon.py                  # 중앙 스케줄러 메인 진입점
├── requirements.txt           # Python 필수 패키지 목록
├── scripts/
│   └── download_apks.sh       # 구글 드라이브 APK 자동 다운로더
├── apks/                      # 오프라인 앱 설치 바이너리
│   ├── naver_app/             # 네이버 앱 Split APKs (v12.22.50)
│   ├── wireguard/             # WireGuard Split APKs
│   └── adbkeyboard/           # ADBKeyboard.apk
├── src/                       # 핵심 소스 코드 엔진
│   ├── config.py              # 전역 경로(동적 탐색) 및 설정
│   ├── modules/               # 신원 변조, WireGuard, UI 검사, 배터리 추적
│   ├── pipeline/              # 단말기 워커 파이프라인
│   └── scheduler/             # 디바이스 풀 & 라운드로빈 스케줄러
└── logs/                      # 자동 롤링 감사 로그 (최대 100개 유지)
    ├── allocate_history/      # 작업 할당 원본 JSON
    ├── release_history/       # 작업 결과 반납 영수증 JSON
    ├── target_screenshot/     # 타겟 크롭 및 상세페이지 랜딩 스크린샷
    └── battery_history/       # 배터리 충전/소모 추적 로그
```
