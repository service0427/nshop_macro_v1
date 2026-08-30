#!/usr/bin/env bash

# ========================================================================================
# [04 단계] N-Shop Macro Android Device All-in-One Comprehensive Health Check (04_device_check.sh)
# ========================================================================================
# - 하드웨어 & OS: 모델명, 안드로이드 버전, RAM, 남은 스토리지 용량
# - 배터리 & 파워: 실시간 잔량, 수명 효율(ASOC), 누적 충방전 사이클, 전압, 온도
# - 화면 & 잠금: 상시 점등(Stay-Awake), 화면 잠금 해제, 세로 고정, 애니메이션
# - 필수 앱 & IME: 네이버 앱(버전), WireGuard, ADBKeyboard 활성화 상태
# - 네트워크 & 권한: 내부 IP, 공인 IP, Root(su) 권한, 배터리 절전 예외
# ========================================================================================

CYAN="\e[1;36m"
GREEN="\e[1;32m"
YELLOW="\e[1;33m"
RED="\e[1;31m"
BOLD="\e[1m"
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
PASS_COUNT=0
WARN_COUNT=0

declare -a SUMMARY_ROWS

for serial in $DEVICES; do
    TOTAL_COUNT=$((TOTAL_COUNT + 1))
    echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}📱 [단말기 정밀 진단: $serial]${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    DEV_WARN=0

    # 1. 하드웨어 및 OS 정보
    MODEL=$(adb -s "$serial" shell "getprop ro.product.model" 2>/dev/null | tr -d '\r\n')
    OS_VER=$(adb -s "$serial" shell "getprop ro.build.version.release" 2>/dev/null | tr -d '\r\n')
    SDK_VER=$(adb -s "$serial" shell "getprop ro.build.version.sdk" 2>/dev/null | tr -d '\r\n')
    FREE_STORAGE=$(adb -s "$serial" shell "df -h /data 2>/dev/null | tail -1 | awk '{print \$4}'" | tr -d '\r\n')
    RAM_TOTAL=$(adb -s "$serial" shell "free -m 2>/dev/null | awk '/Mem:/ {print \$2}'" | tr -d '\r\n')
    [ -z "$RAM_TOTAL" ] && RAM_TOTAL=$(adb -s "$serial" shell "cat /proc/meminfo 2>/dev/null | awk '/MemTotal:/ {print int(\$2/1024)}'" | tr -d '\r\n')

    # 2. Root (su) 권한
    HAS_SU=$(adb -s "$serial" shell "which su 2>/dev/null || ls /system/bin/su /sbin/su 2>/dev/null" | head -1 | tr -d '\r\n')
    SU_STATUS="❌ 미루팅"
    [ -n "$HAS_SU" ] && SU_STATUS="🟢 Root (su) 정상"

    # 3. 배터리 하드웨어 & 수명(ASOC) & 충전
    BATT_DUMP=$(adb -s "$serial" shell "dumpsys battery 2>/dev/null")
    BATT_LEVEL=$(echo "$BATT_DUMP" | awk '/^ *level:/ {print $2}' | head -1 | tr -d '\r\n')
    BATT_RAW_VOLT=$(echo "$BATT_DUMP" | awk '/^ *voltage:/ {print $2}' | head -1 | tr -d '\r\n')
    BATT_VOLT=$(awk -v v="$BATT_RAW_VOLT" 'BEGIN {printf "%.2f", v/1000}')
    BATT_RAW_TEMP=$(echo "$BATT_DUMP" | awk '/^ *temperature:/ {print $2}' | head -1 | tr -d '\r\n')
    BATT_TEMP=$(awk -v t="$BATT_RAW_TEMP" 'BEGIN {printf "%.1f", t/10}')
    BATT_CHG=$(echo "$BATT_DUMP" | awk '/^ *USB powered:/ {print $3}' | head -1 | tr -d '\r\n')

    # 커널 배터리 퓨얼게이지 수명 & 사이클 조회
    ASOC_VAL="?"
    CYCLE_VAL="?"
    FULLCAP_VAL="?"
    NOW_MAH="?"
    if [ -n "$HAS_SU" ]; then
        BATT_SYS=$(adb -s "$serial" shell "su -c '
            echo -n \"asoc:\"; cat /sys/class/power_supply/battery/fg_asoc 2>/dev/null; echo \"\"
            echo -n \"fullcap:\"; cat /sys/class/power_supply/battery/fg_fullcapnom 2>/dev/null; echo \"\"
            echo -n \"discharge:\"; cat /efs/FactoryApp/batt_discharge_level 2>/dev/null; echo \"\"
            echo -n \"counter:\"; cat /sys/class/power_supply/battery/charge_counter 2>/dev/null; echo \"\"
        '")
        ASOC_VAL=$(echo "$BATT_SYS" | awk -F':' '/asoc:/ {print $2}' | head -1 | tr -d '\r\n ')
        FULLCAP_VAL=$(echo "$BATT_SYS" | awk -F':' '/fullcap:/ {print $2}' | head -1 | tr -d '\r\n ')
        DISCHARGE_VAL=$(echo "$BATT_SYS" | awk -F':' '/discharge:/ {print $2}' | head -1 | tr -d '\r\n ')
        COUNTER_VAL=$(echo "$BATT_SYS" | awk -F':' '/counter:/ {print $2}' | head -1 | tr -d '\r\n ')
        [ -n "$DISCHARGE_VAL" ] && [ "$DISCHARGE_VAL" -gt 0 ] 2>/dev/null && CYCLE_VAL=$(awk -v d="$DISCHARGE_VAL" 'BEGIN {printf "%.0f", d/100}')
        [ -n "$COUNTER_VAL" ] && [ "$COUNTER_VAL" -gt 0 ] 2>/dev/null && NOW_MAH=$(awk -v c="$COUNTER_VAL" 'BEGIN {printf "%.1f", c/1000}')
    fi

    # 4. 화면 및 잠금 세팅 감사
    STAY_AWAKE=$(adb -s "$serial" shell "settings get global stay_on_while_plugged_in 2>/dev/null" | tr -d '\r\n')
    LOCK_DISABLED=$(adb -s "$serial" shell "settings get secure lockscreen.disabled 2>/dev/null" | tr -d '\r\n')
    ROTATION_VAL=$(adb -s "$serial" shell "settings get system user_rotation 2>/dev/null" | tr -d '\r\n')

    # 5. 필수 앱 설치 상태 및 버전
    NAVER_VER=$(adb -s "$serial" shell "dumpsys package com.nhn.android.search 2>/dev/null" | awk -F'=' '/versionName=/ {print $2; exit}' | tr -d '\r\n')
    WG_VER=$(adb -s "$serial" shell "dumpsys package com.wireguard.android 2>/dev/null" | awk -F'=' '/versionName=/ {print $2; exit}' | tr -d '\r\n')
    CURRENT_IME=$(adb -s "$serial" shell "settings get secure default_input_method 2>/dev/null" | tr -d '\r\n')
    KB_INSTALLED="❌ 미설치"
    if adb -s "$serial" shell "pm list packages" 2>/dev/null | grep -q "com.android.adbkeyboard"; then
        if [[ "$CURRENT_IME" == *"com.android.adbkeyboard"* ]]; then
            KB_INSTALLED="🟢 활성 (Default IME)"
        else
            KB_INSTALLED="🟡 설치됨 (비활성)"
            DEV_WARN=$((DEV_WARN + 1))
        fi
    else
        DEV_WARN=$((DEV_WARN + 1))
    fi

    # 6. 네트워크 & IP
    LOCAL_IP=$(adb -s "$serial" shell "ip -o -4 addr show wlan0 2>/dev/null | awk '{print \$4}' | cut -d/ -f1" | head -1 | tr -d '\r\n')
    [ -z "$LOCAL_IP" ] && LOCAL_IP=$(adb -s "$serial" shell "ip -o -4 addr show 2>/dev/null | grep -v '127.0.0.1' | awk '{print \$4}' | cut -d/ -f1" | head -1 | tr -d '\r\n')
    [ -z "$LOCAL_IP" ] && LOCAL_IP="Wi-Fi 미연결"
    PUBLIC_IP=$(adb -s "$serial" shell "curl -s --max-time 2 ifconfig.me 2>/dev/null" | tr -d '\r\n')
    [ -z "$PUBLIC_IP" ] && PUBLIC_IP="확인불가(오프라인)"

    # --- 콘솔 상세 출력 ---
    echo -e "  ${BOLD}[1] 하드웨어 & OS 사양${NC}"
    echo -e "      ↳ 모델명: ${GREEN}$MODEL${NC} | OS: Android $OS_VER (SDK $SDK_VER) | RAM: ${RAM_TOTAL}MB"
    echo -e "      ↳ 저장공간(/data 남은용량): ${GREEN}${FREE_STORAGE}${NC} | Root 권한: $SU_STATUS"

    echo -e "  ${BOLD}[2] 배터리 & 전원 건강 상태${NC}"
    CHG_STR="⚡ USB 충전 중"
    [[ "$BATT_CHG" != "true" ]] && CHG_STR="⚠️ 미충전"
    echo -e "      ↳ 현재 잔량: ${GREEN}${BATT_LEVEL}%${NC} (${NOW_MAH} mAh) | 전압: ${GREEN}${BATT_VOLT}V${NC} | 온도: ${GREEN}${BATT_TEMP}°C${NC} | 상태: $CHG_STR"
    if [ "$ASOC_VAL" != "?" ]; then
        ASOC_COLOR="$GREEN"
        [ "$ASOC_VAL" -lt 85 ] 2>/dev/null && ASOC_COLOR="$YELLOW"
        echo -e "      ↳ 배터리 수명 효율(ASOC): ${ASOC_COLOR}${ASOC_VAL}%${NC} (아이폰 성능최대치 기준) | 누적 사이클: ${CYCLE_VAL}회 | 실질 만충용량: ${FULLCAP_VAL} mAh"
    fi

    echo -e "  ${BOLD}[3] 화면 및 절전/잠금 세팅 상태${NC}"
    STAY_STR="🟢 켜짐 (USB/충전 중 상시점등)"
    [ "$STAY_AWAKE" != "7" ] && { STAY_STR="🔴 꺼짐 (미설정, stay_on: $STAY_AWAKE)"; DEV_WARN=$((DEV_WARN + 1)); }
    LOCK_STR="🟢 해제됨 (lockscreen.disabled: 1)"
    [ "$LOCK_DISABLED" != "1" ] && { LOCK_STR="🔴 잠김 위험 (lockscreen.disabled: $LOCK_DISABLED)"; DEV_WARN=$((DEV_WARN + 1)); }
    ROT_STR="🟢 세로 고정 (0°)"
    [ "$ROTATION_VAL" != "0" ] && { ROT_STR="🟡 회전됨 ($ROTATION_VAL°)"; DEV_WARN=$((DEV_WARN + 1)); }
    echo -e "      ↳ 상시 점등(Stay-Awake): $STAY_STR"
    echo -e "      ↳ 화면 잠금 해제:       $LOCK_STR"
    echo -e "      ↳ 화면 방향:             $ROT_STR"

    echo -e "  ${BOLD}[4] 필수 패키지 및 가동 환경${NC}"
    NAVER_STR="🟢 v$NAVER_VER"
    [ -z "$NAVER_VER" ] && { NAVER_STR="🔴 미설치"; DEV_WARN=$((DEV_WARN + 1)); }
    WG_STR="🟢 v$WG_VER"
    [ -z "$WG_VER" ] && { WG_STR="🔴 미설치"; DEV_WARN=$((DEV_WARN + 1)); }
    echo -e "      ↳ 네이버 앱:     $NAVER_STR"
    echo -e "      ↳ WireGuard VPN: $WG_STR"
    echo -e "      ↳ ADBKeyboard:   $KB_INSTALLED"

    echo -e "  ${BOLD}[5] 네트워크 & 외부 공인 IP${NC}"
    echo -e "      ↳ 내부 IP: ${GREEN}$LOCAL_IP${NC} | 공인 IP: ${CYAN}$PUBLIC_IP${NC}"

    # 판정 결과
    if [ $DEV_WARN -eq 0 ]; then
        STATUS_BADGE="🟢 PASS (완벽)"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        STATUS_BADGE="🟡 WARN ($DEV_WARN건 점검필요)"
        WARN_COUNT=$((WARN_COUNT + 1))
    fi

    SUMMARY_ROWS+=("$(printf "| %-13s | %-9s | %-14s | %-12s | %-15s | %-15s | %-18s |" \
        "$serial" "$MODEL" "${BATT_LEVEL}% (수명 ${ASOC_VAL}%)" "$NAVER_VER" "$LOCAL_IP" "$PUBLIC_IP" "$STATUS_BADGE")")
done

echo -e "\n${CYAN}====================================================================================================================${NC}"
echo -e "${BOLD} 📊 [Phone Farm 전체 단말기 종합 진단 결과표]${NC}"
echo -e "${CYAN}====================================================================================================================${NC}"
echo -e "| 단말기 시리얼  | 모델명    | 배터리(수명)   | 네이버앱버전 | 내부 IP         | 외부 공인 IP    | 종합 판정          |"
echo -e "|---------------|-----------|----------------|--------------|-----------------|-----------------|--------------------|"
for row in "${SUMMARY_ROWS[@]}"; do
    echo -e "$row"
done
echo -e "${CYAN}====================================================================================================================${NC}"
echo -e " 총 점검 단말기: ${BOLD}$TOTAL_COUNT 대${NC} (🟢 정상 가동 가능: ${GREEN}$PASS_COUNT 대${NC} / 🟡 점검 권장: ${YELLOW}$WARN_COUNT 대${NC})"

if [ $WARN_COUNT -gt 0 ]; then
    echo -e "\n${YELLOW}💡 [안내] 경고(WARN)가 발생한 단말기는 아래 명령어로 즉시 일괄 최적화할 수 있습니다:${NC}"
    echo -e "   ${GREEN}./03_device_init.sh${NC}\n"
else
    echo -e "\n${GREEN}🎉 모든 단말기가 365일 무한가동 매크로 운영에 100% 완벽한 상태입니다!${NC}\n"
fi
