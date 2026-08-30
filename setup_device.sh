#!/usr/bin/env bash
# ==============================================================================
# N-SHOP AUTOMATION: ONE-CLICK NEW DEVICE SETUP & INITIALIZATION
# Configures Screen Lock, Keep-Awake, Essential APKs, Permissions, and Frida
# Supports single device: ./setup_device.sh <DEVICE_ID>
# Supports all devices  : ./setup_device.sh --all (or with no arguments)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APKS_DIR="${SCRIPT_DIR}/apks"
BIN_DIR="${SCRIPT_DIR}/bin"

# ------------------------------------------------------------------------------
# Function: Setup a single device
# ------------------------------------------------------------------------------
setup_single_device() {
    local DEV="$1"
    echo ""
    echo "=========================================================================="
    echo " 📱 [DEVICE SETUP] Initializing Device: ${DEV}"
    echo "=========================================================================="

    # 0. Check ADB & Root Connectivity
    if ! timeout 5 adb -s "${DEV}" shell "echo OK" >/dev/null 2>&1; then
        echo "  [⚠️ ADB SOCKET TIMEOUT] Reconnecting device ${DEV}..."
        timeout 3 adb reconnect offline >/dev/null 2>&1 || true
        timeout 3 adb -s "${DEV}" reconnect >/dev/null 2>&1 || true
        sleep 1.0
    fi

    local MODEL
    MODEL=$(adb -s "${DEV}" shell "getprop ro.product.model" 2>/dev/null | tr -d '\r\n')
    local ANDROID_VER
    ANDROID_VER=$(adb -s "${DEV}" shell "getprop ro.build.version.release" 2>/dev/null | tr -d '\r\n')
    echo "  [*] Model: ${MODEL} (Android ${ANDROID_VER})"

    # 1. Screen Lock & Stay Awake Configuration (화면 잠금 완전 비활성화 & 상시 켜짐)
    echo "  [1/6] Disabling Screen Lock & Configuring 24/7 Keep-Awake..."
    adb -s "${DEV}" shell "su -c '
        locksettings set-disabled true 2>/dev/null || true
        settings put global stay_on_while_plugged_in 7
        settings put system screen_off_timeout 2147483647
        settings put secure screen_off_timeout 2147483647
        settings put secure lock_screen_lock_after_timeout 0
        settings put global sleep_timeout -1
        settings put system screen_brightness_mode 0 2>/dev/null || true
        settings put system screen_brightness 35 2>/dev/null || true
        settings put global window_animation_scale 0.5 2>/dev/null || true
        settings put global transition_animation_scale 0.5 2>/dev/null || true
        settings put global animator_duration_scale 0.5 2>/dev/null || true
        input keyevent 224 2>/dev/null || true
        wm dismiss-keyguard 2>/dev/null || true
        cmd statusbar collapse 2>/dev/null || true
    '" >/dev/null 2>&1 || true
    echo "  [✓] Screen Lock DISABLED and 24/7 Keep-Awake configured cleanly."

    # 2. Install & Configure ADBKeyboard
    echo "  [2/6] Verifying ADBKeyboard IME installation..."
    local HAS_KB
    HAS_KB=$(adb -s "${DEV}" shell "pm list packages com.android.adbkeyboard" 2>/dev/null | tr -d '\r\n')
    if [[ "${HAS_KB}" != *"com.android.adbkeyboard"* ]]; then
        echo "      -> Installing ADBKeyboard.apk..."
        adb -s "${DEV}" install -r -g "${APKS_DIR}/ADBKeyboard.apk" >/dev/null 2>&1 || true
    fi
    adb -s "${DEV}" shell "ime enable com.android.adbkeyboard/.AdbIME 2>/dev/null; ime set com.android.adbkeyboard/.AdbIME 2>/dev/null" >/dev/null 2>&1 || true
    echo "  [✓] ADBKeyboard configured as default IME."

    # 3. Install & Configure WireGuard APK & Permissions
    echo "  [3/6] Verifying WireGuard APK installation..."
    local HAS_WG
    HAS_WG=$(adb -s "${DEV}" shell "pm list packages com.wireguard.android" 2>/dev/null | tr -d '\r\n')
    if [[ "${HAS_WG}" != *"com.wireguard.android"* ]]; then
        echo "      -> Installing WireGuard split APKs..."
        adb -s "${DEV}" install-multiple -r -g \
            "${APKS_DIR}/wireguard/base.apk" \
            "${APKS_DIR}/wireguard/split_config.arm64_v8a.apk" \
            "${APKS_DIR}/wireguard/split_config.ko.apk" \
            "${APKS_DIR}/wireguard/split_config.xxhdpi.apk" >/dev/null 2>&1 || true
    fi
    adb -s "${DEV}" shell "su -c '
        appops set com.wireguard.android ACTIVATE_VPN allow 2>/dev/null || true
        appops set com.wireguard.android ACTIVATE_PLATFORM_VPN allow 2>/dev/null || true
        dumpsys deviceidle whitelist +com.wireguard.android 2>/dev/null || true
    '" >/dev/null 2>&1 || true
    echo "  [✓] WireGuard installed and VPN permissions granted."

    # 4. Install & Configure GPS Emulator APK & Permissions
    echo "  [4/6] Verifying GPS Emulator installation..."
    local HAS_GPS
    HAS_GPS=$(adb -s "${DEV}" shell "pm list packages com.rosteam.gpsemulator" 2>/dev/null | tr -d '\r\n')
    if [[ "${HAS_GPS}" != *"com.rosteam.gpsemulator"* ]]; then
        echo "      -> Installing GPSEmulator.apk..."
        adb -s "${DEV}" install -r -g "${APKS_DIR}/GPSEmulator.apk" >/dev/null 2>&1 || true
    fi
    adb -s "${DEV}" shell "su -c '
        pm grant com.rosteam.gpsemulator android.permission.ACCESS_FINE_LOCATION 2>/dev/null || true
        pm grant com.rosteam.gpsemulator android.permission.ACCESS_COARSE_LOCATION 2>/dev/null || true
        appops set com.rosteam.gpsemulator android:mock_location allow 2>/dev/null || true
        dumpsys deviceidle whitelist +com.rosteam.gpsemulator 2>/dev/null || true
    '" >/dev/null 2>&1 || true
    echo "  [✓] GPS Emulator installed and Mock Location permissions granted."

    # 5. Deploy Frida Server binary
    echo "  [5/6] Deploying Frida Server binary..."
    if [ -f "${BIN_DIR}/frida-server" ]; then
        adb -s "${DEV}" push "${BIN_DIR}/frida-server" /data/local/tmp/frida-server >/dev/null 2>&1 || true
        adb -s "${DEV}" shell "su -c 'chmod 777 /data/local/tmp/frida-server'" >/dev/null 2>&1 || true
        echo "  [✓] Frida Server deployed to /data/local/tmp/frida-server (chmod 777)."
    else
        echo "  [⚠️ WARN] Frida Server binary not found in ${BIN_DIR}."
    fi

    # 6. Pre-grant Naver App Runtime Permissions & Zero-Tap Popups Bypass
    echo "  [6/6] Pre-granting Naver App permissions and zero-tap popup preferences..."
    local PKG="com.nhn.android.search"
    local HAS_NAVER
    HAS_NAVER=$(adb -s "${DEV}" shell "pm list packages ${PKG}" 2>/dev/null | tr -d '\r\n')
    if [[ "${HAS_NAVER}" == *"${PKG}"* ]]; then
        local PERMS=(
            "android.permission.POST_NOTIFICATIONS"
            "android.permission.ACCESS_FINE_LOCATION"
            "android.permission.ACCESS_COARSE_LOCATION"
            "android.permission.CAMERA"
            "android.permission.READ_EXTERNAL_STORAGE"
            "android.permission.WRITE_EXTERNAL_STORAGE"
            "android.permission.READ_MEDIA_IMAGES"
            "android.permission.READ_MEDIA_VIDEO"
            "android.permission.READ_MEDIA_AUDIO"
            "android.permission.RECORD_AUDIO"
            "android.permission.READ_PHONE_STATE"
            "android.permission.GET_ACCOUNTS"
            "android.permission.BLUETOOTH_CONNECT"
            "android.permission.BLUETOOTH_SCAN"
            "android.permission.ACTIVITY_RECOGNITION"
            "android.permission.BODY_SENSORS"
        )
        local GRANT_CMDS=""
        for perm in "${PERMS[@]}"; do
            GRANT_CMDS+="pm grant ${PKG} ${perm} 2>/dev/null; "
        done
        GRANT_CMDS+="cmd appops set ${PKG} FINE_LOCATION allow 2>/dev/null; cmd appops set ${PKG} COARSE_LOCATION allow 2>/dev/null; cmd appops set ${PKG} MOCK_LOCATION allow 2>/dev/null;"
        adb -s "${DEV}" shell "su -c '${GRANT_CMDS}'" >/dev/null 2>&1 || true
        echo "  [✓] 16 Runtime permissions & Location AppOps pre-granted for Naver App."
    fi

    # Wake and return home
    adb -s "${DEV}" shell "input keyevent 3 2>/dev/null || true"
    echo "=========================================================================="
    echo " 🎉 [SETUP COMPLETE] Device ${DEV} is 100% READY FOR AUTOMATION!"
    echo "=========================================================================="
}

# ------------------------------------------------------------------------------
# Main Dispatcher
# ------------------------------------------------------------------------------
TARGET_ARG="${1:-all}"

if [ "${TARGET_ARG}" = "--all" ] || [ "${TARGET_ARG}" = "all" ]; then
    DEVICES=($(adb devices | grep -w "device" | awk '{print $1}'))
    if [ ${#DEVICES[@]} -eq 0 ]; then
        echo "[❌ ERROR] No ADB devices connected in 'device' state!"
        exit 1
    fi
    echo "=========================================================================="
    echo " 🚀 N-SHOP BATCH DEVICE INITIALIZER (${#DEVICES[@]} Devices Found)"
    echo " Target Devices: ${DEVICES[*]}"
    echo "=========================================================================="
    for dev in "${DEVICES[@]}"; do
        setup_single_device "${dev}"
    done
    echo ""
    echo "🎉 ALL ${#DEVICES[@]} DEVICES INITIALIZED AND CONFIGURED CLEANLY!"
else
    setup_single_device "${TARGET_ARG}"
fi
