# 📦 Offline APK Storage Directory

이 디렉터리는 안드로이드 단말기 초기화(`device_init.sh`)에 필요한 오프라인 패키지 바이너리들이 위치하는 곳입니다.

GitHub의 100MB 단일 파일 제한을 준수하기 위해 대용량 APK 바이너리는 구글 드라이브를 통해 배포되며, 아래 스크립트로 3초 만에 자동 다운로드됩니다:

```bash
./scripts/download_apks.sh
```

## 구성 요소:
1. `essential_tools/` (`ADBKeyboard.apk`, `GPSEmulator.apk`, `wireguard/` Split APKs)
2. `naver_app/` (네이버 앱 Split APKs 최신 버전)
