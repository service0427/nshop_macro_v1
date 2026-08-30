# 🛒 N-Shop Macro Automation V1 (Phone Farm Distribution Node)

안드로이드 실단말기(5~60대) 폰팜 환경에서 **네이버 검색 결과 노출, 2단 스크린샷 아카이빙, 온디바이스 프로필 변조, WireGuard VPN 터널링 및 PM2 무중단 자동 재시작**을 지원하는 분산 매크로 클라이언트 시스템입니다.

---

## 🌟 신규 서버 4단계 원클릭 셋업 & 관제 체계 (Numbered Setup & Audit)

새로운 클라이언트 PC 및 신규 서버 환경에서는 **아래 01~04 스크립트를 번호 순서대로 실행**하면 365일 무한가동 및 단말기 종합 진단이 완료됩니다.

```text
 🖥️ [01단계] OS 최적화  ➔ ./01_install_os.sh   (SSH 키, 타임존, 절전 방지, USB 상시전원, 커널 튜닝)
 ⚙️ [02단계] PM2 서비스 ➔ ./02_pm2_setup.sh    (Node/PM2, Python 의존성, 구글드라이브 APK, 자동가동)
 📱 [03단계] 단말기 세팅 ➔ ./03_device_init.sh  (화면 잠금 해제, 상시 켜짐, APK 자동 설치, 권한)
 🔍 [04단계] 종합 진단  ➔ ./04_device_check.sh (배터리 수명, 전압, 온도, 잠금해제, 패키지, 네트워크 점검)
```

---

### 1️⃣ [01단계] 365일 무한가동 Linux Server OS 셋업 (`./01_install_os.sh`)
* **Sudo 비밀번호 생략 (NOPASSWD)** 구성
* **SSH 공개키 자동 등록** (집/가게 원격 접속용) 및 PubkeyAuthentication 활성화
* **한국 표준시 (Asia/Seoul)** 타임존 및 NTP 시간 동기화
* **시스템 절전/슬립 완전 차단** (`sleep.target`, `suspend.target` 마스킹)
* **USB 자동 절전(Autosuspend) 영구 비활성화** (단말기 ADB 끊김 원천 차단)
* **커널 네트워크/메모리 및 ulimit(65536)** 최적화
* **시스템 필수 패키지 & usbreset** 일괄 설치

```bash
git clone https://github.com/service0427/nshop_macro_v1.git
cd nshop_macro_v1
chmod +x 01_*.sh 02_*.sh 03_*.sh 04_*.sh
./01_install_os.sh
```

---

### 2️⃣ [02단계] PM2 무한가동 서비스 등록 및 APK 동기화 (`./02_pm2_setup.sh`)
* **Node.js 20.x & PM2** 글로벌 설치
* **Python 라이브러리** (`requirements.txt`, `gdown`) 자동 설치
* **구글 드라이브 APK 패키지** (`essential_tools`, `naver_app v12.22.50`) 자동 다운로드 및 무결성 검증
* **PM2 데몬(`daemon.py`) 등록** 및 **PC 재부팅 시 Systemd 자동 시작** 설정

```bash
./02_pm2_setup.sh
```

---

### 3️⃣ [03단계] 안드로이드 단말기 일괄 초기화 (`./03_device_init.sh`)
단말기들을 USB 허브에 연결한 후 실행:
* **재부팅 시 화면 꺼짐/잠김 방지** (`stay_on_while_plugged_in 7`, `lockscreen.disabled 1`)
* **세로 화면 고정**, 오터치 방지 해제, UI 애니메이션 3종 제거
* **필수 앱 자동 설치**: 네이버 앱(Split APKs), WireGuard(Split APKs), ADBKeyboard, GPSEmulator
* **ADBKeyboard 기본 입력기(IME) 등록** 및 권한 자동 승인

```bash
# 연결된 모든 단말기 일괄 초기화
./03_device_init.sh

# 또는 특정 단말기만 초기화
./03_device_init.sh R3CR70SZ0JJ
```

---

### 4️⃣ [04단계] 단말기 종합 정밀 진단 시스템 (`./04_device_check.sh`)
현재 연결된 모든 단말기의 **하드웨어 사양, 배터리 수명(ASOC), 누적 충방전 사이클, 전압/온도, 화면 잠금 상태, 필수 패키지 버전, 내부/공인 IP**를 원클릭으로 전수 점검하고 종합 판정표를 출력합니다:

```bash
./04_device_check.sh
```

---

## ⚙️ PM2 운영 및 모니터링 명령어 치트시트

| 작업 | 명령어 |
| :--- | :--- |
| **실시간 가동 로그 모니터링** | `pm2 logs nshop-macro-daemon` |
| **프로세스 및 CPU/메모리 상태** | `pm2 status` |
| **일시 중지 / 재개** | `pm2 stop nshop-macro-daemon` / `pm2 restart nshop-macro-daemon` |
| **단말기 종합 건강 진단** | `./04_device_check.sh` |

---

## 📂 프로젝트 디렉터리 구조

```text
nshop_macro_v1/
├── 01_install_os.sh           # [01단계] 365일 무한가동 Server OS 튜닝 & 패키지 설치
├── 02_pm2_setup.sh            # [02단계] PM2 무한가동 서비스 등록 & APK 동기화
├── 03_device_init.sh          # [03단계] 안드로이드 단말기 잠금해제 & APK 자동 배포
├── 04_device_check.sh         # [04단계] 단말기 하드웨어/배터리/네트워크 종합 진단기
├── ecosystem.config.js        # PM2 프로세스 정의 파일
├── daemon.py                  # 중앙 스케줄러 메인 진입점
├── requirements.txt           # Python 필수 패키지 목록
├── scripts/
│   ├── download_apks.sh       # 구글 드라이브 APK 자동 다운로더
│   ├── check_battery_health.py# 배터리 ASOC 수명 및 사이클 진단 도구
│   └── monitor_charging.py    # 20분 분 단위 배터리 벤치마크 도구
├── dev_tools/                 # 개발 및 연구용 도구 (Frida, MITM dumper)
├── apks/                      # 오프라인 앱 설치 바이너리 관리 디렉터리
├── src/                       # 핵심 소스 코드 엔진
└── logs/                      # 자동 롤링 감사 로그 (최대 100개 유지)
```
