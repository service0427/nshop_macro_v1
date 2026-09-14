# 📱 Mikrotik Mobile Automation Client API Developer Guide (v3.1 Production Standard)

본 문서는 안드로이드 실단말기(5~60대) 및 클라이언트 자동화 워커가 마이크로틱 라우터 API 서버와 통신하여 **WireGuard VPN 연결, 실전 2~3단어 검색/클릭 작업 수행, NNB/NAPP_DI/GPS/타임스탬프 식별자 추출, 10자리 표준 프로필(pf_0000000001) 자동 시딩/에이징, 앱 설치/업데이트 타임스탬프(install_ts/update_ts) 영구 보존, snapshot_size(KB) 반납, DB 원장 기반 초경량 프로필 자동 동기화(Pruning), 단말기 1대씩 즉시 개별 반납, 4중 지능형 라우터 보호**를 수행하는 최신 프로덕션 실연동 표준 규격서입니다.

---

## 📌 1. 핵심 아키텍처 및 통신 원칙

1. **배치 할당 (Batch Allocation)**:
   * 클라이언트는 단말기 1대씩 개별 호출하지 않고, **PC에 연결된 단말기 N대(`R3CR70KAZDM,R3CR70SZ0JJ,...`)를 묶어서 1회 API 호출로 일괄 할당**받습니다.
2. **단일 라우터 / 단일 공인 IP 공유**:
   * 한 번의 배치 호출에 1개의 마이크로틱 라우터(가상 WAN `macvlan1`)가 배정되며, 요청된 N대의 단말기는 해당 라우터의 서로 다른 가상 IP(`10.8.0.2`, `10.8.0.3`...)를 통해 **동일한 통신사 공인 IP를 공유**합니다.
3. **동일 IP 내 스토어 중복 배정 원천 차단**:
   * 같은 공인 IP 대역에서 동일한 스토어의 상품이 중복 배정되지 않습니다 (스토어 3분할 1:1:1 격리).
   * 작업할 스토어가 부족한 경우 남은 단말기는 **`job_type: "NO_TASK"`** 로 반환되며, 해당 단말기는 VPN을 켜지 않고 즉시 안전 반납합니다.
4. **단말기 1대씩 즉시 개별 반납 (Per-Device Fast Release)**:
   * 각 단말기마다 작업 소요시간(10초~120초)이 다르므로, **작업이 끝난 단말기는 다른 단말기를 기다리지 않고 즉시 1대씩 개별 반납(`POST /api/v1/release`)**합니다.
   * 조기 실패(Fail-Fast)한 단말기는 10초 만에 즉시 풀려나 충전/대기하며 단말기 처리량이 50% 이상 향상됩니다.
5. **서버 4중 지능형 무지성 토글 방지 & 헬스체크 안전장치**:
   * **[안전장치 1] 전원 완주 감지**: 세션 내 다른 단말기가 작업 중(`remaining_working > 0`)일 때는 **라우터 공인 IP를 절대 끊지 않고 유지**합니다.
   * **[안전장치 2] 60초 토글 쿨다운 보호**: 직전 토글로부터 60초가 지나지 않았다면 모뎀 과부하/DHCP 플러딩을 방지하기 위해 중복 토글을 자동 차단합니다.
   * **[안전장치 3] 180초 세션 고아 회수**: 단말기 통신 두절 시 180초 후 워치독이 피어 회수 및 IP 세척을 단행합니다.
   * **[안전장치 4] 토글 후 100% 통신상태 자체 검증**: RouterOS REST API를 통해 신규 공인 IP 획득(`bound`) 및 라우팅 테이블 동기화, 하트비트 정상 수신이 확인된 라우터만 다음 할당에 투입합니다.

---

## 🧬 2. 프로필 생명주기 및 10자리 표준 파일 관리

### 💡 핵심 원칙 1: "10자리 고정 프로필 파일명 (`pf_0000000001`)"
* 서버는 단말기별로 `pf_0000000001`부터 `pf_9999999999`까지 10자리 고정 일련번호를 부여합니다.
* 단말기는 서버가 내려주는 **`profile_name`**을 기준으로 자신의 로컬 작업 폴더(예: `/data/local/tmp/profile_storage/`)에 `f"{profile_name}.tar.gz"` 파일로 압축/해제합니다.

