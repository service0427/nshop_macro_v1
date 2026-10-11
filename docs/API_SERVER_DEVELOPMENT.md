# 🌐 중앙 API 서버 개발 & 원격 관제 가이드

본 문서는 N-Shop Macro의 작업 분배 및 NNB 토큰 숙성을 전담하는 **중앙 API 서버(`114.207.112.173:8000`)의 아키텍처와 로컬 개발/배포 워크플로우**를 정리한 개발자 문서입니다.

---

## 🏗️ 1. 원격 서버 기본 정보

| 항목 | 상세 내용 |
| :--- | :--- |
| **호스트 IP** | `114.207.112.173` (SSH Port: 22) |
| **운영체제** | Ubuntu 22.04 LTS (x86_64, Uptime 50+ days) |
| **SSH 계정** | `tech` / `Tech1324!` |
| **서버 디렉터리** | `/home/tech/nshop_api_v1` |
| **데이터베이스** | MariaDB 10.x (`nshop@127.0.0.1:3306`, DB: `nshop_api_v1`) |
| **PM2 서비스** | • `nshop-api` (FastAPI/Flask API 엔드포인트, Port: 8000)<br>• `nshop-pool-daemon` (실시간 LCS 패킷 NNB 채굴/숙성 데몬) |

---

## 🎛️ 2. 로컬 원격 관제 도구 (`remote_api_mgr.py`)

클라이언트 PC의 로컬 터미널에서 중앙 서버를 직접 제어할 수 있는 전용 관리 스크립트가 탑재되어 있습니다:

```bash
# 1. 서버 PM2 및 MariaDB 실시간 상태 조회
python3 scripts/remote_api/remote_api_mgr.py status

# 2. 실시간 API 서버 로그 조회 (최근 50줄)
python3 scripts/remote_api/remote_api_mgr.py logs -n 50

# 3. API 서버 무중단 리로드
python3 scripts/remote_api/remote_api_mgr.py reload

# 4. MariaDB 쿼리 즉시 실행
python3 scripts/remote_api/remote_api_mgr.py db "SELECT task_id, keyword, store_name, status FROM tasks ORDER BY task_id DESC LIMIT 5;"

# 5. 로컬 수정본을 원격 서버로 배포 (SFTP 전송 ➔ 원격 문법 검사 ➔ PM2 리로드 자동 수행)
python3 scripts/remote_api/remote_api_mgr.py push services/task_service.py

# 6. 원격 서버의 최신 소스 로컬 미러로 내려받기
python3 scripts/remote_api/remote_api_mgr.py pull services/task_service.py
```

---

## 📁 3. 중앙 API 개발 전용 폴더 (`api/`)

중앙 API 서버의 소스코드는 프로젝트 루트의 `api/` 디렉터리에 독립된 프로젝트로 분리되어 형상 관리(Git) 및 로컬 IDE 편집이 가능합니다:

```text
nshop_macro_v1/
└── api/
    ├── app.py                      # Flask 애플리케이션 진입점 (Blueprint 라우팅)
    ├── config.py                   # DB 접속 정보 및 최소 숙성 시간(1200초) 설정
    ├── database.py                 # PyMySQL 커넥션 풀 및 컨텍스트 매니저
    ├── daemon_pool_maintainer.py   # NNB 패킷 채굴/숙성 데몬
    ├── ecosystem.config.js         # PM2 프로세스 정의
    ├── deploy.py                   # 원격 서버 무중단 배포/동기화 도구 (push/pull/reload/status)
    ├── services/
    │   ├── task_service.py         # 작업 할당, 완료 보고, 스토어명 매칭, 30분 만료 처리
    │   └── nnb_service.py          # NNB 풀 선점 및 상태 반환
    ├── routes/
    │   ├── task.py                 # /api/v1/task/* 엔드포인트
    │   └── nnb.py                  # /api/v1/nnb/* 엔드포인트
    └── core/                       # 패킷 채굴 및 파서 모듈
```

---

## 📡 4. REST API 명세서

