#!/bin/bash

DEVICE_ID=$1
PLACE_ID=${2:-"1951575597"}
TARGET_MINUTES=${3:-3}

if [ -z "$DEVICE_ID" ]; then
    echo "[!] Error: DEVICE_ID is required."
    exit 1
fi

PKG_NAME="com.rosteam.gpsemulator"

if ! adb -s "$DEVICE_ID" shell pm list packages | grep -q "$PKG_NAME"; then
    echo " [!] CRITICAL: $PKG_NAME is not installed on $DEVICE_ID! Please install it."
    exit 1
fi

echo "============================================================"
echo "   GPS EMULATOR DYNAMIC ROUTE & SPEED (STEST MODE)"
echo "   Device: $DEVICE_ID | Target: $PLACE_ID"
echo "============================================================"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
UNIQUE_FNAME="${PLACE_ID}_${TIMESTAMP}_${DEVICE_ID}.json"

echo "[-] Generating fresh randomized route..."
ROUTE_INFO=$(python3 utils/smart_route_gen.py "$PLACE_ID" "$UNIQUE_FNAME")

ROUTE_PATH=$(echo "$ROUTE_INFO" | grep "ROUTE_FILE:" | awk '{print $2}')
DISTANCE=$(echo "$ROUTE_INFO" | grep "TOTAL_DISTANCE:" | awk '{print $2}')

if [ -z "$ROUTE_PATH" ] || [ -z "$DISTANCE" ]; then
    echo " [!] Error: Failed to generate route or distance info."
    exit 1
fi

REQUIRED_SPEED=$(python3 -c "
import random
dist = float('$DISTANCE')
# Target time between 5.0 and 8.0 minutes
target_mins = random.uniform(5.0, 8.0)
target_hours = target_mins / 60.0

calc_speed = dist / target_hours
max_speed_cap = random.uniform(100.0, 115.0)

final_speed = min(calc_speed, max_speed_cap)
final_speed = max(final_speed, 20.0)

print(round(final_speed, 1))
")
echo "    > New Distance: $DISTANCE km | Target Speed: $REQUIRED_SPEED km/h"

echo "[-] Rebuilding Premium XML locally..."
adb -s "$DEVICE_ID" shell am force-stop "$PKG_NAME"

LOCAL_TMP="/tmp/final_1_prefs_${DEVICE_ID}.xml"
python3 utils/rebuild_xml.py "$ROUTE_PATH" "$REQUIRED_SPEED" "$DEVICE_ID" > /dev/null

echo "[-] Injecting data to device..."
PREFS_NAME="${PKG_NAME}_preferences.xml"
PREFS_PATH="/data/data/$PKG_NAME/shared_prefs/$PREFS_NAME"

adb -s "$DEVICE_ID" push "$LOCAL_TMP" "/data/local/tmp/$PREFS_NAME" >/dev/null 2>&1
adb -s "$DEVICE_ID" shell "su -c 'chmod 660 $PREFS_PATH 2>/dev/null; cp /data/local/tmp/$PREFS_NAME $PREFS_PATH && chown \$(stat -c %u:%g /data/data/$PKG_NAME) $PREFS_PATH && chmod 440 $PREFS_PATH'"

rm -f "$LOCAL_TMP"
rm -f "$ROUTE_PATH"

echo "[-] Auto-Starting GPS Engine (Headless Intent)..."
SPEED_MPS=$(python3 -c "print(round($REQUIRED_SPEED / 3.6, 6))")
adb -s "$DEVICE_ID" shell su -c "am start-foreground-service -n $PKG_NAME/.servicex2484 -a ACTION_START_CONTINUOUS --es uy.digitools.RUTA 'ruta0' --ef velocidad $SPEED_MPS --ei loopMode 0"
sleep 2

echo "============================================================"
echo " [✓] GPS EMULATION INJECTED AND STARTED FOR $DEVICE_ID!"
echo "============================================================"