### 💡 핵심 원칙 2: "신규 시딩 시 네이버 앱 데이터 초기화 (`pm clear`) 필수"
* `profile_id == 0`: **신규 생성 (시딩)**
  - 네이버 앱 실행 전 **반드시 `adb shell pm clear com.nhn.android.search` (앱 데이터 완전 초기화)** 를 실행합니다.
  - 깨끗한 상태에서 네이버 앱을 기동하여 이번 할당된 키워드 1개만 검색 후 `f"{profile_name}.tar.gz"`로 압축 저장합니다. (검색어 누적 방지)
* `profile_id > 0`: **기존 숙성 프로필**
  - 단말기 로컬의 `f"{profile_name}.tar.gz"`를 압축 해제(복원)하여 네이버 앱을 기동합니다.

### 💡 핵심 원칙 3: "앱 설치 타임스탬프 및 버전 메타데이터 영구 보존"
* 서버는 각 프로필마다 **과거 45~300일 전의 고유한 앱 설치 타임스탬프(`install_ts`, 13자리 밀리초 Unix epoch)** 와 업데이트 타임스탬프(`update_ts`)를 발급하여 영구 보존합니다.
* 단말기는 서버가 내려준 메타데이터(`installer_pkg`, `app_version`, `app_version_code`)를 네이버 앱 환경 파라미터 및 반납 시 1:1로 활용합니다.

### 💡 핵심 원칙 4: "작업 완료 후 snapshot_size (KB Float) 반납"
* 네이버 검색/작업 완주 후 생성된 `.tar.gz` 파일 크기를 **KB 단위 Float(예: `116.2`)** 로 서버에 보고합니다.
* 앱 기동 실패 또는 네트워크 단절 등으로 파일이 생성되지 않은 경우 `snapshot_size: null`로 반납합니다.

### 💡 핵심 원칙 5: "중앙 서버 제어 기반 100회 주기당 1회 온디바이스 자동 정제"
* **원격 중앙 제어**: 중앙 서버 관리자가 오래된 프로필을 삭제하거나 `RETIRED`/`DELETED` 처리하면, 단말기 워커가 100주기마다 서버를 조회하여 **서버 DB에 없는 파일들을 단말기 로컬 저장소에서 알아서 영구 삭제(Prune)**합니다.
* 단말기 5~60대에 개별 접속할 필요 없이 **중앙 서버 DB에서 원클릭으로 모든 단말기의 프로필을 원격 중앙 관리**합니다.

---

## 📡 3. API 규격 상세

* **Base URL**: `http://114.207.112.173:5000` (또는 `https://aaa4.kr`)
* **데이터 포맷**: `JSON` (`Content-Type: application/json`)

---

### [API 1] 작업 및 WireGuard 일괄 할당 (`GET /api/v1/allocate`)

단말기 N대를 파라미터로 전달하여 1개의 공유 라우터와 단말기별 작업/프로필을 일괄 발급받습니다.

#### 🔹 요청 (Request)
```http
GET /api/v1/allocate?device_ids=R3CR70KAZDM,R3CR70SZ0JJ,R3CRB0WCGET,R5CR713T5WT,R5CR9336DSB HTTP/1.1
Host: 114.207.112.173:5000
```

#### 🔹 응답 (Response)
```json
{
  "status": "success",
  "alloc_id": "3969",
  "router": {
    "router_num": "011",
    "endpoint": "119.197.146.94:45820",
    "macvlan_ip": "119.197.183.68",
    "server_public_key": "caunbt0kvyX6VKcqrib223HO1kfqg4GEEL6f7CZc2Qk="
  },
  "tasks": [
    {
      "device_id": "R3CR70SZ0JJ",
      "ip": "10.8.0.2",
      "private_key": "eCZyQJvL6KmYA6ABNcWphCNPPeve44gYUcFtRWFA62k=",
      "mid": "91281457083",
      "keyword": "gold finger 출퇴근용 자동우산",
      "product_title": "골드핑거 자동 접이식 우산 휴대용 여행 출근 야외우산",
      "allow_click": true,
      "job_type": "GOLDEN_CLICK",
      "wifi_list": [
        {
          "ssid": "iptime_5G_22E0",
          "bssid": "64:e5:99:a3:22:e0",
          "frequency": 5240,
          "rssi": -57,
          "connectedSecurityType": 2
        },
        {
          "ssid": "SK_WiFiGIGA_2.4G",
          "bssid": "e4:26:8b:c3:4d:f0",
          "frequency": 2437,
          "rssi": -85
        },
        {
          "ssid": "KT_GiGA_5G_Home",
          "bssid": "50:46:ae:34:a1:c2",
          "frequency": 5745,
          "rssi": -69
        }
      ],
      "profile": {
        "profile_id": 663,
        "profile_name": "pf_0000000074",
        "ssaid": "6e2951e4222952ff",
        "adid": "eaa62887-3407-4055-9f96-ebccdca1d57e",
        "install_ts": 1767419009903,
        "update_ts": 1786764966607,
        "installer_pkg": "com.android.vending",
        "app_version": "12.23.1",
        "app_version_code": 12230102
      }
    }
  ]
}
```

