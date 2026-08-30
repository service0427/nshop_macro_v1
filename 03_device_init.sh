#!/usr/bin/env bash

# ========================================================================================
# [03 단계] N-Shop Macro Android Phone Farm Device Initializer (03_device_init.sh)
# ========================================================================================
# - 단말기 화면 잠금 완전 해제 (재부팅 시 화면 꺼짐/잠김 방지)
# - USB/충전 중 상시 켜짐 (stay_on_while_plugged_in 7)
# - 세로 화면 고정 및 오터치 방지 해제, UI 애니메이션 제거
# - 필수 앱 자동 설치 (네이버 앱 Split APK, WireGuard, ADBKeyboard, GPSEmulator)
# - 권한 승인 / 배터리 최적화 예외 / ADBKeyboard 기본 IME 등록
# ========================================================================================

BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
APKS_DIR="$BASE_DIR/apks"

CYAN="\e[1;36m"
GREEN="\e[1;32m"
YELLOW="\e[1;33m"
RED="\e[1;31m"
NC="\e[0m"

echo -e "${CYAN}==========================================================================${NC}"
echo -e "${CYAN} 📱 [03단계] N-Shop Macro Phone Farm 단말기 일괄 초기화 (03_device_init.sh)${NC}"
echo -e "${CYAN}==========================================================================${NC}"

# 0. 압축 파일 자동 압축 해제 (필요 시)
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

# 대상 단말기 지정 ($1) 또는 전체 연결 단말기 자동 감지
TARGET_DEVICE=$1

