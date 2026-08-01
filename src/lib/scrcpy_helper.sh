#!/usr/bin/env bash

# ==============================================================================
# Library Name: lib/scrcpy_helper.sh
# Description: Standardized GUI scrcpy screen mirroring helper with full touch/mouse control
#              and patched scrcpy-server for Android 13, 14, 15 compatibility.
# ==============================================================================

init_scrcpy_env() {
    export DISPLAY=:0
    export XAUTHORITY=/run/user/1000/gdm/Xauthority
    export LIBGL_ALWAYS_SOFTWARE=1
    export SNAP_LAUNCHER_NOTICE_ENABLED=false
    unset SCRCPY_SERVER_PATH

    # Bypass Snap notice windows
    mkdir -p "$HOME/snap/scrcpy/common" 2>/dev/null
    touch "$HOME/snap/scrcpy/common/.marker.skip-collaborator-change-notice-20250627" 2>/dev/null
    touch "$HOME/snap/scrcpy/common/.marker.skip-rawusb-interface-notice" 2>/dev/null
    touch "$HOME/snap/scrcpy/common/.marker.skip-joystick-interface-notice" 2>/dev/null
}

launch_scrcpy_grid() {
    local target_devices=("$@")
    local num_devices=${#target_devices[@]}

    if [ $num_devices -eq 0 ]; then
        echo "[-] scrcpy_helper: No target devices provided."
        return 1
    fi

    init_scrcpy_env

    # Terminate existing scrcpy sessions
    pkill -9 -x "scrcpy" 2>/dev/null
    pkill -9 -f "/snap/scrcpy/.*/scrcpy" 2>/dev/null
    sleep 1

    # Detect resolution
    local resolution=$(xrandr 2>/dev/null | grep -oP '\d+x\d+(?=\s+\d+\.\d+\*)' | head -n 1)
    local screen_width=2560
    local screen_height=1440
    if [ -n "$resolution" ]; then
        screen_width=$(echo "$resolution" | cut -d'x' -f1)
        screen_height=$(echo "$resolution" | cut -d'x' -f2)
    fi

    local window_height=$((screen_height - 80))
    local window_y=40
    local divisor=$num_devices
    if [ $divisor -lt 3 ]; then
        divisor=3
    fi
    local window_width=$((screen_width / divisor))

    echo "=========================================================="
    echo " [scrcpy_helper] Launching $num_devices Interactive GUI Window(s) (${screen_width}x${screen_height})"
    echo "=========================================================="

    for i in "${!target_devices[@]}"; do
        local serial="${target_devices[$i]}"
        local x_pos=$((i * window_width))

        # Keep physical screen awake
        adb -s "$serial" shell "svc power stayon true" 2>/dev/null

        # Launch scrcpy with software rendering & stable mirror control
        nohup /snap/bin/scrcpy -s "$serial" \
            --window-x "$x_pos" \
            --window-y "$window_y" \
            --window-width "$window_width" \
            --window-height "$window_height" \
            --window-title "[$((i+1))] Device: $serial" \
            --render-driver=software \
            --no-audio \
            --no-control \
            --always-on-top \
            > "/tmp/scrcpy_${serial}.log" 2>&1 &
        disown $! 2>/dev/null || true

        echo "  [✓] Interactive scrcpy GUI launched for $serial at X=$x_pos, Width=$window_width"
    done
}
