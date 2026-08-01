# N-Shop Automation Master & WireGuard RouterOS MacVlan Engine (`wg_nshop_v1`)

고성능 네이버 쇼핑 자동화 매크로 파이프라인 및 **MikroTik RouterOS MacVlan 기반 IP 자동 회전 엔진** 프로젝트입니다.

---

## 🌟 핵심 주요 기능 및 시스템 아키텍처

### 1. WireGuard & MikroTik RouterOS MacVlan IP 회전 엔진 (`--wg`)
- **독립형 MacVlan 바인딩 (`macvlan1`)**:
  - RouterOS REST API (`http://hj20acn8f3p.sn.mynetname.net/rest`) 연동.
  - 라우터 메인 회선(`ether1`)에 영향을 주지 않는 전용 `macvlan1` 가상 인터페이스 생성.
- **정책 라우팅 (Policy Routing) & Mangle Prerouting**:
  - WireGuard 대역(`10.8.0.0/24`) 패킷을 `to-macvlan1` 라우팅 테이블로 강제 마킹(Mangle).
  - `macvlan1` 전용 Masquerade NAT 규칙 및 Dynamic Default Route 실시간 자동 업데이트.
- **안드로이드 단일 `wg0` 프로필 0.1초 찰나 UI Toggle**:
  - 스마트폰 내 불필요한 중복 프로필 자동 정리 후 오직 **`wg0` 단일 설정**만 관리.
  - 작업 시작 시 0.1초 찰나 스위치 토글로 스마트폰 공인 IP와 `macvlan1` 라우터 IP 100% 동기화 검증.
  - 작업 완료 시 **WireGuard 비활성화(OFF) ➡️ MAC 주소 난수화 ➡️ DHCP release/renew**로 새로운 공인 IP 회전(Toggle).

### 2. 프리다(Frida) 기반 네트워크 패킷 훅 & HTTP/3 우회
- Frida 기반 `network_hook.js` 훅 주입을 통한 패킷 모니터링.
- HTTP/3 (QUIC) 통신 특성 및 카탈로그 상품 로그인 전환 방지 우회 설계.

### 3. 디바이스 식별자 및 세션 프로필 관리
- ADB 기반 SSAID, ADID, MAC 주소, 기기 핑거프린트 비부팅 실시간 변경 (`--no-reboot`).
- 성공한 탐색 세션의 쿠키, 식별자, 디바이스 상태를 `/profiles/<ssaid>.json`으로 라이브 백업 및 복원 지원.

### 4. PM2 서비스 상시 데몬화
- `web_monitor` (웹 실시간 모니터링 대시보드) 및 `session_server` (API 서버) PM2 프로세스 관리.

---

## 📂 프로젝트 디렉토리 구조

```text
nshop_macro_v1/
├── apks/                     # WireGuard 및 디바이스 연동 APK 모음
├── config/                   # 시스템 및 기기 설정 파일
├── profiles/                 # SSAID/세션 프로필 JSON 백업 저장소
├── src/                      # 핵심 소스코드
│   ├── lib/                  # ADB, Frida 훅, 식별자 관리 라이브러리
│   ├── macro/                # UI 자동화 및 네이버 파서 모듈
│   ├── modules/              # wireguard_manager.py (라우터 & WG 핵심 제어기)
│   └── utils/                # web_monitor 및 템플릿
├── run.sh                    # 통합 마스터 파이프라인 실행 스크립트
├── .gitignore                # 깃 추적 제외 규칙
└── README.md                 # 프로젝트 문서
```

---

## 🚀 사용법 및 실행 명령

### 1. 도움말 확인
```bash
./run.sh --help
```

### 2. WireGuard + RouterOS IP 자동 회전 매크로 실행 (`--wg`)
```bash
./run.sh R5CT20Y2XYE --no-reboot -k "노트북" -p "87528666743" --wg
```

### 3. WireGuard & 라우터 IP 독립 단독 테스트
```bash
python3 tmp/test_wireguard_standalone.py
```

---

## 🔮 향후 확장 계획 (Roadmap)

1. **REST API 외부 컨트롤러 통합**:
   - 외부 중앙 서버에서 멀티 스마트폰 작업을 제어할 수 있는 RESTful API 통신 레이어 확장.
2. **다중 단말기 동시 구동 (`loop.sh`)**:
   - 서버당 최대 60대 스마트폰 병렬 구동을 위한 멀티 프로세싱 병렬 파이프라인 구축.
