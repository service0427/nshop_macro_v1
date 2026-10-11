# N-Shop Central API Server v1 (`nshop_api_v1`)

로컬 MariaDB 기반 네이버 정품 NNB/BUC 초고속 패킷 수집 및 수위 조절 REST API 서버

---

## 1. 데이터베이스 스키마 (`nnbs`)

- `id`: BIGINT AUTO_INCREMENT PK
- `nnb`: VARCHAR(13) UNIQUE (13자리 네이버 정품 NNB)
- `buc`: VARCHAR(255) NULL (네이버 BUC 쿠키)
- `use_count`: INT DEFAULT 0 (사용 누적 횟수)
- `status`: ENUM('AGING', 'READY', 'USED', 'ACTIVE', 'BLOCKED')
  - `AGING`: 발급 후 1200초 미만 숙성 진행 중인 신생아 토큰
  - `READY`: 1200초 이상 경과하여 즉시 작업 투입 가능한 토큰
  - `USED`: 작업(타격) 완료된 토큰
- `memo`: VARCHAR(255) (단말기 식별자, 메모)
- `ip`: VARCHAR(45) (채굴 시점 공인 IP)
- `device_id`: VARCHAR(100) (채굴 단말기 식별자)
- `source`: VARCHAR(50) (`LCS_PACKET`, `APP_WARMUP` 등)
- `dur_sec`: FLOAT (패킷 응답 속도, 약 0.05~0.15초)
- `used_target`: VARCHAR(255) (타격 대상 스토어/키워드)
- `created_at`: DATETIME (최초 발급 일시)
- `last_used_at`: DATETIME (최근 인출/타격 일시)

---

## 2. 패킷 수집 및 수위 조절 동작 원리

1. **`https://lcs.naver.com/m` 초경량 패킷 호출**:
   - 0.05~0.1초 만에 응답 헤더의 `NNB` 및 `BUC` 쿠키를 실시간 추출
2. **신생아 토큰 저금 (Bank)**:
   - 앱 웜업이나 단말기에서 채굴된 NNB/BUC를 DB에 적재 (`status='AGING'`)
3. **수위 조절기 (Watermark Controller)**:
   - 현재 활성 풀(READY + AGING)이 목표치(`target_size`, 기본 50개) 미달 시 패킷으로 즉시 자동 채굴 보충
4. **20분(1200초) 숙성 후 인출 (Acquire)**:
   - `created_at` 기준 1200초 이상 경과한 토큰만 원자적 락(`FOR UPDATE`)으로 선점 인출
5. **타격 완료 확정 (Mark Used)**:
   - 타격 완료 시 `status='USED'`로 확정 갱신

---

## 3. 핵심 API 엔드포인트

### 0-1) [키워드 랜덤 조회] keyword, nv_mid, compare_id 반환
- **URL**: `GET /api/v1/keyword/random`
- **외부 URL**: `http://114.207.112.173:8000/api/v1/keyword/random`
- **반환 항목**:
  - `keyword`: 상품명 (`product_name`)
  - `nv_mid`: 네이버 쇼핑 상품 ID (`target_id`)
  - `compare_id`: 가격비교 몰 상품 ID (`mall_product_id` 없으면 `target_id`)
- **응답 예시 (200 OK)**:
```json
{
  "success": true,
  "keyword": "쇼핑 접이식 카트 시장 카트 캐리어 장바구니 카트 보급형",
  "nv_mid": "81675436659",
  "compare_id": "4130915605",
  "data": {
    "keyword": "쇼핑 접이식 카트 시장 카트 캐리어 장바구니 카트 보급형",
    "nv_mid": "81675436659",
    "compare_id": "4130915605",
    "product_title": "쇼핑 접이식 카트 시장 카트 캐리어 장바구니 카트 보급형",
    "mall_name": "지니고몰",
    "price": 39900
  }
}
```
- **옵션 파라미터**:
  - 여러 개 동시 조회: `?count=5` (최대 50)
  - compare_id가 반드시 존재하는 것만 조회: `?with_compare=true`

### 0) [작업 할당 및 기존 작업 조회]
- **URL**: `GET` 또는 `POST` `/api/v1/task/assign`
- **외부 URL**: `http://114.207.112.173:8000/api/v1/task/assign`
- **파라미터**:
  - `task_id` (숫자, 선택): 이미 할당된 작업 정보를 다시 확인하고자 할 때 지정 (지정 시 NNB 소모 없이 기존 정보 그대로 반환)
  - `device_id` (문자열, 선택): 단말기 식별자
  - `min_age_seconds` (숫자, 기본 1200): NNB 최소 숙성 시간