### (1) 작업 할당 API: `GET /api/v1/task/assign`
* **요청 파라미터**:
  - `device_id` (str, 필수): 단말기 논리 식별자 (예: `phone_01`)
  - `min_age_seconds` (int, 선택): 최소 숙성 시간 (기본값: 1200초 = 20분 하한선 강제)
  - `task_id` (int, 선택): 기존 할당 작업 재조회 모드
* **동작 원칙**:
  1. 30분 이상 경과된 미완료(`ASSIGNED`) 작업을 자동으로 `TIMEOUT` 처리.
  2. 20분 이상 숙성된 NNB 토큰을 `nnbs` 테이블에서 선점 (`FOR UPDATE`).
  3. `nshop_list`에서 대상 상품, 키워드, `mall_name`(`store_name`) 매칭.
  4. `tasks` 테이블에 `ASSIGNED` 상태로 신규 등록.
* **정상 응답 (200 OK)**:
  ```json
  {
    "success": true,
    "task_id": 1000001,
    "keyword": "NEXT-POE605F",
    "nv_mid": "58903592598",
    "compare_id": null,
    "store_name": "컴퓨존",
    "nnb": "2S4VQPB34DCWU",
    "buc": "RoORrNtiFNSIN3...",
    "device_id": "phone_01",
    "ip": "121.142.9.48"
  }
  ```
* **작업 없음 / 쿨다운 대기 (404 Not Found)**:
  - 1200초 이상 숙성된 NNB가 부족하거나 스토어 쿨다운 중일 때 반환됩니다.
  - 클라이언트는 이를 **에러로 간주하지 않고 IDLE 대기 상태로 유지**합니다.

---

### (2) 작업 결과 보고 API: `POST /api/v1/task/report`
* **요청 페이로드**:
  ```json
  {
    "task_id": 1000001,
    "status": "SUCCESS",
    "search_type": "m.search",
    "serp_rank": 1,
    "shopping_rank": 1,
    "shopping_page": 1,
    "match_type": "nv_mid",
    "login_detected": false,
    "device_id": "R3CR70K98XZ",
    "store_name": "컴퓨존",
    "duration_seconds": 18.78,
    "memo": "성공 (쇼핑순위: 1위, 몰: 컴퓨존)"
  }
  ```
* **상태값 정규화 (DB ENUM 보호)**:
  - 허용 ENUM: `'ASSIGNED'`, `'SUCCESS'`, `'FAILED'`, `'TIMEOUT'`, `'CANCELLED'`
  - 클라이언트가 `TARGET_NOT_FOUND`, `FDS_BLOCKED` 등 비표준 상태를 보낼 경우, 서버는 이를 `FAILED`로 정규화하고 `result_memo`에 원본 상태(`[TARGET_NOT_FOUND]...`)를 100% 보존합니다.

---

## 🗄️ 5. MariaDB 핵심 스키마 (`tasks`)

```sql
CREATE TABLE `tasks` (
  `task_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `nnb` varchar(32) DEFAULT NULL,
  `buc` varchar(255) DEFAULT NULL,
  `keyword` varchar(500) NOT NULL,
  `nv_mid` varchar(100) NOT NULL,
  `compare_id` varchar(100) DEFAULT NULL,
  `store_name` varchar(255) DEFAULT NULL,
  `device_id` varchar(100) DEFAULT NULL,
  `ip` varchar(45) DEFAULT NULL,
  `status` enum('ASSIGNED','SUCCESS','FAILED','TIMEOUT','CANCELLED') DEFAULT 'ASSIGNED',
  `search_type` varchar(20) DEFAULT NULL,
  `serp_rank` int(11) DEFAULT NULL,
  `shopping_rank` int(11) DEFAULT NULL,
  `shopping_page` int(11) DEFAULT NULL,
  `match_type` varchar(50) DEFAULT NULL,
  `login_detected` tinyint(1) NOT NULL DEFAULT 0,
  `duration_seconds` float DEFAULT NULL,
  `raw_report` text DEFAULT NULL,
  `result_memo` varchar(255) DEFAULT NULL,
  `assigned_at` datetime NOT NULL DEFAULT current_timestamp(),
  `completed_at` datetime DEFAULT NULL,
  PRIMARY KEY (`task_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
