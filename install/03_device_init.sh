#!/usr/bin/env bash

# ========================================================================================
# [03 단계] N-Shop Macro Android Phone Farm Device Initializer (03_device_init.sh)
# ========================================================================================
# - 단말기 화면 잠금 완전 해제 (재부팅 시 화면 꺼짐/잠김 방지)
# - USB/충전 중 상시 켜짐 (stay_on_while_plugged_in 7)
# - USB 디버깅 영구 인증 유지 및 7일 자동 만료 차단 (adb_authorization_timeout 0)
# - Host PC ADB 공개키 영구 고정 (/data/misc/adb/adb_keys 백업 및 권한 잠금)
# - 세로 화면 고정 및 오터치 방지 해제, UI 애니메이션 제거, 60Hz, 다크모드, USB고속충전
# - 블루투스/디바이스 고유 명칭 부여 (Galaxy-ZFlip3-<시리얼접미사>)
# - 주변 Wi-Fi/BLE/Nearby 백그라운드 탐색 차단 (0)
# - 커널 ARP 테이블(600) 및 EFS 시리얼(700) 보안 잠금
# - 고정밀 GPS 위치 모드(3) 및 GPSEmulator 모의위치 허용
# - 필수 앱 자동 설치 (ADBKeyboard, GPSEmulator, WireGuard, 네이버 앱 Split APK)
# - ADBKeyboard 기본 IME 등록 및 활성화
# - 네이버 앱 위치 권한(BSSID) 박탈 및 배터리 절전 예외 등록
# - Magisk DenyList 강제 활성화 및 네이버 앱 프로세스 격리 등록
# - Magisk 슈퍼유저(su) 권한 허용 토스트 알림 영구 비활성화 (su_notification 0, uid 2000 notification 0)
# ========================================================================================

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="/home/tech/nshop_macro_v1"
APKS_DIR="$PROJECT_ROOT/install/apks"
[ ! -d "$APKS_DIR" ] && APKS_DIR="$PROJECT_ROOT/apks"

CYAN="\e[1;36m"
GREEN="\e[1;32m"
YELLOW="\e[1;33m"
RED="\e[1;31m"
BOLD="\e[1m"
DIM="\e[2m"
NC="\e[0m"

echo -e "${CYAN}====================================================================================================================${NC}"
echo -e "${CYAN} 📱 [03단계] N-Shop Macro Phone Farm 단말기 일괄 초기화 & 자동 패치 (03_device_init.sh)${NC}"
echo -e "${CYAN}====================================================================================================================${NC}"

# 0. 필수 APK 파일 확인 및 압축 해제
# 방금 기준: naver_app_<version> 디렉토리 탐색 (최신 12.23.81 우선, 12.22.50 보조)
if [ ! -d "$APKS_DIR/naver_app_12.23.81" ] && [ ! -d "$APKS_DIR/naver_app_12.22.50" ] && [ ! -d "$APKS_DIR/naver_app" ]; then
    if [ -f "$APKS_DIR/naver_app_latest.tar.gz" ]; then
        echo -e "${YELLOW}[*] naver_app_latest.tar.gz 압축 해제 중...${NC}"
        mkdir -p "$APKS_DIR/naver_app_12.22.50"
        tar -xzf "$APKS_DIR/naver_app_latest.tar.gz" -C "$APKS_DIR/naver_app_12.22.50"
    fi
fi

if [ ! -d "$APKS_DIR/wireguard" ] && [ -f "$APKS_DIR/essential_tools.tar.gz" ]; then
    echo -e "${YELLOW}[*] essential_tools.tar.gz 압축 해제 중...${NC}"
    mkdir -p "$APKS_DIR/essential_tools"
    tar -xzf "$APKS_DIR/essential_tools.tar.gz" -C "$APKS_DIR/essential_tools"
    cp -rf "$APKS_DIR/essential_tools/wireguard" "$APKS_DIR/" 2>/dev/null || true
    cp -f "$APKS_DIR/essential_tools/ADBKeyboard.apk" "$APKS_DIR/" 2>/dev/null || true
    cp -f "$APKS_DIR/essential_tools/GPSEmulator.apk" "$APKS_DIR/" 2>/dev/null || true
fi

# 대상 단말기 지정 ($1) 또는 전체 작업 단말기 자동 감지
EXCLUDE_DEVICE=""
TARGET_DEVICE=$1

if [ -z "$TARGET_DEVICE" ]; then
    echo -e "${YELLOW}[*] 대상 단말기가 지정되지 않았습니다. 연결된 작업 단말기 전체를 자동 감지합니다...${NC}"
    DEVICES=$(adb devices | grep -w "device" | awk '{print $1}')
    UNAUTH_DEVICES=$(adb devices | grep -w "unauthorized" | awk '{print $1}')
    if [ -n "$UNAUTH_DEVICES" ]; then
        echo -e "${RED}[!] ⚠️ USB 디버깅 미인증(unauthorized) 단말기 감지됨:${NC}"
        for udev in $UNAUTH_DEVICES; do
            echo -e "    ${RED}↳ $udev (화면에서 '항상 허용' 체크 후 [허용] 터치 필요)${NC}"
        done
        echo -e "${YELLOW}[ℹ️] 단말기 허용 후 다시 실행하면 영구 인증(만료 방지)이 자동 적용됩니다.${NC}"
    fi
