# ==============================================================================
#  N-Shop Macro Pipeline Unified Master Controller (run.sh)
# ==============================================================================
#  [CRITICAL EXECUTION PRECAUTIONS & HISTORY NOTES]
#  1. MITM Mode, HTTP/3 (H3) & Multi-Seller Catalog Login Redirection:
#     - MITM proxy does NOT support HTTP/3 (QUIC), forcing downgrade to HTTP/2 (TCP).
#     - Clicking Multi-Seller Catalog items ("가격비교 (판매처 N개)") in MITM mode causes
#       Naver to trigger Login Redirection (⚠️ 로그인 전환).
#     - Single organic store items ("단일상품 (스토어명)") bypass login checks cleanly.
#  2. Certificate Interception (Android 14 Conscrypt APEX):
#     - Do NOT use 'mount -t tmpfs' over /apex/com.android.conscrypt/cacerts.
#     - Copy mitmproxy CA cert (c8750f0d.0) to /apex/com.android.conscrypt/cacerts/c8750f0d.0 (644).
#  3. Data Reset & SSL Exception Preservation:
#     - Default FRESH mode preserves /data/data/com.nhn.android.search/app_xwhale/Default/ and
#       shared_prefs/ so that WebView SSL exception decisions are retained.
#     - Use '--pm-clear' flag ONLY when explicit full package wipe is required.
# ==============================================================================

DEVICE=""
KEYWORD=""
PRODUCT_ID=""
MAX_RANK=10
NO_REBOOT=false
SLEEP_SEC=10
CURRENT_IP="211.234.12.34"
PM_CLEAR=false
REUSE_SESSION=false
USE_MITM=false
USE_WG=false
TARGET_SSAID=""
FULL_EXEC_CMD="./run.sh $*"

show_help() {
    echo "Usage: ./run.sh [DEVICE_ID] [FLAGS]"
    echo "Flags:"
    echo "  -k, --keyword KEYWORD     Search keyword (e.g. '노트북')"
    echo "  -p, --product_id NVMID    Target product nvMid (e.g. '87528666743')"
    echo "  --no-reboot               Reuse existing device identity without soft reboot"
    echo "  --wg                      Enable WireGuard & RouterOS MacVlan IP rotation mode"
    echo "  --mitm                    Enable mitmproxy HTTP interception mode"
    echo "  --pm-clear                Force full app package wipe"
    echo "  --sleep SEC               Hold duration before app exit"
    echo "  -h, --help                Show this help message"
    exit 0
}

# Parse Positional & Flag Arguments Cleanly
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            show_help
            ;;
        --device|-d)
            DEVICE="$2"
            shift 2
            ;;
        --keyword|-k)
            KEYWORD="$2"
            shift 2
            ;;
        --product_id|-p)
            PRODUCT_ID="$2"
            shift 2
            ;;
        --ip)
            CURRENT_IP="$2"
            shift 2
            ;;
        --ssaid)
            TARGET_SSAID="$2"
            shift 2
            ;;
        --pm-clear)
            PM_CLEAR=true
            shift
            ;;
        --reuse)
            REUSE_SESSION=true
            shift
            ;;
        --mitm)
            USE_MITM=true
            shift
            ;;
        --wg)
            USE_WG=true
            shift
            ;;
        --max-rank|-m)
            MAX_RANK="$2"
            shift 2
            ;;
        --no-reboot)
            NO_REBOOT=true
            shift
            ;;
        --sleep|-s)
            SLEEP_SEC="$2"
            shift 2
            ;;
        *)
            if [ -z "${DEVICE}" ] && [[ "$1" != -* ]]; then
                DEVICE="$1"
            elif [ -z "${KEYWORD}" ] && [[ "$1" != -* ]]; then
                KEYWORD="$1"
            fi
            shift
            ;;
    esac
done

if [ -z "${DEVICE}" ]; then
    DEVICE="R3CRC0K2K7D"
fi

# Validation Rule: --ssaid CANNOT be combined with --no-reboot
if [ -n "${TARGET_SSAID}" ] && [ "${NO_REBOOT}" = true ]; then
    echo "=========================================================================="
    echo " ❌ [FATAL ERROR] Invalid Argument Combination!"
    echo "    --ssaid '${TARGET_SSAID}' CANNOT be used with --no-reboot!"
    echo "    Restoring a device profile identity requires an OS soft reboot."
    echo "=========================================================================="
    exit 1
