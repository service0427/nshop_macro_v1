# 📱 Mikrotik Mobile Automation Client API Developer Guide (v2.6 Production Standard)

본 문서는 안드로이드 실단말기(5~60대) 및 클라이언트 자동화 워커가 마이크로틱 라우터 API 서버와 통신하여 **WireGuard VPN 연결, 실전 2~3단어 검색/클릭 작업 수행, NNB/NAPP_DI/GPS 식별자 추출, 120개 온디바이스 프로필 풀 누적/동기화, snapshot_size(KB) 반납, DB 우선 프로필 자동 정제(Pruning), 단말기 1대씩 즉시 개별 반납, 4중 무지성 토글 방지**를 수행하는 최신 프로덕션 실연동 표준 규격서입니다.

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

## 🧬 2. 프로필 생명주기 및 DB 우선 온디바이스 동기화 표준

### 💡 핵심 원칙 1: "성공 검증된 프로필만 snapshot_path & snapshot_size(KB) 저장"
* `is_searched == True`로 네이버 검색 및 쿠키 추출에 완주한 프로필만 tar.gz 스냅샷을 생성하고, 파일 크기(`snapshot_size: 116.2` KB)를 서버에 보고합니다.
* `is_searched == False`(WG/홈 에러 등)인 경우 스냅샷을 생성하지 않고 `snapshot_path: null`, `snapshot_size: null`로 반납합니다.

### 💡 핵심 원칙 2: "100회 주기당 1회 DB 우선 온디바이스 불필요 파일 자동 정제"
* 클라이언트는 100주기마다 1회 `GET /api/v1/profiles?device_id={단말기ID}&compact=1`를 호출하여 서버 DB에 등록된 유효 프로필 목록(`READY`, `AGING`)을 수신합니다.
* 단말기 로컬 디렉터리(`/data/local/tmp/profile_storage/`)에 존재하지만 서버 DB에 없거나 `RETIRED`/`DELETED`된 고아 tar.gz 파일은 **단말기에서 즉시 영구 삭제(Prune)**하여 100% 완벽한 싱크를 유지합니다.

---

## 📡 3. API 규격 상세

* **Base URL**: `http://114.207.112.173:5000` (또는 `https://aaa4.kr`)
* **데이터 포맷**: `JSON` (`Content-Type: application/json`)

---

### [API 1] 작업 및 WireGuard 일괄 할당 (`GET/POST /api/v1/allocate`)

```http
GET /api/v1/allocate?device_ids=R3CR70KAZDM,R3CR70SZ0JJ,R3CRB0WCGET,R5CR713T5WT,R5CR9336DSB HTTP/1.1
Host: 114.207.112.173:5000
```

```json
{
  "status": "success",
  "alloc_id": "3003",
  "router": {
    "router_num": "008",
    "endpoint": "221.163.54.24:45820",
    "macvlan_ip": "125.130.247.245",
    "server_public_key": "si9407EffGLzEbcWCodH7tp1KR4eUE2MjeoBU0nqgWk="
  },
  "tasks": [
    {
      "device_id": "R3CR70SZ0JJ",
      "ip": "10.8.0.3",
      "private_key": "6Cl0ROVXfDFV+J...",
      "mid": "91247019083",
      "keyword": "슬라이딩 디테일애드 계란",
      "product_title": "계란 보관함 슬라이딩 2단...",
      "allow_click": true,
      "job_type": "GOLDEN_CLICK",
      "profile": {
        "profile_id": 812,
        "profile_name": "pf_R3CR70SZ0JJ_0008",
        "snapshot_path": "/data/local/tmp/profile_storage/pf_R3CR70SZ0JJ_0008.tar.gz",
        "ssaid": "5c73297dfae0c155",
        "adid": "38b58cc3-e55c-029b-9808-3b545647f840"
      }
    }
  ]
}
```

---

### [API 2] 작업 완료 및 1대씩 즉시 개별 반납 (`POST /api/v1/release`)

#### 🔹 [Case A] 🛒 골든 클릭 / 노출 완주 반납 (`snapshot_size` 추가)
```json
{
  "alloc_id": "3003",
  "results": [
    {
      "device_id": "R3CR70SZ0JJ",
      "status": "SUCCESS",
      "target_code": "91247019083",
      "keyword": "슬라이딩 디테일애드 계란",
      "is_searched": true,
      "is_clicked": true,
      "is_exposed": true,
      "exposure_rank": 1,
      "execution_sec": 84.5,
      "cycle_duration_sec": 84.5,
      "free_storage_mb": 216557,
      "battery_level": 53.06,
      "gps_lat": 37.497942,
      "gps_lng": 127.027621,
      "ssaid": "5c73297dfae0c155",
      "adid": "38b58cc3-e55c-029b-9808-3b545647f840",
      "nnb": "5FBIWHUTY6JWU",
      "napp_di": "f035173eb53f14993a2286efe7d87ba8",
      "snapshot_path": "/data/local/tmp/profile_storage/pf_R3CR70SZ0JJ_0008.tar.gz",
      "snapshot_size": 116.2            // [신규] 생성된 tar.gz 파일의 실제 크기 (KB 단위 Float)
    }
  ]
}
```

#### 🔹 [Case B] ❌ 최초 1회 미달성 조기 실패 반납
```json
{
  "alloc_id": "3003",
  "results": [
    {
      "device_id": "R3CR70KAZDM",
      "status": "FAILED",
      "target_code": "91281269728",
      "keyword": "카인드 몰 등산용 메쉬",
      "is_searched": false,
      "is_clicked": false,
      "is_exposed": false,
      "execution_sec": 59.3,
      "cycle_duration_sec": 59.3,
      "free_storage_mb": 214762,
      "battery_level": 81.25,
      "error_reason": "TUNNEL_DOWN",
      "snapshot_path": null,
      "snapshot_size": null
    }
  ]
}
```

---

### [API 3] 단말기별 서버 프로필 목록 조회 (`GET /api/v1/profiles`)

서버 DB에 등록된 유효 프로필을 조회하여 온디바이스와 100% 동기화합니다.

#### 🔹 요청 (Request)
```http
GET /api/v1/profiles?device_id=R3CR70SZ0JJ&compact=1 HTTP/1.1
Host: 114.207.112.173:5000
```

#### 🔹 응답 예시 (Response JSON)
```json
{
  "status": "success",
  "device_id": "R3CR70SZ0JJ",
  "count": 7,
  "profiles": [
    {
      "name": "pf_R3CR70SZ0JJ_0008",
      "file": "pf_R3CR70SZ0JJ_0008.tar.gz",
      "status": "READY",
      "nnb": "5FBIWHUTY6JWU",
      "ssaid": "5a21faf64ac349da",
      "searches": 1,
      "clicks": 0,
      "size_kb": 116.2
    },
    {
      "name": "pf_R3CR70SZ0JJ_0007",
      "file": "pf_R3CR70SZ0JJ_0007.tar.gz",
      "status": "READY",
      "nnb": "GAMCICHSV6JWU",
      "ssaid": "ea75f30e0d951f55",
      "searches": 6,
      "clicks": 3,
      "size_kb": 84.1
    }
  ],
  "summary": {
    "total": 7,
    "ready": 7,
    "aging": 0,
    "daily_clicks": 15
  }
}
```

---

## 🔒 4. 클라이언트 WireGuard 터널 조립 규격

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
