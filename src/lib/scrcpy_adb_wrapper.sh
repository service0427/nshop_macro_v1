#!/usr/bin/env bash

# Custom ADB wrapper script for scrcpy
# Wraps app_process in su -c so scrcpy-server runs as root on Android 14/15.
# Always injects -s <serial> cleanly.

ADB_BIN="$(command -v adb 2>/dev/null || echo "adb")"
RAW_ARGS=("$@")
SERIAL="${ANDROID_SERIAL:-}"
CLEAN_ARGS=()

for ((i=0; i<${#RAW_ARGS[@]}; i++)); do
    arg="${RAW_ARGS[$i]}"
    if [ "$arg" = "-s" ]; then
        i=$((i+1))
        SERIAL="${RAW_ARGS[$i]}"
    else
        CLEAN_ARGS+=("$arg")
    fi
done

if [ -z "$SERIAL" ]; then
    SERIAL="$(/usr/bin/adb devices 2>/dev/null | grep -E '^R[A-Z0-9]+' | head -n 1 | awk '{print $1}')"
fi

HAS_APP_PROCESS=false
for arg in "${CLEAN_ARGS[@]}"; do
    if [[ "$arg" == *"app_process"* ]]; then
        HAS_APP_PROCESS=true
        break
    fi
done

if [ "$HAS_APP_PROCESS" = true ]; then
    CMD_STR=""
    for ((i=0; i<${#CLEAN_ARGS[@]}; i++)); do
        if [ "${CLEAN_ARGS[$i]}" = "shell" ]; then
            CMD_STR="${CLEAN_ARGS[$((i+1))]}"
            break
        fi
    done
    
    if [ -n "$CMD_STR" ]; then
        exec "$ADB_BIN" -s "$SERIAL" shell su -c "$CMD_STR"
    fi
fi

if [ -n "$SERIAL" ]; then
    exec "$ADB_BIN" -s "$SERIAL" "${CLEAN_ARGS[@]}"
else
    exec "$ADB_BIN" "${CLEAN_ARGS[@]}"
fi