fi

# Automatically terminate pre-existing processes targeting the same device
CUR_PID=$$
EXISTING_PIDS=$(pgrep -f "run\.sh.*${DEVICE}" | grep -v "^${CUR_PID}$" || true)
if [ -n "${EXISTING_PIDS}" ]; then
    echo "=========================================================================="
    echo " ⚠️ [DEVICE PROCESS CONFLICT DETECTED] Previous task running on '${DEVICE}'!"
    echo "    Terminating conflicting PIDs: ${EXISTING_PIDS}"
    for p in ${EXISTING_PIDS}; do
        if [ "${p}" != "${CUR_PID}" ]; then
            kill -9 "${p}" 2>/dev/null || true
        fi
    done
    sleep 1
    echo "  [✓] Previous session processes for '${DEVICE}' cleanly terminated."
    echo "=========================================================================="
fi

PKG="com.nhn.android.search"
MONTH_DIR=$(date +"%m%d")
TIME_DIR=$(date +"%H%M%S")
BASE_DIR="/home/tech/nshop_macro_v1/logs/naver_v1/${MONTH_DIR}/${DEVICE}/${TIME_DIR}"

mkdir -p "${BASE_DIR}"
CONSOLE_LOG="${BASE_DIR}/execution_console.log"
exec > >(tee -a "${CONSOLE_LOG}") 2>&1

export CAPTURE_LOG_DIR="${BASE_DIR}"
export LOG_SAVE_DIR="${BASE_DIR}"

# Signal Handler for Graceful Interrupt (Ctrl+C / SIGINT)
cleanup_on_exit() {
    echo ""
    echo "=========================================================================="
    echo " [!] User Interrupt (Ctrl+C) Detected! Performing Cleanup..."
    echo "=========================================================================="
    if [ "${USE_MITM}" = true ]; then
        echo "  [*] Disabling MITM Proxy & Restoring Device Global Proxy..."
        adb -s "${DEVICE}" shell "settings put global http_proxy :0" 2>/dev/null || true
        pkill -f mitmdump 2>/dev/null || true
    fi
    echo " pipeline Gracefully Terminated."
    echo "=========================================================================="
    exit 0
}
trap cleanup_on_exit SIGINT SIGTERM

