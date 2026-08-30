# 🧪 Development & Research Tools (개발 및 연구용 도구)

이 폴더는 실서비스 배포용 클라이언트 노드(`daemon.py`, `src/pipeline/`)와 분리된 **패킷 분석(MITM), Frida 훅 디버깅, 단독 프로토타입 검증용 도구**들을 보관하는 공간입니다.

---

## 📂 구성 도구

1. **Frida 훅 및 디버깅 스크립트**:
   - `src/lib/hooks/network_hook.js`: 네이버 앱 네트워크 요청/응답 실시간 후킹
   - `src/run_frida_spawn.py`: Frida 기반 네이버 앱 스폰 및 자바스크립트 주입기
2. **MITM 패킷 덤퍼**:
   - `src/lib/pure_mitm_addon.py`: 실시간 nlog/API 트래픽 덤프 애드온
3. **배치 및 테스트 유틸리티**:
   - `scripts/monitor_charging.py`: 20분 분 단위 배터리 충전 속도 벤치마크
   - `scripts/download_apks.sh`: 구글 드라이브 APK 다운로더

---

> ⚠️ **주의**: 일반 배포 클라이언트 PC에서는 위 도구들을 실행할 필요가 없으며, 오직 `./pm2_setup.sh`와 `./device_init.sh` 2개만으로 운영됩니다.
