# 📱 신규 단말기(Phone Farm) 온보딩 및 자동화 셋업 가이드

본 문서는 N-Shop Macro Phone Farm 노드에 **새로운 안드로이드 공기계(예: Galaxy Z Flip 3 5G 등)를 신규 투입할 때 수행하는 표준 온보딩 절차**를 정의합니다.

---

## 🚀 1. 빠른 시작 (원클릭 셋업)

신규 단말기를 USB 허브에 연결하고 화면에서 `[이 컴퓨터에서 항상 허용]`을 터치한 후, 아래 명령어를 실행하면 90% 이상의 설정이 전자동으로 적용됩니다:

```bash
# 1. 단말기 일괄 초기화 & 안티디텍션 패치
./03_device_init.sh [단말기_시리얼]

# 2. 종합 정밀 진단 및 온보딩 판정 확인
./04_device_check.sh [단말기_시리얼]
```

---

## 🛠️ 2. 신규 단말기 사전 준비 (수동 1회 작업)

공장 초기화된 신규 단말기를 투입할 경우 아래 4가지 항목을 확인합니다:

1. **Magisk Rooting (루팅 가용)**:
   - Magisk 앱 설치 및 Zygisk 활성화 확인.
   - Magisk 설정 ➔ **DenyList 적용(Enforce DenyList)** 활성화.
2. **개발자 옵션 & USB 디버깅 개방**:
   - `설정 ➔ 휴대전화 정보 ➔ 소프트웨어 정보 ➔ 빌드번호 7회 터치`
   - `설정 ➔ 개발자 옵션 ➔ USB 디버깅 ON`
   - PC에 USB 연결 시 화면에 나타나는 팝업에서 **[이 컴퓨터에서 항상 허용]** 체크 후 [허용].
3. **구글 실사용 계정 1개 로그인**:
   - 실사용 계정 1개를 로그인하여 Google Play 서비스 및 GMS 정상 활성화 (유령 단말기 방지).
4. **플립 단말기 화면 펼침**:
   - Galaxy Z Flip 계열의 경우 메인 화면을 완전히 펼쳐둔 상태(OPEN)로 허브에 거치.

---

## ⚙️ 3. `03_device_init.sh` 자동 적용 항목 상세

`./03_device_init.sh` 스크립트가 단말기에 자동으로 구성하는 상세 항목입니다:

### (1) 무중단 24/7 가동 환경
- **충전 중 상시 켜짐**: `settings put global stay_on_while_plugged_in 7`
- **화면 타임아웃 최대화**: `settings put system screen_off_timeout 2147483647`
- **화면 잠금 해제**: `locksettings set-disabled true` & `settings put secure lockscreen.disabled 1`
- **ADB 영구 인증(7일 만료 차단)**: `settings put global adb_authorization_timeout 0`
- **Host PC ADB 공개키 영구 동기화**: `/data/misc/adb/adb_keys`에 Host 공개키 주입 및 퍼미션(640) 고정.

### (2) 디스플레이 & 배터리 최적화
- **화면 세로 고정**: `settings put system accelerometer_rotation 0` (자동회전 OFF)
- **주사율 60Hz 고정**: `settings put system peak_refresh_rate 60.0`
- **다크 모드 강제**: `cmd uimode night yes`
- **UI 애니메이션 제거**: `window_animation_scale 0`, `transition_animation_scale 0`, `animator_duration_scale 0`
- **시스템 알림/음향/TalkBack 완전 박멸**: 볼륨 0, accessibility 관련 불필요 서비스 영구 비활성화
- **긴급 재난문자 팝업 차단**: `cellbroadcastreceiver` 비활성화 (오터치/화면 가림 방지)
- **USB 고속 충전 개방**: `batt_high_current_usb 1`

### (3) FDS 및 안티 디텍션 방어선
- **Magisk DenyList 등록**:
  `com.nhn.android.search`, `com.nhn.android.search:channel`, `com.nhn.android.search:core`, `com.google.android.gms`
- **Magisk SU 토스트 알림 차단**: `su_notification=0` (화면 캡처 시 토스트 노출 방지)
- **BSSID 누출 원천 차단**:
  네이버 앱(`com.nhn.android.search`)의 `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION` 권한을 영구 박탈하고 AppOps를 `ignore`로 설정하여 실기기 위치/작업실 AP의 BSSID 유출을 원천 방어.
- **백그라운드 스캔 차단**: Wi-Fi Scan, BLE Scan, Nearby Scan 모두 0으로 비활성화.
- **블루투스 고유 지문**: `Galaxy-ZFlip3-<시리얼접미사>` 형태로 고유 네이밍 자동 부여.
- **커널 정보 보호**: `/proc/net/arp` (600), `/efs/FactoryApp/serial_no` (700) 보안 잠금.

### (4) 필수 툴 & 데몬 구성
- **네이버 공식 앱 (`com.nhn.android.search`)**: 최신 버전 자동 설치 및 배터리 절전 예외 등록.
- **ADBKeyboard (`com.android.adbkeyboard`)**: 한글/영문 키코드 주입용 IME 구성.
- **GPSEmulator (`com.rosteam.gpsemulator`)**: 모의위치 가상 GPS 허용.
- **Frida Server (`/data/local/tmp/frida-server`)**: Zygote 후킹 및 실시간 안티디텍션 데몬 백그라운드 기동.

---

## 🔍 4. `04_device_check.sh` 진단 판정 기준

`./04_device_check.sh`는 모든 단말기의 상태를 점검하여 다음과 같이 판정합니다:

| 점검 영역 | PASS 기준 (🟢) | FAIL / WARN 기준 |
| :--- | :--- | :--- |
| **네이버 공식 앱** | `com.nhn.android.search` 설치 완료 | 미설치 시 🔴 FAIL |
| **Google 계정** | 1개 이상 정상 로그인 | 미로그인 시 🔴 FAIL |
| **Magisk DenyList** | DenyList Enforce ON & 네이버앱 격리 | 미격리 시 🔴 FAIL (su 노출 위험) |
| **BSSID 위치 권한** | 네이버앱 위치 권한 박탈(Revoked) | 권한 허용 시 🔴 FAIL (작업실 AP 노출) |
| **상시 점등 & 잠금** | Stay-Awake: 7, Lockscreen: Disabled | 잠금 켜짐 시 🔴 FAIL |
| **ADB 영구 인증** | `adb_authorization_timeout` = 0 | 만료 활성 시 🟡 WARN |
| **배터리 & 전원** | 배터리 정상, 고속충전(1500mA) 개방 | 일반 충전 시 🟡 WARN |
| **무선 백그라운드 스캔**| Wi-Fi / BLE / Nearby 스캔 = 0 | 스캔 켜짐 시 🟡 WARN |

> 💡 **진단 결과 `🔴 불가`가 뜬 경우**: `./03_device_init.sh [시리얼]`을 1회 실행하면 미비점이 즉시 자동 보정됩니다.