# ------------------------------------------------------------------------------
# API Task & WireGuard Slot Allocation
# ------------------------------------------------------------------------------
if [ -z "${KEYWORD}" ] || [ "${USE_WG}" = true ]; then
    echo "[*] Querying Master REST API for Task Assignment & WireGuard Slot (Device: ${DEVICE})..."
    JOB_RES=$(curl -s "http://127.0.0.1:5050/api/v1/jobs/assign?device_id=${DEVICE}")
    
    # Check if all slots are busy
    JOB_STATUS=$(echo "${JOB_RES}" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', ''))" 2>/dev/null)
    if [ "${JOB_STATUS}" = "busy" ]; then
        BUSY_MSG=$(echo "${JOB_RES}" | python3 -c "import sys, json; print(json.load(sys.stdin).get('message', 'All WG slots occupied'))" 2>/dev/null)
        echo "  [⚠️ CONCURRENCY LOCK] ${BUSY_MSG}"
        echo "  [*] Waiting for active WireGuard slot to free up..."
        exit 429
    fi

    if [ -z "${KEYWORD}" ]; then
        KEYWORD=$(echo "${JOB_RES}" | python3 -c "import sys, json; print(json.load(sys.stdin).get('job', {}).get('keyword', '노트북'))" 2>/dev/null)
        PRODUCT_ID=$(echo "${JOB_RES}" | python3 -c "import sys, json; print(json.load(sys.stdin).get('job', {}).get('product_id', '87528666743'))" 2>/dev/null)
        echo "  [✓] Auto-Assigned Random Task via API -> Keyword: '${KEYWORD}' | nvMid: '${PRODUCT_ID}'"
    fi
fi

echo "=========================================================================="
echo " N-SHOP AUTOMATION MASTER CONTROLLER (run.sh)"
echo " Target Device : ${DEVICE}"
echo " Target IP     : ${CURRENT_IP}"
echo " Session Mode  : $( [ -n "${TARGET_SSAID}" ] && echo "REUSE (SSAID: ${TARGET_SSAID})" || echo "FRESH (New Allocation)" )"
echo " Search Keyword: ${KEYWORD:-[None - Stop at Main Screen]}"
echo " Target Product: ${PRODUCT_ID:-[None - Stop at Search Page]}"
echo " Zero-Reboot   : ${NO_REBOOT}"
echo " Sleep Delay   : ${SLEEP_SEC}s"
echo " Log Save Path : ${BASE_DIR}"
echo "=========================================================================="

# ------------------------------------------------------------------------------
# Stage 1: Identity Allocation (New Random vs SSAID Profile Restore)
# ------------------------------------------------------------------------------
stage1_physical_device_randomize() {
    export PYTHONPATH="/home/tech/nshop_macro_v1/src:${PYTHONPATH:-}"

    if [ "${USE_WG}" = true ]; then
        echo ""
        echo "=========================================================================="
        echo " 🌐 [WIREGUARD / MACVLAN MODE ACTIVE (--wg)] Activating WireGuard on Device ${DEVICE}..."
        echo "=========================================================================="
        python3 /home/tech/nshop_macro_v1/src/modules/wireguard_manager.py activate "${DEVICE}"
    fi

    if [ -n "${TARGET_SSAID}" ]; then
        echo ""
        echo "=========================================================================="
        echo " [STAGE 1] [REUSE MODE - SSAID: ${TARGET_SSAID}] Restoring Device Profile Identity..."
        echo "=========================================================================="
        
        PROFILE_FILE="/home/tech/nshop_macro_v1/profiles/${TARGET_SSAID}.json"
        if [ ! -f "${PROFILE_FILE}" ]; then
            echo "  [❌ ERROR] Profile for SSAID '${TARGET_SSAID}' not found at '${PROFILE_FILE}'!"
            exit 1
        fi

        RESTORE_RES=$(curl -s -X POST http://127.0.0.1:5050/api/v1/profiles/restore \
            -H "Content-Type: application/json" \
            -d "{\"device_id\": \"${DEVICE}\", \"ssaid\": \"${TARGET_SSAID}\"}")
        
        echo "  [✓] Profile Identity restore payload injected: ${RESTORE_RES}"
        echo "  [*] Executing OS Soft Reboot to apply restored SSAID identity cleanly..."
        PM_FLAG=""
        if [ "${PM_CLEAR}" = true ]; then PM_FLAG="--pm-clear"; fi
        python3 /home/tech/nshop_macro_v1/src/randomize_physical_device_id.py "${DEVICE}" "${PKG}" --ssaid "${TARGET_SSAID}" ${PM_FLAG}
        return 0
    fi

    if [ "${NO_REBOOT}" = true ]; then
        echo ""
        echo "=========================================================================="
        echo " [STAGE 1] [SKIPPED - Reusing Existing Device Identity (--no-reboot)]"
        echo "=========================================================================="
        echo "  [✓] Skipping OS soft reboot & device identity modification."
        return 0
    fi

    echo ""
    echo "=========================================================================="
    echo " [STAGE 1] Physical Device Identity Randomization & OS Soft Reboot"
    echo "=========================================================================="
    adb -s "${DEVICE}" forward tcp:27042 tcp:27042 2>/dev/null || true
    sleep 1

    PM_FLAG=""
    if [ "${PM_CLEAR}" = true ]; then PM_FLAG="--pm-clear"; fi
    python3 /home/tech/nshop_macro_v1/src/randomize_physical_device_id.py "${DEVICE}" "${PKG}" ${PM_FLAG}
}

# ------------------------------------------------------------------------------
# Stage 2: App Data Clear & Zero-Tap Preference Injection
# ------------------------------------------------------------------------------
stage2_app_environment_init() {
    echo ""
    echo "=========================================================================="
    echo " [STAGE 2] App Environment Reset & Zero-Tap Preference Injection"
    echo "=========================================================================="
    
    if [ "${PM_CLEAR}" = true ]; then
        echo "[2-1] [--pm-clear Flag Active] Performing Full Package Clear (pm clear ${PKG})..."
        adb -s "${DEVICE}" shell "pm clear ${PKG}"
    elif [ -z "${TARGET_SSAID}" ]; then
        echo "[2-1] [FRESH MODE] Selective Reset (Preserving SSL Exception Cache & WebView Defaults)..."
        adb -s "${DEVICE}" shell "am force-stop ${PKG}"
        adb -s "${DEVICE}" shell "su -c 'rm -rf /data/data/${PKG}/files/nelolog/* /data/data/${PKG}/files/AFRequestCache/* /data/data/${PKG}/cache/NaverAdsServices/*'"
    else
        echo "[2-1] [REUSE MODE] Selective Reset (Preserving Restored Profile Cookies, NAC Token & NTracker)..."
        adb -s "${DEVICE}" shell "am force-stop ${PKG}"
        adb -s "${DEVICE}" shell "su -c 'rm -rf /data/data/${PKG}/files/nelolog/* /data/data/${PKG}/files/AFRequestCache/* /data/data/${PKG}/cache/NaverAdsServices/*'"
    fi

    echo "[2-2] Pre-granting ALL 16 runtime permissions..."
    PERMS=(
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

    for perm in "${PERMS[@]}"; do
        adb -s "${DEVICE}" shell "pm grant ${PKG} ${perm} 2>/dev/null || true"
    done

    echo "[2-3] Injecting Minimal XML Preferences for Zero-Tap Popup Bypass..."
    APP_UID=$(adb -s "${DEVICE}" shell "su -c 'stat -c %u:%g /data/data/${PKG}'" 2>/dev/null | tr -d '\r\n')
    if [ -z "${APP_UID}" ]; then
        APP_UID="10320:10320"
    fi

    cat << 'EOF' > /tmp/null.xml
<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
    <boolean name="keyFirstRun" value="false" />
    <boolean name="keyUniverseTutorialComplete" value="true" />
    <boolean name="keyNextTutorialComplete" value="true" />
    <boolean name="keyTutorialLocProcessed" value="true" />
    <boolean name="keyDarkTutorialComplete" value="true" />
    <boolean name="keyNewmainTutorialComplete" value="true" />
    <boolean name="keyNotificationQuery" value="true" />
    <boolean name="keyLocationAgree" value="true" />
    <boolean name="keyUniverseMigrationFinished" value="true" />
    <boolean name="keyMyTabMigrationFinished" value="true" />
</map>
EOF

    cat << 'EOF' > /tmp/tutorial_pref.xml
<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
    <boolean name="tutorial_shown" value="true" />
    <boolean name="is_first_launch" value="false" />
</map>
EOF

    adb -s "${DEVICE}" push /tmp/null.xml /data/local/tmp/null.xml >/dev/null
    adb -s "${DEVICE}" push /tmp/tutorial_pref.xml /data/local/tmp/tutorial_pref.xml >/dev/null

    adb -s "${DEVICE}" shell "su -c 'mkdir -p /data/data/${PKG}/shared_prefs && cp /data/local/tmp/null.xml /data/data/${PKG}/shared_prefs/null.xml && cp /data/local/tmp/tutorial_pref.xml /data/data/${PKG}/shared_prefs/tutorial_pref.xml && chmod -R 777 /data/data/${PKG}/shared_prefs && chown -R ${APP_UID} /data/data/${PKG}/shared_prefs'"
    echo "  [✓] Zero-Tap XML Preferences Injected (UID: ${APP_UID})"

    echo "[2-4] Verifying ADB Keyboard installation & setting default IME..."
    HAS_ADB_KB=$(adb -s "${DEVICE}" shell "pm list packages com.android.adbkeyboard" 2>/dev/null | tr -d '\r\n')
    if [[ "${HAS_ADB_KB}" != *"com.android.adbkeyboard"* ]]; then
        echo "  [+] Installing ADBKeyboard.apk on '${DEVICE}'..."
        adb -s "${DEVICE}" install -r /home/tech/nshop_macro_v1/apks/ADBKeyboard.apk >/dev/null 2>&1 || true
    fi
    adb -s "${DEVICE}" shell "ime enable com.android.adbkeyboard/.AdbIME" >/dev/null 2>&1 || true
    adb -s "${DEVICE}" shell "ime set com.android.adbkeyboard/.AdbIME" >/dev/null 2>&1 || true
    CUR_IME=$(adb -s "${DEVICE}" shell "settings get secure default_input_method" 2>/dev/null | tr -d '\r\n')
    echo "  [✓] Default IME verified on '${DEVICE}': ${CUR_IME}"
}

# ------------------------------------------------------------------------------
# Stage 3: App Execution & User Intent Flow (Native Direct Mode)
# ------------------------------------------------------------------------------
stage3_execution_flow() {
    LIVE_COUNT=0
    echo ""
    echo "=========================================================================="
    echo " [STAGE 3] App Launch & Search Intent Execution"
    echo "=========================================================================="

    export PYTHONPATH="/home/tech/nshop_macro_v1/src:${PYTHONPATH:-}"

    if [ "${USE_MITM}" = true ]; then
        echo "[3-1] [MITM PACKET INTERCEPTION MODE] Spawning mitmdump & Setting Global Device Proxy..."
        pkill -f mitmdump 2>/dev/null || true
        /home/tech/.local/bin/mitmdump -p 8888 --set flow_detail=1 -s /home/tech/nshop_macro_v1/src/mitm_full_dumper.py -w "${BASE_DIR}/packets.mitm" > "${BASE_DIR}/mitm.log" 2>&1 &
        sleep 1.5
        adb -s "${DEVICE}" reverse tcp:8888 tcp:8888 2>/dev/null || true
        adb -s "${DEVICE}" shell "settings put global http_proxy 127.0.0.1:8888" 2>/dev/null || true
        echo "  [✓] MITM Proxy active on 127.0.0.1:8888 | Logging packet captures to ${BASE_DIR}/packets.mitm"

        echo "  [*] Spawning Naver App with Frida SSL Pinning Bypass (network_hook.js)..."
        python3 /home/tech/nshop_macro_v1/src/run_frida_spawn.py "${DEVICE}" /home/tech/nshop_macro_v1/src/lib/hooks/network_hook.js > "${BASE_DIR}/frida.log" 2>&1 &
        sleep 2.5
    else
        echo "[3-1] Ensuring NO proxy is set for native HTTP/3..."
        adb -s "${DEVICE}" shell "settings put global http_proxy :0; settings delete global global_http_proxy_host; settings delete global global_http_proxy_port" 2>/dev/null || true
        adb -s "${DEVICE}" reverse --remove tcp:8888 2>/dev/null || true
    fi
    
    echo "[3-2] Ensuring Screen Unlocked & Preparing App Launch..."
    adb -s "${DEVICE}" shell "am force-stop s.aa.cp 2>/dev/null || true"
    adb -s "${DEVICE}" shell "am force-stop com.samsung.android.mtp 2>/dev/null || true"
    adb -s "${DEVICE}" shell "cmd statusbar collapse; input keyevent 224; input keyevent 82; wm dismiss-keyguard" >/dev/null 2>&1 || true

    if [ -n "${KEYWORD}" ]; then
        echo "[3-3] Executing 1-Step Direct Rolling Intent Search URL (Keyword: ${KEYWORD})..."
        python3 -c "from modules.search_action import execute_intent_search; execute_intent_search('${DEVICE}', '${KEYWORD}')"
        echo "  [✓] [MACRO STAGE 1 COMPLETE] Search query executed directly via Intent URL!"
        PYTHONUNBUFFERED=1 python3 -u -c "from modules.shopping_item_finder import execute_top5_category_check_and_extract; execute_top5_category_check_and_extract('${DEVICE}', '${KEYWORD}')"
    else
        echo "[3-3] [*] No --keyword specified. Launching Naver Main Screen (SearchHomePage)..."
        adb -s "${DEVICE}" shell "am start -n ${PKG}/.ui.pages.SearchHomePage" >/dev/null 2>&1
    fi

    echo ""
    echo "=========================================================================="
    echo " [STAGE 4 / MACRO STAGE 2] 1st-Pass Product Scanner & Sequential Click Engine"
    echo "=========================================================================="
    echo "[3-4] Executing 1st-Pass nvMid Memory Scan & Sequential Click Verification (Device: ${DEVICE})..."
    export LOG_SAVE_DIR="${BASE_DIR}"
    PYTHONUNBUFFERED=1 python3 -u -c '
import sys
from modules.shopping_item_finder import execute_nvmid_rank_scanner
from modules.product_clicker import execute_full_sequential_click_test, execute_target_product_click

res = execute_nvmid_rank_scanner("'"${DEVICE}"'", "'"${KEYWORD}"'", "'"${PRODUCT_ID:-}"'")
if "'"${PRODUCT_ID:-}"'" != "":
    if not res:
        print("[!] Target nvMid not found in 1st-pass results.")
        sys.exit(1)
    execute_target_product_click("'"${DEVICE}"'", "'"${KEYWORD}"'", "'"${PRODUCT_ID}"'")
else:
    print("  [✓] 1st-Pass Extraction Complete (No target -p specified). Exiting cleanly.")
' || EXIT_CODE=$?

    if [ "${SLEEP_SEC}" -gt 0 ]; then
        echo "  [*] [--sleep ${SLEEP_SEC}s Flag Active] Holding app active for ${SLEEP_SEC} seconds..."
        sleep "${SLEEP_SEC}"
    fi

    echo ""
    echo "=========================================================================="
    echo " [STAGE 5] App Close & Session Profile Backup to /home/tech/nshop_macro_v1/profiles"
    echo "=========================================================================="
    echo "[5-1] Force closing app..."
    adb -s "${DEVICE}" shell "am force-stop ${PKG}" 2>/dev/null || true

    echo "[5-2] Triggering Live Session Profile Backup & JSON Export for IP '${CURRENT_IP}'..."
    BACKUP_RES=$(curl -s -X POST http://127.0.0.1:5050/api/v1/profiles/backup \
        -H "Content-Type: application/json" \
        -d "{\"device_id\": \"${DEVICE}\", \"ip_address\": \"${CURRENT_IP}\"}")
    echo "  [✓] Profile Backup Result: ${BACKUP_RES}"

    if [ "${USE_MITM}" = true ]; then
        echo "  [*] Restoring device global proxy..."
        adb -s "${DEVICE}" shell "settings put global http_proxy :0" 2>/dev/null || true
        pkill -f mitmdump 2>/dev/null || true
    fi

    if [ "${USE_WG}" = true ]; then
        echo ""
        echo "=========================================================================="
        echo " 🌐 [WIREGUARD / MACVLAN MODE ACTIVE (--wg)] Disconnecting WG & Toggling Router IP..."
        echo "=========================================================================="
        python3 /home/tech/nshop_macro_v1/src/modules/wireguard_manager.py toggle "${DEVICE}"
        
        # Release WireGuard slot lock via API
        RELEASE_RES=$(curl -s -X POST http://127.0.0.1:5050/api/v1/jobs/complete \
            -H "Content-Type: application/json" \
            -d "{\"device_id\": \"${DEVICE}\"}")
        echo "  [✓] WireGuard Slot Lock Released: ${RELEASE_RES}"
    fi

    FINAL_FOCUS=$(adb -s "${DEVICE}" shell "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'" | tr -d '\r\n')
    ACTIVE_SSAID=$(adb -s "${DEVICE}" shell "settings get secure android_id" | tr -d '\r\n')
    HISTORY_FILE="/home/tech/nshop_macro_v1/logs/history_${MONTH_DIR}.log"
    MODE_STR=$( [ -n "${TARGET_SSAID}" ] && echo "REUSE" || echo "FRESH" )
    TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

    # Record daily execution entry
    echo "[${TIMESTAMP}] DEVICE: ${DEVICE} | MODE: ${MODE_STR} | SSAID: ${ACTIVE_SSAID} | CMD: ${FULL_EXEC_CMD} | LOG_DIR: ${BASE_DIR}" >> "${HISTORY_FILE}"

    echo "=========================================================================="
    echo " PIPELINE EXECUTION COMPLETE!"
    echo " Focused Window : ${FINAL_FOCUS}"
    echo " Log Destination: ${BASE_DIR}"
    echo " Profile Saved  : /home/tech/nshop_macro_v1/profiles/${ACTIVE_SSAID}.json"
    echo " Daily Log Record: ${HISTORY_FILE}"
    echo "=========================================================================="
}

# Execute All Modular Stages
stage1_physical_device_randomize
stage2_app_environment_init
stage3_execution_flow