#### ① 신규 작업 할당 (task_id 파라미터 미지정 시)
- **요청**: `curl -s "http://114.207.112.173:8000/api/v1/task/assign?device_id=phone_01"`
- **응답 (200 OK - task_id 단독 제공)**:
```json
{
  "success": true,
  "task_id": 10,
  "nnb": "K55GT6ZW4DCWU",
  "buc": "YZkMfTCu8ET6YbT_S4nsKyB-RbfU51QTPtoc-lgpKhg=",
  "keyword": "블루필 듀얼젯 바디드라이어 에어샤워 욕실 바디 건조기 드라이기 드라이 발 몸",
  "nv_mid": "90958015542",
  "compare_id": "13413505206",
  "device_id": "phone_01",
  "ip": "121.142.9.48"
}
```

#### ② 기존 작업 재조회 (task_id 지정 시)
- **요청**: `curl -s "http://114.207.112.173:8000/api/v1/task/assign?task_id=10"`
- **응답**: 기존에 할당되었던 `task_id=10`의 정보를 그대로 반환 (새로운 NNB 소모 없음)

### 0-2) [작업 완료/결과 보고] task_id 기반 결과 실시간 수신 및 DB 기록
- **URL**: `POST /api/v1/task/report` (또는 `POST /api/v1/task/complete`)
- **외부 URL**: `http://114.207.112.173:8000/api/v1/task/report`

#### ① 통합검색에서 발견/직클릭한 경우 (`search_type: "m.search"`)
- **Request Body (JSON)**:
```json
{
  "task_id": 195,
  "success": true,
  "status": "SUCCESS",
  "search_type": "m.search",
  "serp_rank": 1,
  "shopping_rank": 1,
  "shopping_page": 0,
  "match_type": "nv_mid",
  "login_detected": false,
  "device_id": "R3CR70FFFEK",
  "duration_seconds": 26.0
}
```

#### ② 쇼핑 검색 탭으로 이동하여 발견/클릭한 경우 (`search_type: "msearch"`)
- **Request Body (JSON)**:
```json
{
  "task_id": 196,
  "success": true,
  "status": "SUCCESS",
  "search_type": "msearch",
  "serp_rank": null,
  "shopping_rank": 3,
  "shopping_page": 1,
  "match_type": "nv_mid",
  "login_detected": false,
  "device_id": "R5CR91SH8LM",
  "duration_seconds": 34.5
}
```

- **응답 (200 OK)**:
```json
{
  "success": true,
  "task_id": 195,
  "message": "task_id(195) 결과 보고가 성공적으로 기록되었습니다.",
  "data": {
    "task_id": 195,
    "status": "SUCCESS",
    "search_type": "m.search",
    "serp_rank": 1,
    "shopping_rank": 1,
    "shopping_page": 0,
    "match_type": "nv_mid",
    "login_detected": false,
    "duration_seconds": 26.0,
    "device_id": "R3CR70FFFEK",
    "completed_at": "2026-10-07 17:19:41"
  }
}
```

#### ③ 특정 작업 보고서 조회 (GET)
- **URL**: `GET http://114.207.112.173:8000/api/v1/task/report?task_id=195`
- **POST** `/api/v1/nnb/harvest`
- **Request**:
```json
{
  "count": 5,
  "memo": "자동_채굴"
}
```

### 2) [토큰 저금] 앱 웜업/단말기 채굴 토큰 저금
- **POST** `/api/v1/nnb/bank`
- **Request**:
```json
{
  "nnb": "R2TM54WHZXCWU",
  "buc": "X4T4_DujDGm6ZdD...",
  "source": "APP_WARMUP",
  "device_id": "pixel_7_01"
}
```

### 3) [수위 조절] 활성 풀 자동 보충
- **POST** `/api/v1/nnb/topup`
- **Request**:
```json
{
  "target_size": 50
}
```

### 4) [작업 인출] 1200초 숙성 완료 토큰 인출
- **POST** `/api/v1/nnb/acquire`
- **Request**:
```json
{
  "min_age_seconds": 1200,
  "target": "스토어명_또는_키워드",
  "device_id": "worker_01"
}
```

### 5) [타격 확정] NNB를 USED 상태로 확정
- **POST** `/api/v1/nnb/mark-used`
- **Request**:
```json
{
  "nnb": "R2TM54WHZXCWU",
  "target": "스토어명_성공"
}
```

### 6) [풀 수위 및 상태 추적]
- **GET** `/api/v1/nnb/pool-status?min_age_seconds=1200`
- **Response**:
```json
{
  "total": 52,
  "ready_count": 35,
  "aging_count": 12,
  "used_count": 5,
  "min_age_seconds": 1200
}
```

---

## 4. 테스트 실행
```bash
python3 -m unittest discover -s . -p "test_*.py"
```