else
    echo -e "${YELLOW}[*] 특정 대상 단말기 지정: $TARGET_DEVICE${NC}"
    DEVICES=$TARGET_DEVICE
fi

if [ -z "$DEVICES" ]; then
    echo -e "${RED}[-] 연결된 단말기가 없습니다. USB 디버깅 및 연결 상태를 확인하세요.${NC}"
    exit 1
fi

init_single_device() {
    local serial=$1
    local serial_suffix="${serial: -5}"
    local expected_bt_name="Galaxy-ZFlip3-${serial_suffix}"

    echo -e "\n${CYAN}--------------------------------------------------------------------------------------------------------------------${NC}"
    echo -e "${GREEN}[📱 단말기 초기화 및 안티디텍션 패치 시작: $serial]${NC}"
    echo -e "${CYAN}--------------------------------------------------------------------------------------------------------------------${NC}"

    # 1. Root (su) 권한 확인 및 Magisk DenyList 은닉 활성화 (FDS 루팅 탐지 원천 차단)
    local HAS_SU=$(adb -s "$serial" shell "which su 2>/dev/null || ls /system/bin/su /system/xbin/su /sbin/su /product/bin/su 2>/dev/null" | head -1 | tr -d '\r\n')

    if [ -n "$HAS_SU" ]; then
        echo -e "  [✓] Root (su) 권한 확인 완료"
        echo -e "  [*] [1/8] Magisk DenyList 강제 활성화 및 네이버 앱 프로세스 격리 등록 중..."
        adb -s "$serial" shell "su -c '
            magisk --denylist enable
            magisk --denylist add com.nhn.android.search 2>/dev/null || true
            magisk --denylist add com.nhn.android.search com.nhn.android.search:channel 2>/dev/null || true
            magisk --denylist add com.nhn.android.search com.nhn.android.search:core 2>/dev/null || true
            magisk --denylist add com.google.android.gms 2>/dev/null || true
            magisk --denylist add com.google.android.gms com.google.android.gms.unstable 2>/dev/null || true
            magisk --denylist add com.android.chrome 2>/dev/null || true
            magisk --denylist add org.mozilla.firefox 2>/dev/null || true
            magisk --denylist add com.naver.whale 2>/dev/null || true
            magisk --denylist add com.sec.android.app.sbrowser 2>/dev/null || true
        '" 2>/dev/null
        echo -e "      ↳ [✓] Magisk DenyList 강제 활성화 및 네이버 앱/GMS 격리 등록 완료"

        # Magisk Shell(uid=2000) 및 전역 슈퍼유저 허용 토스트 알림 영구 차단 (화면 가림/오동작 방지)
        adb -s "$serial" shell "su -c \"magisk --sqlite 'UPDATE policies SET notification=0 WHERE uid=2000; REPLACE INTO settings (key,value) VALUES (\\\"su_notification\\\",0);'\"" 2>/dev/null || true
        echo -e "      ↳ [✓] Magisk 슈퍼유저 권한 허용 토스트 알림 영구 비활성화 완료 (su_notification=0)"
    else
        echo -e "  ${YELLOW}[⚠️] Root 권한을 찾을 수 없습니다. 일반 ADB 명령으로 진행합니다.${NC}"
    fi

    # 1-1. mitmproxy 시스템 CA 인증서 주입 & WebView/Whale 디버깅 프록시 구성 (R3CR70FFFEK 동일 구성)
    echo -e "  [*] [1-1] mitmproxy 시스템 CA 인증서 및 WebView 디버깅 프록시 환경 구성 중..."
    local CA_CERT_FILE="$HOME/.mitmproxy/mitmproxy-ca-cert.cer"
    if [ -f "$CA_CERT_FILE" ]; then
        adb -s "$serial" push "$CA_CERT_FILE" /data/local/tmp/c8750f0d.0 >/dev/null 2>&1
        if [ -n "$HAS_SU" ]; then
            adb -s "$serial" shell "su -mm -c '
                # 1. Magisk trustusercerts 모듈 디렉토리 구성 (재부팅 시 자동 마운트)
                mkdir -p /data/adb/modules/trustusercerts/system/etc/security/cacerts 2>/dev/null
                cp /data/local/tmp/c8750f0d.0 /data/adb/modules/trustusercerts/system/etc/security/cacerts/c8750f0d.0 2>/dev/null
                chmod 644 /data/adb/modules/trustusercerts/system/etc/security/cacerts/c8750f0d.0 2>/dev/null
                chown -R root:root /data/adb/modules/trustusercerts 2>/dev/null || true

                # 2. 사용자 인증서 저장소에도 백업 주입
                mkdir -p /data/misc/user/0/cacerts-added 2>/dev/null
                cp /data/local/tmp/c8750f0d.0 /data/misc/user/0/cacerts-added/c8750f0d.0 2>/dev/null
                chmod 644 /data/misc/user/0/cacerts-added/c8750f0d.0 2>/dev/null
                chown system:system /data/misc/user/0/cacerts-added/c8750f0d.0 2>/dev/null || true

                # 3. 글로벌 마운트 네임스페이스에 cacerts 오버레이 바인드 (재부팅 없이 즉시 시스템 인증서 활성화)
                mkdir -p /data/local/tmp/new_cacerts 2>/dev/null
                cp /system/etc/security/cacerts/* /data/local/tmp/new_cacerts/ 2>/dev/null
                cp /data/local/tmp/c8750f0d.0 /data/local/tmp/new_cacerts/ 2>/dev/null
                chmod 644 /data/local/tmp/new_cacerts/* 2>/dev/null
                chown -R root:root /data/local/tmp/new_cacerts 2>/dev/null
                chcon u:object_r:system_file:s0 /data/local/tmp/new_cacerts/* 2>/dev/null || true
                mount --bind /data/local/tmp/new_cacerts /system/etc/security/cacerts 2>/dev/null || true
            '" 2>/dev/null
            echo -e "      ↳ [✓] mitmproxy 시스템 CA 인증서(c8750f0d.0) 주입 및 전역 mount --bind 완료"
        fi

        # WebView / Whale 커맨드라인 디버깅 플래그 구성
        adb -s "$serial" shell "
            echo '_ --proxy-server=http://127.0.0.1:8888 --ignore-certificate-errors' > /data/local/tmp/webview-command-line
            echo '_ --proxy-server=http://127.0.0.1:8888 --ignore-certificate-errors' > /data/local/tmp/whale-command-line
            chmod 777 /data/local/tmp/webview-command-line /data/local/tmp/whale-command-line 2>/dev/null || true
        " 2>/dev/null
        echo -e "      ↳ [✓] WebView 및 Whale 프록시 플래그 파일 (/data/local/tmp/*-command-line) 구성 완료"
    else
        echo -e "      ${YELLOW}[⚠️] $CA_CERT_FILE 을 찾을 수 없어 인증서 주입을 건너뜁니다.${NC}"
    fi

    # 리버스 포트 및 프록시 초기화
    adb -s "$serial" reverse tcp:8888 tcp:8888 2>/dev/null || true
    adb -s "$serial" shell "settings put global http_proxy :0; settings delete global global_http_proxy_host; settings delete global global_http_proxy_port" 2>/dev/null || true

    # 2. 화면 잠금 완전 해제 & 재부팅 시 잠김/꺼짐 방지 & ADB 영구 인증(만료 차단)
    echo -e "  [*] [2/8] 화면 잠금 비활성화 & 상시 켜짐 & ADB 디버깅 영구 인증(만료 방지) 설정 중..."
    adb -s "$serial" shell "settings put global stay_on_while_plugged_in 7" 2>/dev/null      # USB/AC/무선 충전 중 상시 점등
    adb -s "$serial" shell "settings put system screen_off_timeout 2147483647" 2>/dev/null  # 화면 타임아웃 최대치
    adb -s "$serial" shell "locksettings set-disabled true 2>/dev/null || true"             # 화면 잠금 해제
    adb -s "$serial" shell "settings put secure lockscreen.disabled 1" 2>/dev/null
    adb -s "$serial" shell "wm dismiss-keyguard" 2>/dev/null                                # 현재 켜진 키가드 즉시 해제
    adb -s "$serial" shell "cmd device_state state 3 2>/dev/null || true"                   # 플립 단말기 메인 화면(OPEN) 강제 활성화 (커버화면 SubHome 모드 방지)

    # [핵심] USB 디버깅 7일 자동 인증 해제 방지 (구글 로그인 기기 타임아웃 만료 차단)
    adb -s "$serial" shell "settings put global adb_authorization_timeout 0" 2>/dev/null

    # Host PC 공개키를 단말기 영구 adb_keys 저장소에 동기화 (Root 가용 시)
    local HOST_PUBKEY_FILE="$HOME/.android/adbkey.pub"
    if [ -f "$HOST_PUBKEY_FILE" ] && [ -n "$HAS_SU" ]; then
        local HOST_PUBKEY=$(head -1 "$HOST_PUBKEY_FILE" | tr -d '\r\n')
        if [ -n "$HOST_PUBKEY" ]; then
            adb -s "$serial" shell "su -c '
                mkdir -p /data/misc/adb 2>/dev/null
                touch /data/misc/adb/adb_keys 2>/dev/null
                if ! grep -qF \"$HOST_PUBKEY\" /data/misc/adb/adb_keys 2>/dev/null; then
                    echo \"$HOST_PUBKEY\" >> /data/misc/adb/adb_keys
                fi
                chown system:shell /data/misc/adb/adb_keys 2>/dev/null || chown 1000:2000 /data/misc/adb/adb_keys 2>/dev/null || true
                chmod 640 /data/misc/adb/adb_keys 2>/dev/null || true
            '" 2>/dev/null
        fi
    fi
    echo -e "      ↳ [✓] 화면 잠금 해제 & ADB 영구 인증(timeout=0) 적용 완료"

    # 3. 디스플레이 & 제스처 & 애니메이션 & 저전력 배터리 튜닝
    echo -e "  [*] [3/8] 60Hz 주사율 & 다크모드 & 세로 고정 & 애니메이션 제거 & USB 고속충전 개방..."
    adb -s "$serial" shell "settings put system accelerometer_rotation 0" 2>/dev/null       # 자동 회전 비활성화
    adb -s "$serial" shell "settings put system user_rotation 0" 2>/dev/null                # 0도(세로 Portrait) 고정
    adb -s "$serial" shell "settings put system screen_off_pocket 0" 2>/dev/null            # 오터치 방지 필터 해제
    adb -s "$serial" shell "settings put global window_animation_scale 0" 2>/dev/null       # 윈도우 애니메이션 제거
    adb -s "$serial" shell "settings put global transition_animation_scale 0" 2>/dev/null   # 전환 애니메이션 제거
    adb -s "$serial" shell "settings put global animator_duration_scale 0" 2>/dev/null     # 애니메이터 제거

    # 저전력 다크모드 + 60Hz + 고속충전
    adb -s "$serial" shell "cmd uimode night yes" 2>/dev/null                               # 다크모드
    adb -s "$serial" shell "settings put system peak_refresh_rate 60.0" 2>/dev/null         # 60Hz
    adb -s "$serial" shell "settings put system min_refresh_rate 60.0" 2>/dev/null
    adb -s "$serial" shell "settings put system screen_brightness 100" 2>/dev/null          # 밝기 100
    adb -s "$serial" shell "settings put system haptic_feedback_enabled 0" 2>/dev/null      # 햅틱 진동 OFF
    adb -s "$serial" shell "settings put system touch_vibration_enabled 0" 2>/dev/null
    adb -s "$serial" shell "settings put system sound_effects_enabled 0" 2>/dev/null
    adb -s "$serial" shell "settings put system vibration_feedback_intensity 0" 2>/dev/null
    adb -s "$serial" shell "svc nfc disable 2>/dev/null || settings put secure nfc_on 0" 2>/dev/null # NFC 차단
    adb -s "$serial" shell "svc bluetooth disable 2>/dev/null || true"

    # 접근성 TalkBack / TTS 음성 안내 및 시스템 음향/버튼/바로가기 영구 박멸
    adb -s "$serial" shell "
        pm uninstall -k --user 0 com.samsung.android.accessibility.talkback 2>/dev/null || true
        pm uninstall -k --user 0 com.google.android.marvin.talkback 2>/dev/null || true
        pm uninstall -k --user 0 com.google.audio.hearing.visualization.accessibility.scribe 2>/dev/null || true
        pm uninstall -k --user 0 com.samsung.accessibility 2>/dev/null || true
        pm uninstall -k --user 0 com.samsung.SMT 2>/dev/null || true
        pm uninstall -k --user 0 com.google.android.tts 2>/dev/null || true
        settings put system all_sound_off 1 2>/dev/null || true
        settings put system sound_effects_enabled 0 2>/dev/null || true
        settings put system haptic_feedback_enabled 0 2>/dev/null || true
        settings put secure enabled_accessibility_services '' 2>/dev/null || true
        settings put secure accessibility_shortcut_target_service '' 2>/dev/null || true
        settings put secure accessibility_button_targets '' 2>/dev/null || true
        settings put secure accessibility_button_mode 0 2>/dev/null || true
        settings put secure accessibility_shortcut_on_lock_screen 0 2>/dev/null || true
        settings put secure accessibility_shortcut_dialog_shown 1 2>/dev/null || true
        settings put secure accessibility_display_magnification_navbar_enabled 0 2>/dev/null || true
        settings put secure accessibility_enabled 0 2>/dev/null || true
        cmd audio set-stream-volume 1 0 0 2>/dev/null || true
        cmd audio set-stream-volume 2 0 0 2>/dev/null || true
        cmd audio set-stream-volume 3 0 0 2>/dev/null || true
        cmd audio set-stream-volume 5 0 0 2>/dev/null || true
        cmd media_session volume --stream 9 --set 0 2>/dev/null || true
        cmd media_session volume --stream 3 --set 0 2>/dev/null || true
        cmd media_session volume --stream 1 --set 0 2>/dev/null || true
        cmd media_session volume --stream 5 --set 0 2>/dev/null || true
        cmd media_session volume --stream 2 --set 0 2>/dev/null || true
    " 2>/dev/null

    # 긴급 재난문자 / 안전 안내 문자 팝업 및 백그라운드 알림 영구 차단
    echo -e "  [*] [3-1] 긴급 재난문자/안전안내문자 수신 및 전체화면 팝업 영구 차단..."
    adb -s "$serial" shell "
        pm disable-user --user 0 com.google.android.cellbroadcastreceiver 2>/dev/null || true
        pm disable-user --user 0 com.google.android.cellbroadcastservice 2>/dev/null || true
        pm disable-user --user 0 com.google.android.overlay.modules.cellbroadcastreceiver 2>/dev/null || true
        pm disable-user --user 0 com.google.android.overlay.modules.cellbroadcastservice 2>/dev/null || true
        pm disable-user --user 0 com.sec.cellbroadcastreceiver 2>/dev/null || true
        appops set com.google.android.cellbroadcastreceiver POST_NOTIFICATION ignore 2>/dev/null || true
        appops set com.google.android.cellbroadcastreceiver SYSTEM_ALERT_WINDOW ignore 2>/dev/null || true
        appops set com.google.android.cellbroadcastservice POST_NOTIFICATION ignore 2>/dev/null || true
        am force-stop com.google.android.cellbroadcastreceiver 2>/dev/null || true
        am force-stop com.google.android.cellbroadcastservice 2>/dev/null || true
    " 2>/dev/null

    if [ -n "$HAS_SU" ]; then
        adb -s "$serial" shell "su -c 'echo 1 > /sys/class/power_supply/battery/batt_high_current_usb'" 2>/dev/null
    fi

    # 4. 안티 디텍션 무선 가드 & 디바이스 고유 지문 부여
    echo -e "  [*] [4/8] 블루투스 고유명칭 부여 & Wi-Fi/BLE/Nearby 백그라운드 탐색 차단 & 커널 ARP/EFS 잠금..."
    adb -s "$serial" shell "settings put secure bluetooth_name '$expected_bt_name'" 2>/dev/null
    adb -s "$serial" shell "settings put global device_name '$expected_bt_name'" 2>/dev/null
    adb -s "$serial" shell "settings put global wifi_scan_always_enabled 0" 2>/dev/null
    adb -s "$serial" shell "settings put global ble_scan_always_enabled 0" 2>/dev/null
    adb -s "$serial" shell "settings put system nearby_scanning_enabled 0" 2>/dev/null
    adb -s "$serial" shell "settings put system nearby_scanning_permission_allowed 0" 2>/dev/null
    adb -s "$serial" shell "settings put secure location_mode 3" 2>/dev/null                # 고정밀 위치 모드 3

    if [ -n "$HAS_SU" ]; then
        adb -s "$serial" shell "su -c 'chmod 600 /proc/net/arp 2>/dev/null; chmod 700 /efs/FactoryApp/serial_no 2>/dev/null; chattr +i /efs/FactoryApp/serial_no 2>/dev/null || true'" 2>/dev/null
    fi

    # 5. USB MTP 팝업 차단
    echo -e "  [*] [5/8] USB MTP 팝업 영구 비활성화..."
    if [ -n "$HAS_SU" ]; then
        adb -s "$serial" shell "su -c 'pm disable-user --user 0 com.samsung.android.mtp 2>/dev/null; pm disable-user --user 0 com.android.mtp 2>/dev/null'" 2>/dev/null
    else
        adb -s "$serial" shell "pm disable-user --user 0 com.samsung.android.mtp 2>/dev/null; pm disable-user --user 0 com.android.mtp 2>/dev/null" 2>/dev/null
    fi
    adb -s "$serial" shell "am force-stop com.samsung.android.mtp" 2>/dev/null

    # 6. 필수 APK 설치 및 환경 구성
    echo -e "  [*] [6/8] 필수 패키지 설치 확인 및 구성..."

    # A. ADBKeyboard
    local kb_pkg=$(adb -s "$serial" shell "pm list packages" 2>/dev/null | grep -w "package:com.android.adbkeyboard")
    if [ -z "$kb_pkg" ]; then
        local KB_APK="$APKS_DIR/ADBKeyboard.apk"
        [ ! -f "$KB_APK" ] && KB_APK="$APKS_DIR/essential_tools/ADBKeyboard.apk"
        if [ -f "$KB_APK" ]; then
            echo -e "      ↳ ADBKeyboard 설치 중..."
            adb -s "$serial" install -r -d "$KB_APK" >/dev/null 2>&1
        fi
    fi
    adb -s "$serial" shell "ime enable com.android.adbkeyboard/.AdbIME" 2>/dev/null
    adb -s "$serial" shell "ime set com.android.adbkeyboard/.AdbIME" 2>/dev/null
    echo -e "      ↳ [✓] ADBKeyboard 기본 입력기로 활성화 완료"

    # B. GPSEmulator
    local gps_pkg=$(adb -s "$serial" shell "pm list packages" 2>/dev/null | grep -w "package:com.rosteam.gpsemulator")
    if [ -z "$gps_pkg" ]; then
        if [ -d "$APKS_DIR/gpsemulator" ] && [ -f "$APKS_DIR/gpsemulator/base.apk" ]; then
            echo -e "      ↳ GPSEmulator 설치 중 (Split APKs)..."
            adb -s "$serial" install-multiple -r -d "$APKS_DIR/gpsemulator/"*.apk >/dev/null 2>&1
            echo -e "      ↳ [✓] GPSEmulator 설치 완료"
        elif [ -f "$APKS_DIR/GPSEmulator.apk" ]; then
            echo -e "      ↳ GPSEmulator 설치 중..."
            adb -s "$serial" install -r -d "$APKS_DIR/GPSEmulator.apk" >/dev/null 2>&1
        fi
    fi
    adb -s "$serial" shell "appops set com.rosteam.gpsemulator android:mock_location allow" 2>/dev/null
    echo -e "      ↳ [✓] GPSEmulator 모의위치 권한 부여 완료"

    # C. WireGuard
    local wg_pkg=$(adb -s "$serial" shell "pm list packages" 2>/dev/null | grep -w "package:com.wireguard.android")
    if [ -z "$wg_pkg" ]; then
        local WG_PATH="$APKS_DIR/wireguard"
        [ ! -d "$WG_PATH" ] && WG_PATH="$APKS_DIR/essential_tools/wireguard"
        if [ -d "$WG_PATH" ] && [ -f "$WG_PATH/base.apk" ]; then
            echo -e "      ↳ WireGuard VPN 설치 중 (Split APKs)..."
            adb -s "$serial" install-multiple -r -d "$WG_PATH/"*.apk >/dev/null 2>&1
            echo -e "      ↳ [✓] WireGuard 설치 완료"
        fi
    else
        echo -e "      ↳ [✓] WireGuard 이미 설치됨"
    fi

    # D. 네이버 앱 (방금 기준: 버전별 디렉토리 naver_app_12.23.81 또는 naver_app_12.22.50)
    local NAVER_TARGET_DIR=""
    if [ -n "$NAVER_APP_VERSION" ] && [ -d "$APKS_DIR/naver_app_${NAVER_APP_VERSION}" ]; then
        NAVER_TARGET_DIR="$APKS_DIR/naver_app_${NAVER_APP_VERSION}"
    elif [ -d "$APKS_DIR/naver_app_12.23.81" ]; then
        NAVER_TARGET_DIR="$APKS_DIR/naver_app_12.23.81"
    elif [ -d "$APKS_DIR/naver_app_12.22.50" ]; then
        NAVER_TARGET_DIR="$APKS_DIR/naver_app_12.22.50"
    elif [ -d "$APKS_DIR/naver_app" ]; then
        NAVER_TARGET_DIR="$APKS_DIR/naver_app"
    fi

    local naver_pkg=$(adb -s "$serial" shell "pm list packages" 2>/dev/null | grep -w "package:com.nhn.android.search")
    if [ -z "$naver_pkg" ]; then
        if [ -n "$NAVER_TARGET_DIR" ] && [ -f "$NAVER_TARGET_DIR/base.apk" ]; then
            local ver_label=$(basename "$NAVER_TARGET_DIR")
            echo -e "      ↳ 네이버 앱 설치 중 (Split APKs: $ver_label)..."
            adb -s "$serial" install-multiple -r -d "$NAVER_TARGET_DIR/"*.apk >/dev/null 2>&1
            echo -e "      ↳ [✓] 네이버 앱 설치 완료 ($ver_label)"
        else
            echo -e "      ${RED}[!] 네이버 앱 APK 디렉토리를 찾을 수 없습니다: $NAVER_TARGET_DIR${NC}"
        fi
    else
        local naver_ver=$(adb -s "$serial" shell "dumpsys package com.nhn.android.search 2>/dev/null" | awk -F'=' '/versionName=/ {print $2; exit}' | tr -d '\r\n')
        echo -e "      ↳ [✓] 네이버 앱 이미 설치됨 (v$naver_ver)"
    fi

    # E. Chrome 브라우저
    local chrome_pkg=$(adb -s "$serial" shell "pm list packages" 2>/dev/null | grep -w "package:com.android.chrome")
    if [ -z "$chrome_pkg" ]; then
        if [ -d "$APKS_DIR/browsers/chrome" ] && [ -f "$APKS_DIR/browsers/chrome/base.apk" ]; then
            echo -e "      ↳ Chrome 설치 중 (Split APKs)..."
            adb -s "$serial" install-multiple -r -d "$APKS_DIR/browsers/chrome/"*.apk >/dev/null 2>&1
            echo -e "      ↳ [✓] Chrome 설치 완료"
        fi
    else
        local chrome_ver=$(adb -s "$serial" shell "dumpsys package com.android.chrome 2>/dev/null" | awk -F'=' '/versionName=/ {print $2; exit}' | tr -d '\r\n')
        echo -e "      ↳ [✓] Chrome 이미 설치됨 (v$chrome_ver)"
    fi
    # Chrome 접근성 DOM 렌더러 플래그 및 권한 사전 부여
    adb -s "$serial" shell "su -c 'echo \"chrome --force-renderer-accessibility --no-first-run --disable-fre\" > /data/local/tmp/chrome-command-line && chmod 777 /data/local/tmp/chrome-command-line && am set-debug-app --persistent com.android.chrome'" 2>/dev/null || true
    adb -s "$serial" shell "pm grant com.android.chrome android.permission.POST_NOTIFICATIONS 2>/dev/null || true"
    adb -s "$serial" shell "pm grant com.android.chrome android.permission.ACCESS_FINE_LOCATION 2>/dev/null || true"
    adb -s "$serial" shell "pm grant com.android.chrome android.permission.ACCESS_COARSE_LOCATION 2>/dev/null || true"

    # F. Firefox 브라우저
    local ff_pkg=$(adb -s "$serial" shell "pm list packages" 2>/dev/null | grep -w "package:org.mozilla.firefox")
    if [ -z "$ff_pkg" ]; then
        if [ -d "$APKS_DIR/browsers/firefox" ] && [ -f "$APKS_DIR/browsers/firefox/base.apk" ]; then
            echo -e "      ↳ Firefox 설치 중 (Split APKs)..."
            adb -s "$serial" install-multiple -r -d "$APKS_DIR/browsers/firefox/"*.apk >/dev/null 2>&1
            echo -e "      ↳ [✓] Firefox 설치 완료"
        fi
    else
        local ff_ver=$(adb -s "$serial" shell "dumpsys package org.mozilla.firefox 2>/dev/null" | awk -F'=' '/versionName=/ {print $2; exit}' | tr -d '\r\n')
        echo -e "      ↳ [✓] Firefox 이미 설치됨 (v$ff_ver)"
    fi
    adb -s "$serial" shell "pm grant org.mozilla.firefox android.permission.POST_NOTIFICATIONS 2>/dev/null || true"

    # G. Whale 브라우저
    local whale_pkg=$(adb -s "$serial" shell "pm list packages" 2>/dev/null | grep -w "package:com.naver.whale")
    if [ -z "$whale_pkg" ]; then
        if [ -d "$APKS_DIR/browsers/whale" ] && [ -f "$APKS_DIR/browsers/whale/base.apk" ]; then
            echo -e "      ↳ Whale 설치 중 (Split APKs)..."
            adb -s "$serial" install-multiple -r -d "$APKS_DIR/browsers/whale/"*.apk >/dev/null 2>&1
            echo -e "      ↳ [✓] Whale 설치 완료"
        fi
    else
        local whale_ver=$(adb -s "$serial" shell "dumpsys package com.naver.whale 2>/dev/null" | awk -F'=' '/versionName=/ {print $2; exit}' | tr -d '\r\n')
        echo -e "      ↳ [✓] Whale 이미 설치됨 (v$whale_ver)"
    fi
    adb -s "$serial" shell "pm grant com.naver.whale android.permission.POST_NOTIFICATIONS 2>/dev/null || true"

    # H. Samsung Internet 브라우저
    local samsung_pkg=$(adb -s "$serial" shell "pm list packages" 2>/dev/null | grep -w "package:com.sec.android.app.sbrowser")
    if [ -z "$samsung_pkg" ]; then
        if [ -d "$APKS_DIR/browsers/samsung" ] && [ -f "$APKS_DIR/browsers/samsung/base.apk" ]; then
            echo -e "      ↳ Samsung Internet 설치 중..."
            adb -s "$serial" install -r -d "$APKS_DIR/browsers/samsung/base.apk" >/dev/null 2>&1
            echo -e "      ↳ [✓] Samsung Internet 설치 완료"
        fi
    else
        local samsung_ver=$(adb -s "$serial" shell "dumpsys package com.sec.android.app.sbrowser 2>/dev/null" | awk -F'=' '/versionName=/ {print $2; exit}' | tr -d '\r\n')
        echo -e "      ↳ [✓] Samsung Internet 이미 설치됨 (v$samsung_ver)"
    fi
    adb -s "$serial" shell "pm grant com.sec.android.app.sbrowser android.permission.POST_NOTIFICATIONS 2>/dev/null || true"

    # 7. 권한 정제 & 배터리 최적화 제외 (안티 디텍션 지문 방어)
    echo -e "  [*] [7/8] 런타임 권한 정제 및 BSSID 유출 차단..."
    adb -s "$serial" shell "pm grant com.nhn.android.search android.permission.POST_NOTIFICATIONS 2>/dev/null || true"
    adb -s "$serial" shell "dumpsys deviceidle whitelist +com.nhn.android.search" 2>/dev/null
    adb -s "$serial" shell "dumpsys deviceidle whitelist +com.wireguard.android" 2>/dev/null

    # [핵심] 위치 권한 영구 박탈 & AppOps 차단 (WifiManager BSSID 작업실 누출 방어)
    adb -s "$serial" shell "pm revoke com.nhn.android.search android.permission.ACCESS_FINE_LOCATION 2>/dev/null || true"
    adb -s "$serial" shell "pm revoke com.nhn.android.search android.permission.ACCESS_COARSE_LOCATION 2>/dev/null || true"
    adb -s "$serial" shell "cmd appops set com.nhn.android.search FINE_LOCATION ignore 2>/dev/null || true"
    adb -s "$serial" shell "cmd appops set com.nhn.android.search COARSE_LOCATION ignore 2>/dev/null || true"
    adb -s "$serial" shell "cmd appops set com.nhn.android.search MOCK_LOCATION ignore 2>/dev/null || true"
    echo -e "      ↳ [✓] 네이버 앱 위치 권한 박탈 및 AppOps ignore 완료"

    # [핵심] 신규 설치된 네이버 앱 및 브라우저 프로세스를 Magisk DenyList에 최종 등록
    if [ -n "$HAS_SU" ]; then
        adb -s "$serial" shell "su -c '
            magisk --denylist add com.nhn.android.search 2>/dev/null || true
            magisk --denylist add com.nhn.android.search com.nhn.android.search:channel 2>/dev/null || true
            magisk --denylist add com.nhn.android.search com.nhn.android.search:core 2>/dev/null || true
            magisk --denylist add com.naver.whale 2>/dev/null || true
            magisk --denylist add org.mozilla.firefox 2>/dev/null || true
            magisk --denylist add com.sec.android.app.sbrowser 2>/dev/null || true
        '" 2>/dev/null
        echo -e "      ↳ [✓] 신규 설치 앱 Magisk DenyList 격리 등록 완료"
    fi

    # 8. 골든 브라우저 프리셋 배포, 프로필 저장소 생성 및 홈 화면 안착
    echo -e "  [*] [8/8] 골든 브라우저 프리셋 배포 및 홈 화면 안착..."
    local GOLDEN_DIR="$PROJECT_ROOT/src/modules/browser/golden_prefs"
    [ ! -d "$GOLDEN_DIR" ] && GOLDEN_DIR="$PROJECT_ROOT/backups/legacy_root_backup_20261006/src/modules/browser/golden_prefs"
    if [ -d "$GOLDEN_DIR" ]; then
        adb -s "$serial" shell "mkdir -p /data/local/tmp/golden_browser_prefs" 2>/dev/null
        for b in chrome firefox whale samsung; do
            if [ -f "$GOLDEN_DIR/$b/${b}_prefs.tar.gz" ]; then
                adb -s "$serial" push "$GOLDEN_DIR/$b/${b}_prefs.tar.gz" "/data/local/tmp/golden_browser_prefs/${b}_prefs.tar.gz" >/dev/null 2>&1
            fi
        done
        adb -s "$serial" shell "chmod -R 777 /data/local/tmp/golden_browser_prefs" 2>/dev/null
        echo -e "      ↳ [✓] 4대 브라우저 온보딩 영구 차단 골든 프리셋 주입 완료"
    fi

    if [ -n "$HAS_SU" ]; then
        adb -s "$serial" shell "su -c 'mkdir -p /data/local/tmp/profile_storage && chmod 777 /data/local/tmp/profile_storage'" 2>/dev/null
    else
        adb -s "$serial" shell "mkdir -p /data/local/tmp/profile_storage" 2>/dev/null
    fi

    # 9. Frida-Server 배포 및 백그라운드 데몬 기동
    local FRIDA_BIN="$PROJECT_ROOT/install/bin/frida-server"
    [ ! -f "$FRIDA_BIN" ] && FRIDA_BIN="$PROJECT_ROOT/bin/frida-server"
    if [ -f "$FRIDA_BIN" ]; then
        local frida_ps=$(adb -s "$serial" shell "ps -A" 2>/dev/null | grep -w "frida-server")
        if [ -z "$frida_ps" ]; then
            echo -e "      ↳ frida-server 배포 및 기동 중..."
            adb -s "$serial" push "$FRIDA_BIN" "/data/local/tmp/frida-server" >/dev/null 2>&1
            adb -s "$serial" shell "su -c 'chmod 755 /data/local/tmp/frida-server && /data/local/tmp/frida-server -D &'" 2>/dev/null
            echo -e "      ↳ [✓] frida-server 기동 완료"
        else
            echo -e "      ↳ [✓] frida-server 이미 실행 중"
        fi
    fi

    adb -s "$serial" shell "input keyevent 224" 2>/dev/null  # WAKEUP
    adb -s "$serial" shell "wm dismiss-keyguard" 2>/dev/null # DISMISS KEYGUARD (NO MENU POPUP)
    adb -s "$serial" shell "input keyevent 3" 2>/dev/null    # HOME

    echo -e "${GREEN}[✓] $serial 단말기 초기화 및 안티디텍션 패치 완료!${NC}"
}

for dev in $DEVICES; do
    init_single_device "$dev"
done

echo -e "\n${CYAN}====================================================================================================================${NC}"
echo -e "${GREEN} 🎉 모든 대상 단말기 초기화 및 패치가 성공적으로 완료되었습니다!${NC}"
echo -e "${CYAN}====================================================================================================================${NC}\n"
