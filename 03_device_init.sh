#!/usr/bin/env bash

# ========================================================================================
# [03 단계] N-Shop Macro Android Phone Farm Device Initializer (03_device_init.sh)
# ========================================================================================
# - 단말기 화면 잠금 완전 해제 (재부팅 시 화면 꺼짐/잠김 방지)
# - USB/충전 중 상시 켜짐 (stay_on_while_plugged_in 7)
# - 세로 화면 고정 및 오터치 방지 해제, UI 애니메이션 제거, 60Hz, 다크모드, USB고속충전
# - 블루투스/디바이스 고유 명칭 부여 (Galaxy-ZFlip3-<시리얼접미사>)
# - 주변 Wi-Fi/BLE/Nearby 백그라운드 탐색 차단 (0)
# - 커널 ARP 테이블(600) 및 EFS 시리얼(700) 보안 잠금
# - 고정밀 GPS 위치 모드(3) 및 GPSEmulator 모의위치 허용
# - 필수 앱 자동 설치 (ADBKeyboard, GPSEmulator, WireGuard, 네이버 앱 Split APK)
# - ADBKeyboard 기본 IME 등록 및 활성화
# - 네이버 앱 위치 권한(BSSID) 박탈 및 배터리 절전 예외 등록
# - Magisk DenyList 강제 활성화 및 네이버 앱 프로세스 격리 등록
# ========================================================================================

BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
APKS_DIR="$BASE_DIR/apks"

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
if [ ! -d "$APKS_DIR/naver_app" ] && [ -f "$APKS_DIR/naver_app_latest.tar.gz" ]; then
    echo -e "${YELLOW}[*] naver_app_latest.tar.gz 압축 해제 중...${NC}"
    mkdir -p "$APKS_DIR/naver_app"
    tar -xzf "$APKS_DIR/naver_app_latest.tar.gz" -C "$APKS_DIR/naver_app"
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
        '" 2>/dev/null
        echo -e "      ↳ [✓] Magisk DenyList 강제 활성화 및 네이버 앱/GMS 격리 등록 완료"
    else
        echo -e "  ${YELLOW}[⚠️] Root 권한을 찾을 수 없습니다. 일반 ADB 명령으로 진행합니다.${NC}"
    fi

    # 2. 화면 잠금 완전 해제 & 재부팅 시 잠김/꺼짐 방지
    echo -e "  [*] [2/8] 화면 잠금 비활성화 및 상시 켜짐(Stay-Awake) 설정 중..."
    adb -s "$serial" shell "settings put global stay_on_while_plugged_in 7" 2>/dev/null      # USB/AC/무선 충전 중 상시 점등
    adb -s "$serial" shell "settings put system screen_off_timeout 2147483647" 2>/dev/null  # 화면 타임아웃 최대치
    adb -s "$serial" shell "locksettings set-disabled true 2>/dev/null || true"             # 화면 잠금 해제
    adb -s "$serial" shell "settings put secure lockscreen.disabled 1" 2>/dev/null
    adb -s "$serial" shell "wm dismiss-keyguard" 2>/dev/null                                # 현재 켜진 키가드 즉시 해제
    adb -s "$serial" shell "cmd device_state state 3 2>/dev/null || true"                   # 플립 단말기 메인 화면(OPEN) 강제 활성화 (커버화면 SubHome 모드 방지)

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
        local GPS_APK="$APKS_DIR/GPSEmulator.apk"
        [ ! -f "$GPS_APK" ] && GPS_APK="$APKS_DIR/essential_tools/GPSEmulator.apk"
        if [ -f "$GPS_APK" ]; then
            echo -e "      ↳ GPSEmulator 설치 중..."
            adb -s "$serial" install -r -d "$GPS_APK" >/dev/null 2>&1
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

    # D. 네이버 앱
    local naver_pkg=$(adb -s "$serial" shell "pm list packages" 2>/dev/null | grep -w "package:com.nhn.android.search")
    if [ -z "$naver_pkg" ]; then
        if [ -d "$APKS_DIR/naver_app" ] && [ -f "$APKS_DIR/naver_app/base.apk" ]; then
            echo -e "      ↳ 네이버 앱 설치 중 (Split APKs)..."
            adb -s "$serial" install-multiple -r -d "$APKS_DIR/naver_app/"*.apk >/dev/null 2>&1
            echo -e "      ↳ [✓] 네이버 앱 설치 완료"
        fi
    else
        local naver_ver=$(adb -s "$serial" shell "dumpsys package com.nhn.android.search 2>/dev/null" | awk -F'=' '/versionName=/ {print $2; exit}' | tr -d '\r\n')
        echo -e "      ↳ [✓] 네이버 앱 이미 설치됨 (v$naver_ver)"
    fi

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

    # 8. 온디바이스 프로필 저장소 및 홈 화면 복귀
    echo -e "  [*] [8/8] 프로필 저장소 생성 및 홈 화면 안착..."
    if [ -n "$HAS_SU" ]; then
        adb -s "$serial" shell "su -c 'mkdir -p /data/local/tmp/profile_storage && chmod 777 /data/local/tmp/profile_storage'" 2>/dev/null
    else
        adb -s "$serial" shell "mkdir -p /data/local/tmp/profile_storage" 2>/dev/null
    fi
    adb -s "$serial" shell "input keyevent 224" 2>/dev/null  # WAKEUP
    adb -s "$serial" shell "input keyevent 82" 2>/dev/null   # MENU
    adb -s "$serial" shell "input keyevent 3" 2>/dev/null    # HOME

    echo -e "${GREEN}[✓] $serial 단말기 초기화 및 안티디텍션 패치 완료!${NC}"
}

for dev in $DEVICES; do
    init_single_device "$dev"
done

echo -e "\n${CYAN}====================================================================================================================${NC}"
echo -e "${GREEN} 🎉 모든 대상 단말기 초기화 및 패치가 성공적으로 완료되었습니다!${NC}"
echo -e "${CYAN}====================================================================================================================${NC}\n"