#### 🔹 작업 대기 및 쿨다운 응답 (503 Service Unavailable)
서버에 가용 작업이 없거나(스토어 쿨다운) 라우터/IP 대기 중인 경우, 서버는 HTTP 503과 함께 세부 사유 코드를 반환합니다. 클라이언트는 이를 `logs/allocate_history/YYYY-MM-DD/no_task_records.jsonl`에 레코드 형식으로 기록하며, 단말기는 WireGuard나 앱을 실행하지 않고 안전 유휴(IDLE) 대기 상태를 유지합니다.

```json
// 1. 일감 없을 때 (스토어 쿨다운 등)
HTTP/1.1 503 Service Unavailable
{
  "status": "error",
  "code": "NO_TASKS",
  "sub_code": "STORE_COOLDOWN",
  "message": "스토어 쿨다운 진행 중입니다."
}

// 2. 가용 라우터/IP 없을 때
HTTP/1.1 503 Service Unavailable
{
  "status": "error",
  "code": "NO_IP",
  "sub_code": "ROUTER_WAITING",
  "message": "가용 라우터 대기 중입니다."
}
```

* **`wifi_list` 배열 상세 설명 (필수 - 누락 시 Fail-Fast 차단)**:
  - `wifi_list[0]` (0번 인덱스): 단말기가 접속한 **메인 연결 공유기 (Connected AP)**. `"connectedSecurityType": 2` 필수 포함.
  - `wifi_list[1:]` (1번 이후 인덱스): 단말기 주변에서 탐색된 **이웃집 스캔 Wi-Fi AP**.
  - `ssid`: 공유기 명칭 (예: `iptime_5G_22E0`, `SK_WiFiGIGA_2.4G`, `KT_GiGA_5G_Home`)
  - `bssid`: 공유기 MAC 주소 (6바이트 소문자 콜론 표기)
  - `frequency`: 주파수 (2.4GHz: 2412, 2437, 2462 / 5GHz: 5180, 5240, 5745, 5765 MHz)
  - `rssi`: 신호 강도 (dBm) (연결 AP: -45~-60dBm, 주변 AP: -65~-88dBm)

* **`profile` 객체 상세 설명**:
  - `profile_id`: `0`이면 신규 생성, `> 0`이면 기존 숙성 프로필
  - `profile_name`: `pf_0000000074` (10자리 표준 파일명)
  - `install_ts`: 최초 앱 설치 타임스탬프 (13자리 Unix epoch ms)
  - `update_ts`: 최근 앱 업데이트 타임스탬프 (13자리 Unix epoch ms)
  - `installer_pkg`: 설치 출처 패키지명 (`com.android.vending` 고정)
  - `app_version`: 설치된 네이버 앱 버전 문자열 (`12.23.1`)
  - `app_version_code`: 설치된 네이버 앱 버전 코드 (`12230102`)

* **🚀 [향후 로드맵 / API 확장 규격] 프로필별 하드웨어 지문 가상화 필드 (Hardware Virtualization Roadmap)**:
  - 현재는 테스트 및 단일/유니크 프로필 검증 단계이므로 클라이언트 워커가 `profile_name` 해시 기반 결정론적 난수로 가상화(`R5CR...`)를 수행 중입니다.
  - **향후 정식 프로덕션 단계에서 API가 사전 생성/보존하여 내려줄 확장 필드 규격**:
    ```json
    "profile": {
      "profile_id": 663,
      "profile_name": "pf_0000000074",
      "ssaid": "6e2951e4222952ff",
      "adid": "eaa62887-3407-4055-9f96-ebccdca1d57e",
      "serialno": "R5CR91KMUTY",
      "ap_serial": "0x01100583",
      "nas_user_id": "088eba4c-c3a8-4498-961d-4447ac3f5ace",
      "install_ts": 1767419009903,
      "update_ts": 1786764966607,
      "installer_pkg": "com.android.vending",
      "app_version": "12.23.1",
      "app_version_code": 12230102
    }
    ```
  - `serialno`: 삼성 갤럭시 11자리 가상 하드웨어 시리얼 (`R3CR`/`R5CR` + 배치 7~C + 6자리 영숫자). API DB 원장에서 프로필별로 영구 바인딩하여 내려줌.
  - `ap_serial`: 스냅드래곤 888 32-bit AP 퓨즈 번호 (`0x01` + 6자리 Hex).
  - `nas_user_id`: 네이버 광고/FDS 식별자 (`com.naver.ads.flags.xml`에 주입되는 고유 UUID).

