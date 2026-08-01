#!/usr/bin/env bash
# ==============================================================================
#  🛠️ DEVICE ENVIRONMENT RESET UTILITY (Selective Clearing Mode)
#  Usage: ./clear_device_env.sh <DEVICE_ID> <SPOOFED_ADID>
# ==============================================================================

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: $0 <DEVICE_ID> <SPOOFED_ADID>"
    exit 1
fi

DEV_ID="$1"
SPOOFED_ADID="$2"
RESET_MODE="$3"
PKG_NAME="com.nhn.android.search"

# Determine reset type
if [ "$RESET_MODE" = "--reset" ]; then
    echo " [$DEV_ID] [🧹] FULL RESET: Running pm clear to completely purge data packages..."
    # Execute full pm clear for all Naver applications
    adb -s "$DEV_ID" shell pm clear "$PKG_NAME" >/dev/null 2>&1
    adb -s "$DEV_ID" shell pm clear "com.navercorp.navershopping" >/dev/null 2>&1
    adb -s "$DEV_ID" shell pm clear "com.nhn.android.nmap" >/dev/null 2>&1
else
    echo " [$DEV_ID] [🧹] STANDARD START: Keeping all cookies and environments intact..."
    # 1. Force stop the applications to release process locks (but do NOT delete any files or cookies)
    adb -s "$DEV_ID" shell am force-stop "$PKG_NAME" >/dev/null 2>&1
    adb -s "$DEV_ID" shell am force-stop "com.navercorp.navershopping" >/dev/null 2>&1
    adb -s "$DEV_ID" shell am force-stop "com.nhn.android.nmap" >/dev/null 2>&1
fi

# 3. Reset Google Advertising ID physically on GMS via configuration rewrite (Only under --reset mode)
if [ "$RESET_MODE" = "--reset" ]; then
    echo " [$DEV_ID] [🎲] Resetting Physical Google Advertising ID via GMS config..."
    RESET_SCRIPT="/tmp/reset_adid_${DEV_ID}.sh"
    cat <<EOF > "$RESET_SCRIPT"
#!/system/bin/sh
NEW_ADID="\$1"
am force-stop com.google.android.gms
echo '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
    <boolean name="enable_debug_logging" value="false" />
    <boolean name="using_cert" value="false" />
    <string name="adid_key">'"\$NEW_ADID"'</string>
    <string name="fake_adid_key"></string>
    <int name="adid_reset_count" value="99" />
    <boolean name="enable_limit_ad_tracking" value="false" />
</map>' > /data/data/com.google.android.gms/shared_prefs/adid_settings.xml
chmod 660 /data/data/com.google.android.gms/shared_prefs/adid_settings.xml
GMS_OWNER=\$(stat -c '%U:%G' /data/data/com.google.android.gms)
chown \$GMS_OWNER /data/data/com.google.android.gms/shared_prefs/adid_settings.xml
am force-stop com.google.android.gms
EOF

    adb -s "$DEV_ID" push "$RESET_SCRIPT" /data/local/tmp/reset_adid.sh >/dev/null 2>&1
    adb -s "$DEV_ID" shell su -c "sh /data/local/tmp/reset_adid.sh $SPOOFED_ADID" >/dev/null 2>&1
    adb -s "$DEV_ID" shell rm -f /data/local/tmp/reset_adid.sh >/dev/null 2>&1
    rm -f "$RESET_SCRIPT"
    sleep 1.5
fi

# 4. Grant runtime permissions since preferences were wiped
echo " [$DEV_ID] [🛡️] Granting location & system permissions..."
adb -s "$DEV_ID" shell pm grant "$PKG_NAME" android.permission.ACCESS_FINE_LOCATION >/dev/null 2>&1
adb -s "$DEV_ID" shell pm grant "$PKG_NAME" android.permission.ACCESS_COARSE_LOCATION >/dev/null 2>&1
adb -s "$DEV_ID" shell pm grant "$PKG_NAME" android.permission.READ_PHONE_STATE >/dev/null 2>&1
adb -s "$DEV_ID" shell pm grant "$PKG_NAME" android.permission.POST_NOTIFICATIONS >/dev/null 2>&1
adb -s "$DEV_ID" shell pm grant "$PKG_NAME" android.permission.RECORD_AUDIO >/dev/null 2>&1

echo " [$DEV_ID] [✓] Environment ready!"
