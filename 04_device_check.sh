#!/usr/bin/env bash

# ========================================================================================
# [04 단계] N-Shop Macro Android Device All-in-One Comprehensive Health Check (04_device_check.sh)
# ========================================================================================
# - 하드웨어 & OS: 모델명, 안드로이드 버전, RAM, 남은 스토리지 용량
# - 구글 계정: 실사용 Google 로그인 상태(유령단말기 방지), GMS 프레임워크
# - 배터리 & 파워: 실시간 잔량, 온도, 고속 USB 충전 개방 상태
# - 화면 & 잠금: 상시 점등(Stay-Awake 7), 화면 잠금 해제(1), 세로 고정(0), 60Hz, 다크모드
# - 필수 앱 & IME: 네이버 앱(버전), WireGuard, GPSEmulator, ADBKeyboard(기본 IME)
# - 안티 디텍션 방어: BSSID 유출 방어(위치 권한 박탈), 블루투스 고유명, 무선 스캔 차단,
#                    커널 ARP 테이블(600), EFS 시리얼(700), Magisk DenyList 프로세스 격리
# ========================================================================================

CYAN="\e[1;36m"
GREEN="\e[1;32m"
YELLOW="\e[1;33m"
RED="\e[1;31m"
BOLD="\e[1m"
DIM="\e[2m"
NC="\e[0m"

echo -e "${CYAN}====================================================================================================================${NC}"
echo -e "${CYAN} 🔍 [04단계] N-Shop Macro Phone Farm 단말기 종합 정밀 진단 시스템 (04_device_check.sh)${NC}"
echo -e "${CYAN}====================================================================================================================${NC}"

TARGET_DEVICE=$1

if [ -z "$TARGET_DEVICE" ]; then
    DEVICES=$(adb devices | grep -w "device" | awk '{print $1}')
else
    DEVICES=$TARGET_DEVICE
fi

if [ -z "$DEVICES" ]; then
    echo -e "${RED}[-] 연결된 온라인 단말기가 없습니다. USB 케이블 및 USB 디버깅 상태를 확인하세요.${NC}"
    exit 1
fi

TOTAL_COUNT=0
READY_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

declare -a SUMMARY_ROWS