---

### [API 2] 작업 완료 및 1대씩 즉시 개별 반납 (`POST /api/v1/release`)

작업이 끝난 단말기는 다른 단말기를 기다리지 않고 즉시 1대씩 개별 반납합니다.

#### 🔹 요청 (Request)
```http
POST /api/v1/release HTTP/1.1
Host: 114.207.112.173:5000
Content-Type: application/json

{
  "alloc_id": "3969",
  "results": [
    {
      "device_id": "R3CR70SZ0JJ",
      "status": "SUCCESS",
      "target_code": "91281457083",
      "keyword": "gold finger 출퇴근용 자동우산",
      "is_searched": true,
      "is_clicked": true,
      "is_exposed": true,
      "exposure_rank": 1,
      "execution_sec": 65.2,
      "battery_level": 91.50,
      "gps_lat": 37.497942,
      "gps_lng": 127.027621,
      "ssaid": "6e2951e4222952ff",
      "adid": "eaa62887-3407-4055-9f96-ebccdca1d57e",
      "nnb": "5FBIWHUTY6JWU",
      "napp_di": "f035173eb53f14993a2286efe7d87ba8",
      "install_ts": 1767419009903,
      "update_ts": 1786764966607,
      "installer_pkg": "com.android.vending",
      "app_version": "12.23.1",
      "app_version_code": 12230102,
      "snapshot_size": 118.0
    }
  ]
}
```

#### 🔹 응답 (Response)
```json
{
  "status": "success",
  "session_state": "PARTIAL_RELEASED",
  "is_session_closed": false,
  "alloc_id": "3969",
  "remaining_working": 1,
  "processed_devices": ["R3CR70SZ0JJ"],
  "toggled_routers": [],
  "message": "세션 [3969] 조기 반납 접수 완료 (진행 중인 단말기 1대 존재로 라우터 IP 유지)"
}
```
*(세션 내 마지막 남은 단말기까지 모두 반납되면 `remaining_working: 0`, `is_session_closed: true`가 되며 라우터 IP가 자동 세척/토글됩니다.)*

---

### [API 3] 단말기별 서버 프로필 목록 조회 (`GET /api/v1/profiles`)

중앙 DB가 프로필의 "진실의 원천(Source of Truth)"입니다. 관리자가 DB에서 특정 프로필을 삭제하거나 비활성화하면, 단말기는 100주기마다 이 API를 호출해 **현재 DB에 살아있는 유효한 파일명 목록(`files`)만 받아와서, 단말기 로컬에 남은 불필요한 tar.gz 고아 파일들을 즉시 삭제(Pruning)**합니다.

#### 🔹 요청 (Request)
```http
GET /api/v1/profiles?device_id=R3CR70SZ0JJ HTTP/1.1
Host: 114.207.112.173:5000
```

#### 🔹 초경량 응답 (Ultra-Compact Response, 2,000개 누적 시에도 30KB 미만)
```json
{
  "status": "success",
  "device_id": "R3CR70SZ0JJ",
  "count": 7,
  "files": [
    "pf_0000000001.tar.gz",
    "pf_0000000002.tar.gz",
    "pf_0000000003.tar.gz",
    "pf_0000000004.tar.gz",
    "pf_0000000005.tar.gz",
    "pf_0000000006.tar.gz",
    "pf_0000000007.tar.gz"
  ]
}
```

* **단말기 동기화 로직**: 로컬 `/data/local/tmp/profile_storage/` 디렉터리의 파일 중 위 `files` 배열에 **없는 파일만 즉시 rm 삭제**하면 100% 동기화가 완료됩니다.

---

## 🔒 4. 클라이언트 WireGuard 터널 조립 규격

클라이언트는 API 응답값과 아래 표준 규격을 조합하여 WireGuard 터널을 생성합니다.

```ini
[Interface]
PrivateKey = {task.private_key}
Address = {task.ip}/32
DNS = 8.8.8.8, 1.1.1.1
MTU = 1420

[Peer]
PublicKey = {router.server_public_key}
Endpoint = {router.endpoint}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```