if [ -z "$TARGET_DEVICE" ]; then
    echo -e "${YELLOW}[*] 대상 단말기가 지정되지 않았습니다. 연결된 모든 온라인 단말기를 초기화합니다...${NC}"
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
    echo -e "\n${CYAN}--------------------------------------------------------------------------${NC}"
    echo -e "${GREEN}[📱 단말기 초기화 시작: $serial]${NC}"
    echo -e "${CYAN}--------------------------------------------------------------------------${NC}"

    # 1. Root (su) 권한 확인
    HAS_SU=$(adb -s "$serial" shell "which su" 2>/dev/null | tr -d '\r')
    if [ -z "$HAS_SU" ]; then
        HAS_SU=$(adb -s "$serial" shell "ls /system/bin/su /system/xbin/su /sbin/su 2>/dev/null" | head -1 | tr -d '\r')
    fi

    if [ -n "$HAS_SU" ]; then
        echo -e "  [✓] Root (su) 권한 확인 완료"
    else
        echo -e "  ${YELLOW}[⚠️] Root 권한을 찾을 수 없습니다. 일반 ADB 명령으로 진행합니다.${NC}"
    fi

    # 2. [핵심] 화면 잠금 완전 해제 & 재부팅 시 잠김/꺼짐 방지
    echo -e "  [*] [1/6] 화면 잠금 비활성화 및 상시 켜짐(Stay-Awake) 설정 중..."
    adb -s "$serial" shell "settings put global stay_on_while_plugged_in 7" 2>/dev/null      # USB/AC/무선 충전 중 상시 점등
    adb -s "$serial" shell "settings put system screen_off_timeout 2147483647" 2>/dev/null  # 화면 타임아웃 최대치
    adb -s "$serial" shell "locksettings set-disabled true" 2>/dev/null                     # 화면 잠금 해제
    adb -s "$serial" shell "settings put secure lockscreen.disabled 1" 2>/dev/null
    adb -s "$serial" shell "settings put global require_keyguard_disabled 1" 2>/dev/null
    adb -s "$serial" shell "wm dismiss-keyguard" 2>/dev/null                                # 현재 켜진 키가드 즉시 해제

    # 3. 디스플레이 & 제스처 & 애니메이션 최적화
    echo -e "  [*] [2/6] 세로 화면 고정 & 오터치 방지 해제 & UI 애니메이션 제거 중..."
    adb -s "$serial" shell "settings put system accelerometer_rotation 0" 2>/dev/null       # 자동 회전 비활성화
    adb -s "$serial" shell "settings put system user_rotation 0" 2>/dev/null                # 0도(세로 Portrait) 고정
    adb -s "$serial" shell "settings put system screen_off_pocket 0" 2>/dev/null            # 오터치 방지 필터 해제
    adb -s "$serial" shell "settings put global window_animation_scale 0" 2>/dev/null       # 윈도우 애니메이션 제거
    adb -s "$serial" shell "settings put global transition_animation_scale 0" 2>/dev/null   # 전환 애니메이션 제거
    adb -s "$serial" shell "settings put global animator_duration_scale 0" 2>/dev/null     # 애니메이터 제거

    # 4. 필수 APK 설치 (ADBKeyboard, GPSEmulator, WireGuard, 네이버 앱)
    echo -e "  [*] [3/6] 필수 패키지 설치 확인 및 배포 중..."

    # A. ADBKeyboard 설치 및 기본 IME 활성화
    if ! adb -s "$serial" shell "pm list packages" | grep -q "com.android.adbkeyboard"; then
        KB_APK="$APKS_DIR/adbkeyboard/ADBKeyboard.apk"
        [ ! -f "$KB_APK" ] && KB_APK="$APKS_DIR/ADBKeyboard.apk"
        [ ! -f "$KB_APK" ] && KB_APK="$APKS_DIR/essential_tools/ADBKeyboard.apk"
        if [ -f "$KB_APK" ]; then
            echo -e "      ↳ ADBKeyboard 설치 중..."
            adb -s "$serial" install -r -d "$KB_APK" >/dev/null 2>&1
        fi
    fi
    adb -s "$serial" shell "ime enable com.android.adbkeyboard/.AdbIME" 2>/dev/null
    adb -s "$serial" shell "ime set com.android.adbkeyboard/.AdbIME" 2>/dev/null
    echo -e "      ↳ [✓] ADBKeyboard 기본 입력기로 활성화 완료"

    # B. GPSEmulator 설치 (있는 경우)
    GPS_APK="$APKS_DIR/GPSEmulator.apk"
    [ ! -f "$GPS_APK" ] && GPS_APK="$APKS_DIR/essential_tools/GPSEmulator.apk"
    if [ -f "$GPS_APK" ] && ! adb -s "$serial" shell "pm list packages" | grep -q "com.rosteam.gpsemulator"; then
        echo -e "      ↳ GPSEmulator 설치 중..."
        adb -s "$serial" install -r -d "$GPS_APK" >/dev/null 2>&1
        adb -s "$serial" shell "appops set com.rosteam.gpsemulator android:mock_location allow" 2>/dev/null
    fi

    # C. WireGuard 설치
    if ! adb -s "$serial" shell "pm list packages" | grep -q "com.wireguard.android"; then
        WG_PATH="$APKS_DIR/wireguard"
        [ ! -d "$WG_PATH" ] && WG_PATH="$APKS_DIR/essential_tools/wireguard"
        if [ -d "$WG_PATH" ] && [ -f "$WG_PATH/base.apk" ]; then
            echo -e "      ↳ WireGuard VPN 설치 중 (Split APKs)..."
            adb -s "$serial" install-multiple -r -d "$WG_PATH/"*.apk >/dev/null 2>&1
            echo -e "      ↳ [✓] WireGuard 설치 완료"
        fi
    else
        echo -e "      ↳ [✓] WireGuard 이미 설치됨"
    fi

    # D. 네이버 앱 설치
    if ! adb -s "$serial" shell "pm list packages" | grep -q "com.nhn.android.search"; then
        if [ -d "$APKS_DIR/naver_app" ] && [ -f "$APKS_DIR/naver_app/base.apk" ]; then
            echo -e "      ↳ 네이버 앱 설치 중 (Split APKs)..."
            adb -s "$serial" install-multiple -r -d "$APKS_DIR/naver_app/"*.apk >/dev/null 2>&1
            echo -e "      ↳ [✓] 네이버 앱 설치 완료"
        fi
    else
        echo -e "      ↳ [✓] 네이버 앱 이미 설치됨"
    fi

    # 5. 권한 부여 & 배터리 최적화 제외
    echo -e "  [*] [4/6] 런타임 권한 승인 및 배터리 절전 예외 등록 중..."
    adb -s "$serial" shell "pm grant com.nhn.android.search android.permission.ACCESS_FINE_LOCATION" 2>/dev/null
    adb -s "$serial" shell "pm grant com.nhn.android.search android.permission.ACCESS_COARSE_LOCATION" 2>/dev/null
    adb -s "$serial" shell "pm grant com.nhn.android.search android.permission.POST_NOTIFICATIONS" 2>/dev/null
    adb -s "$serial" shell "dumpsys deviceidle whitelist +com.nhn.android.search" 2>/dev/null
    adb -s "$serial" shell "dumpsys deviceidle whitelist +com.wireguard.android" 2>/dev/null

    # 6. 온디바이스 프로필 저장소 디렉터리 생성
    echo -e "  [*] [5/6] 온디바이스 프로필 저장소 (/data/local/tmp/profile_storage) 생성..."
    if [ -n "$HAS_SU" ]; then
        adb -s "$serial" shell "su -c 'mkdir -p /data/local/tmp/profile_storage && chmod 777 /data/local/tmp/profile_storage'" 2>/dev/null
    else
        adb -s "$serial" shell "mkdir -p /data/local/tmp/profile_storage" 2>/dev/null
    fi

    # 7. 화면 켜기 & 홈 화면으로 복귀
    echo -e "  [*] [6/6] 키가드 해제 및 런처 안착 확인..."
    adb -s "$serial" shell "input keyevent 224" 2>/dev/null  # WAKEUP
    adb -s "$serial" shell "input keyevent 82" 2>/dev/null   # MENU
    adb -s "$serial" shell "input keyevent 3" 2>/dev/null    # HOME

    echo -e "${GREEN}[✓] $serial 단말기 초기 설정 완료!${NC}"
}

for dev in $DEVICES; do
    init_single_device "$dev"
done

echo -e "\n${CYAN}==========================================================================${NC}"
echo -e "${GREEN} 🎉 모든 대상 단말기 초기화가 성공적으로 완료되었습니다!${NC}"
echo -e "${CYAN}==========================================================================${NC}\n"