for serial in $DEVICES; do
    TOTAL_COUNT=$((TOTAL_COUNT + 1))
    local_fails=0
    local_warns=0

    echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}📱 [단말기 정밀 진단: $serial]${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    # 1. 하드웨어 및 OS 정보
    MODEL=$(adb -s "$serial" shell "getprop ro.product.model" 2>/dev/null | tr -d '\r\n')
    OS_VER=$(adb -s "$serial" shell "getprop ro.build.version.release" 2>/dev/null | tr -d '\r\n')
    SDK_VER=$(adb -s "$serial" shell "getprop ro.build.version.sdk" 2>/dev/null | tr -d '\r\n')
    FREE_STORAGE=$(adb -s "$serial" shell "df -h /data 2>/dev/null | tail -1 | awk '{print \$4}'" | tr -d '\r\n')
    RAM_TOTAL=$(adb -s "$serial" shell "free -m 2>/dev/null | awk '/Mem:/ {print \$2}'" | tr -d '\r\n')
    [ -z "$RAM_TOTAL" ] && RAM_TOTAL=$(adb -s "$serial" shell "cat /proc/meminfo 2>/dev/null | awk '/MemTotal:/ {print int(\$2/1024)}'" | tr -d '\r\n')
    serial_suffix="${serial: -5}"

    # 2. Root (su) 권한 및 Magisk DenyList 은닉 상태 진단
    HAS_SU=$(adb -s "$serial" shell "which su 2>/dev/null || ls /system/bin/su /system/xbin/su /sbin/su /product/bin/su 2>/dev/null" | head -1 | tr -d '\r\n')
    SU_STATUS="⚪ Non-Root (미루팅)"
    SU_HIDE_STATUS="⚪ 해당없음"

    if [ -n "$HAS_SU" ]; then
        SU_STATUS="🟢 Root (su) 가용"

        DENY_STATUS=$(adb -s "$serial" shell "su -c 'magisk --denylist status 2>&1'" 2>/dev/null | tr -d '\r\n')
        DENY_LS=$(adb -s "$serial" shell "su -c 'magisk --denylist ls 2>/dev/null'")

        IS_ENFORCED=0
        if [[ "$DENY_STATUS" =~ [Ee]nforce && ! "$DENY_STATUS" =~ [Nn]ot[[:space:]]+enforce ]]; then
            IS_ENFORCED=1
        fi

        IS_APP_DENIED=0
        if echo "$DENY_LS" | grep -q "com.nhn.android.search"; then
            IS_APP_DENIED=1
        fi

        if [ $IS_ENFORCED -eq 1 ] && [ $IS_APP_DENIED -eq 1 ]; then
            SU_HIDE_STATUS="${GREEN}🟢 PASS (DenyList 격리완료)${NC}"
        else
            SU_HIDE_STATUS="${RED}🔴 FAIL (DenyList 미격리 - su 노출 위험)${NC}"
            local_fails=$((local_fails + 1))
        fi
    fi

    # 3. 구글 계정 & GMS
    G_ACCOUNTS=$(adb -s "$serial" shell "dumpsys account 2>/dev/null" | grep -E "Account \{name=.*type=com\.google\}" | sed -n 's/.*name=\([^,]*\),.*/\1/p' | tr -d '\r')
    G_COUNT=0
    G_ACCOUNT_MASKED=""

    if [ -n "$G_ACCOUNTS" ]; then
        while read -r acc; do
            [ -z "$acc" ] && continue
            G_COUNT=$((G_COUNT + 1))
            user_part="${acc%%@*}"
            domain_part="${acc#*@}"
            masked_user="${user_part:0:3}***"
            if [ -z "$G_ACCOUNT_MASKED" ]; then
                G_ACCOUNT_MASKED="${masked_user}@${domain_part}"
            else
                G_ACCOUNT_MASKED="${G_ACCOUNT_MASKED}, ${masked_user}@${domain_part}"
            fi
        done <<< "$G_ACCOUNTS"
    fi

    G_STATUS="${GREEN}🟢 PASS (로그인: ${G_ACCOUNT_MASKED})${NC}"
    if [ $G_COUNT -eq 0 ]; then
        G_STATUS="${RED}🔴 FAIL (구글 계정 없음 - 유령단말기 위험)${NC}"
        local_fails=$((local_fails + 1))
    fi

    # 4. 배터리 하드웨어 & 전원
    BATT_DUMP=$(adb -s "$serial" shell "dumpsys battery 2>/dev/null")
    BATT_LEVEL=$(echo "$BATT_DUMP" | awk '/^ *level:/ {print $2}' | head -1 | tr -d '\r\n')
    BATT_RAW_TEMP=$(echo "$BATT_DUMP" | awk '/^ *temperature:/ {print $2}' | head -1 | tr -d '\r\n')
    BATT_TEMP=$(awk -v t="$BATT_RAW_TEMP" 'BEGIN {printf "%.1f", t/10}')
    USB_HIGH=$(adb -s "$serial" shell "su -c 'cat /sys/class/power_supply/battery/batt_high_current_usb' 2>/dev/null" | tr -d '\r\n')
    USB_HIGH_STR="⚪ 일반"
    [ "$USB_HIGH" == "1" ] && USB_HIGH_STR="${GREEN}⚡ 고속개방(1500mA)${NC}"

    # 배터리 저잔량 경고
    if [ -n "$BATT_LEVEL" ] && [ "$BATT_LEVEL" -lt 20 ] 2>/dev/null; then
        local_warns=$((local_warns + 1))
    fi

    # 5. 화면 및 잠금 세팅
    STAY_AWAKE=$(adb -s "$serial" shell "settings get global stay_on_while_plugged_in 2>/dev/null" | tr -d '\r\n')
    LOCK_DISABLED=$(adb -s "$serial" shell "settings get secure lockscreen.disabled 2>/dev/null" | tr -d '\r\n')
    ROTATION_VAL=$(adb -s "$serial" shell "settings get system user_rotation 2>/dev/null" | tr -d '\r\n')
    DARK_MODE=$(adb -s "$serial" shell "settings get secure ui_night_mode 2>/dev/null" | tr -d '\r\n')
    REFRESH_RATE=$(adb -s "$serial" shell "settings get system peak_refresh_rate 2>/dev/null" | tr -d '\r\n')

    STAY_STR="${GREEN}🟢 PASS (상시 켜짐: 7)${NC}"
    [ "$STAY_AWAKE" != "7" ] && { STAY_STR="${RED}🔴 FAIL (미설정: $STAY_AWAKE)${NC}"; local_fails=$((local_fails + 1)); }
    LOCK_STR="${GREEN}🟢 PASS (잠금 해제: 1)${NC}"
    [ "$LOCK_DISABLED" != "1" ] && { LOCK_STR="${RED}🔴 FAIL (잠금 켜짐)${NC}"; local_fails=$((local_fails + 1)); }

    FLIP_STATE=$(adb -s "$serial" shell "dumpsys device_state 2>/dev/null | grep mCommittedState" | tr -d '\r\n')
    FLIP_STR="${GREEN}🟢 PASS (메인 화면 OPEN)${NC}"
    if echo "$FLIP_STATE" | grep -q "CLOSE"; then
        FLIP_STR="${YELLOW}🟡 WARN (커버 화면 CLOSE 감지 ➔ OPEN 자동 보정)${NC}"
        adb -s "$serial" shell "cmd device_state state 3" 2>/dev/null || true
    fi

    # 6. 필수 앱 설치 상태 및 버전
    NAVER_VER=$(adb -s "$serial" shell "dumpsys package com.nhn.android.search 2>/dev/null" | awk -F'=' '/versionName=/ {print $2; exit}' | tr -d '\r\n')
    WG_VER=$(adb -s "$serial" shell "dumpsys package com.wireguard.android 2>/dev/null" | awk -F'=' '/versionName=/ {print $2; exit}' | tr -d '\r\n')
    GPS_PKG=$(adb -s "$serial" shell "pm list packages" 2>/dev/null | grep -w "package:com.rosteam.gpsemulator")
    CURRENT_IME=$(adb -s "$serial" shell "settings get secure default_input_method 2>/dev/null" | tr -d '\r\n')

    NAVER_STR="${GREEN}🟢 PASS (v$NAVER_VER)${NC}"
    [ -z "$NAVER_VER" ] && { NAVER_STR="${RED}🔴 FAIL (미설치)${NC}"; local_fails=$((local_fails + 1)); }

    WG_STR="${GREEN}🟢 PASS (v$WG_VER)${NC}"
    [ -z "$WG_VER" ] && { WG_STR="${RED}🔴 FAIL (미설치)${NC}"; local_fails=$((local_fails + 1)); }

    GPS_STR="${GREEN}🟢 PASS (설치됨 & 모의위치 허용)${NC}"
    MOCK_APPOPS=$(adb -s "$serial" shell "appops get com.rosteam.gpsemulator android:mock_location 2>/dev/null" | tr -d '\r\n')
    if [ -z "$GPS_PKG" ]; then
        GPS_STR="${YELLOW}🟡 WARN (미설치)${NC}"
        local_warns=$((local_warns + 1))
    elif ! echo "$MOCK_APPOPS" | grep -qi "allow"; then
        GPS_STR="${YELLOW}🟡 WARN (모의위치 미허용)${NC}"
        local_warns=$((local_warns + 1))
    fi

    KB_STR="${GREEN}🟢 PASS (Default IME 활성화)${NC}"
    if adb -s "$serial" shell "pm list packages" 2>/dev/null | grep -q "com.android.adbkeyboard"; then
        if [[ "$CURRENT_IME" != *"com.android.adbkeyboard"* ]]; then
            KB_STR="${YELLOW}🟡 WARN (설치됨 / 비활성: $CURRENT_IME)${NC}"
            local_warns=$((local_warns + 1))
        fi
    else
        KB_STR="${RED}🔴 FAIL (미설치)${NC}"
        local_fails=$((local_fails + 1))
    fi

    # 7. 안티 디텍션 무선 가드 & 권한 감사
    LOC_PERM_FINE=$(adb -s "$serial" shell "dumpsys package com.nhn.android.search 2>/dev/null" | grep -E "ACCESS_FINE_LOCATION: granted=true")
    BSSID_GUARD="${GREEN}🟢 PASS (위치 권한 완전 박탈 - BSSID 보호)${NC}"
    if [ -n "$LOC_PERM_FINE" ]; then
        BSSID_GUARD="${RED}🔴 FAIL (위치 권한 허용됨 - 작업실 BSSID 유출 위험!)${NC}"
        local_fails=$((local_fails + 1))
    fi

    WIFI_SCAN=$(adb -s "$serial" shell "settings get global wifi_scan_always_enabled 2>/dev/null" | tr -d '\r\n')
    BLE_SCAN=$(adb -s "$serial" shell "settings get global ble_scan_always_enabled 2>/dev/null" | tr -d '\r\n')
    NEARBY_SCAN=$(adb -s "$serial" shell "settings get system nearby_scanning_enabled 2>/dev/null" | tr -d '\r\n')
    SCAN_GUARD="${GREEN}🟢 PASS (모두 차단: 0)${NC}"
    if [ "$WIFI_SCAN" != "0" ] || [ "$BLE_SCAN" != "0" ] || [ "$NEARBY_SCAN" != "0" ]; then
        SCAN_GUARD="${YELLOW}🟡 WARN (스캔 켜짐: wifi=$WIFI_SCAN, ble=$BLE_SCAN, nearby=$NEARBY_SCAN)${NC}"
        local_warns=$((local_warns + 1))
    fi

    BT_NAME=$(adb -s "$serial" shell "settings get secure bluetooth_name" 2>/dev/null | tr -d '\r\n')
    BT_NAME_STR="${GREEN}🟢 PASS ('$BT_NAME')${NC}"
    if [[ "$BT_NAME" == "Galaxy Z Flip3 5G" || -z "$BT_NAME" ]]; then
        BT_NAME_STR="${YELLOW}🟡 WARN (팩토리 기본명: '$BT_NAME')${NC}"
        local_warns=$((local_warns + 1))
    fi

    ARP_PERM=$(adb -s "$serial" shell "stat -c %a /proc/net/arp 2>/dev/null" | tr -d '\r\n')
    ARP_STR="${GREEN}🟢 PASS (600 잠금)${NC}"
    [ "$ARP_PERM" != "600" ] && { ARP_STR="${YELLOW}🟡 WARN (권한: $ARP_PERM, 600 권장)${NC}"; local_warns=$((local_warns + 1)); }

    EFS_PERM=$(adb -s "$serial" shell "su -c 'stat -c %a /efs/FactoryApp/serial_no' 2>/dev/null" | tr -d '\r\n')
    EFS_STR="${GREEN}🟢 PASS (700 잠금)${NC}"
    [ "$EFS_PERM" != "700" ] && { EFS_STR="${YELLOW}🟡 WARN (권한: $EFS_PERM, 700 권장)${NC}"; local_warns=$((local_warns + 1)); }

    # 상세 출력
    echo -e "  ${BOLD}[1] 📦 필수 APK 및 기본 환경${NC}"
    echo -e "      ↳ 네이버 앱:          $NAVER_STR"
    echo -e "      ↳ WireGuard VPN:      $WG_STR"
    echo -e "      ↳ ADBKeyboard:        $KB_STR"
    echo -e "      ↳ GPSEmulator:        $GPS_STR"

    echo -e "\n  ${BOLD}[2] 🔑 구글 계정 & 무결성 은닉${NC}"
    echo -e "      ↳ Google 로그인:      $G_STATUS"
    echo -e "      ↳ Magisk DenyList:    $SU_HIDE_STATUS"

    echo -e "\n  ${BOLD}[3] 🛡️ 안티 디텍션 지문 방어${NC}"
    echo -e "      ↳ 네이버 BSSID 방어:  $BSSID_GUARD"
    echo -e "      ↳ 블루투스 고유명:    $BT_NAME_STR"
    echo -e "      ↳ 주변 무선 스캔:     $SCAN_GUARD"
    echo -e "      ↳ 커널 ARP 라우터:    $ARP_STR"
    echo -e "      ↳ EFS 시리얼 잠금:    $EFS_STR"

    echo -e "\n  ${BOLD}[4] ⚙️ 화면 & 전원 24/7 세팅${NC}"
    echo -e "      ↳ 플립 화면 상태:       $FLIP_STR"
    echo -e "      ↳ 상시 점등(Stay-Awake): $STAY_STR"
    echo -e "      ↳ 화면 잠금 해제:       $LOCK_STR"
    echo -e "      ↳ 배터리 잔량/온도:     ${GREEN}${BATT_LEVEL}%${NC} (${BATT_TEMP}°C) | USB충전: $USB_HIGH_STR"

    # 종합 판정
    verdict=""
    if [ $local_fails -eq 0 ] && [ $local_warns -eq 0 ]; then
        verdict="${GREEN}🟢 완벽 (즉시 투입 가능)${NC}"
        READY_COUNT=$((READY_COUNT + 1))
    elif [ $local_fails -eq 0 ]; then
        verdict="${YELLOW}🟡 주의 (가동 가능, ${local_warns}건 권장)${NC}"
        WARN_COUNT=$((WARN_COUNT + 1))
    else
        verdict="${RED}🔴 불가 (결함 ${local_fails}건 해결 필수)${NC}"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi

    echo -e "\n  ${BOLD}▶ 최종 진단 결과: $verdict${NC}"

    SUMMARY_ROWS+=("$(printf "| %-13s | %-16s | %-12s | %-12s | %-18s | %-20s |" \
        "$serial" "$MODEL" "${BATT_LEVEL}%" "v${NAVER_VER:-미설치}" "$([ $G_COUNT -gt 0 ] && echo "🟢 ${G_COUNT}개 계정" || echo "🔴 미로그인")" "$verdict")")
done

echo -e "\n${CYAN}====================================================================================================================${NC}"
echo -e "${BOLD} 📊 [Phone Farm 전체 단말기 종합 진단 결과표 (04_device_check.sh)]${NC}"
echo -e "${CYAN}====================================================================================================================${NC}"
echo -e "| 단말기 시리얼  | 모델명           | 배터리       | 네이버앱     | 구글 로그인 상태   | 온보딩 종합 판정     |"
echo -e "|---------------|------------------|--------------|--------------|--------------------|----------------------|"
for row in "${SUMMARY_ROWS[@]}"; do
    echo -e "$row"
done
echo -e "${CYAN}====================================================================================================================${NC}"
echo -e " 점검 단말기: ${BOLD}$TOTAL_COUNT 대${NC} ( 🟢 완벽 투입 가능: ${GREEN}$READY_COUNT 대${NC} | 🟡 주의/권장: ${YELLOW}$WARN_COUNT 대${NC} | 🔴 투입 불가: ${RED}$FAIL_COUNT 대${NC} )"

if [ $FAIL_COUNT -gt 0 ]; then
    echo -e "\n${RED}⚠️ 결함이 있는 단말기는 아래 명령어로 즉시 일괄 자동 수정하십시오:${NC}"
    echo -e "   ${GREEN}./03_device_init.sh${NC}\n"
fi
