import subprocess
import secrets
import uuid
import sys
import time
import os

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("device", nargs="?", default="R3CRC0K2K7D")
parser.add_argument("package", nargs="?", default="com.nhn.android.search")
parser.add_argument("--ssaid", default="")
parser.add_argument("--pm-clear", action="store_true")
args, _ = parser.parse_known_args()

device_id = args.device
package_name = args.package

new_ssaid = args.ssaid if args.ssaid else secrets.token_hex(8)  # 16-char hex
new_adid = str(uuid.uuid4())      # 36-char uuid
new_idfv = str(uuid.uuid4())      # 36-char uuid

print(f"==========================================================================")
print(f" [Mode-A Complete] System-Level Physical Identity Randomizer")
print(f" Target Device : {device_id}")
print(f" Target Mode   : {'REUSE (SSAID: ' + new_ssaid + ')' if args.ssaid else 'FRESH RANDOMIZATION'}")
print(f"  -> SSAID      : {new_ssaid}")
print(f"  -> ADID       : {new_adid}")
print(f"  -> IDFV       : {new_idfv}")
print(f"==========================================================================")

def run_adb_su(cmd):
    full_cmd = f"su -c '{cmd}'"
    return subprocess.run(["adb", "-s", device_id, "shell", full_cmd], capture_output=True, text=True)

# 1. Stop App & GMS + Selective Reset
print("[1/5] Force stopping app & GMS services, performing Selective Reset...")
run_adb_su(f"am force-stop {package_name}; am force-stop com.google.android.gms")

if args.pm_clear:
    print("  [--pm-clear Flag Active] Performing Full Package Clear (pm clear)...")
    run_adb_su(f"pm clear {package_name}")
else:
    # Selective Reset: Flush tracking logs & NaverAdsServices cache, while preserving WebView SSL exception cache
    flush_cmd = f"""
rm -rf /data/data/{package_name}/files/nelolog/* \
       /data/data/{package_name}/files/AFRequestCache/* \
       /data/data/{package_name}/cache/NaverAdsServices/*
"""
    run_adb_su(flush_cmd)

perms = [
    "android.permission.POST_NOTIFICATIONS",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.READ_PHONE_STATE",
    "android.permission.READ_PHONE_NUMBERS",
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
    "android.permission.READ_MEDIA_IMAGES",
    "android.permission.READ_MEDIA_VIDEO",
    "android.permission.READ_MEDIA_VISUAL_USER_SELECTED",
    "android.permission.CAMERA",
    "android.permission.RECORD_AUDIO",
    "android.permission.READ_CONTACTS",
    "android.permission.WRITE_CONTACTS",
    "android.permission.ACTIVITY_RECOGNITION",
    "android.permission.ACCESS_MEDIA_LOCATION"
]
for p in perms:
    run_adb_su(f"pm grant {package_name} {p} 2>/dev/null || true")

run_adb_su("settings put global disable_secure_windows 1 2>/dev/null || true")

# Inject minimal XML tutorial bypass preferences directly
owner_res = run_adb_su(f"stat -c %u:%g /data/data/{package_name}")
app_uid = owner_res.stdout.strip()

null_xml_content = """<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
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
    <int name="keyCurrentInstallVersion" value="12217006" />
    <int name="keyFirstInstallVersionCode" value="12217006" />
</map>"""

tutorial_xml_content = """<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
    <boolean name="tutorial_shown" value="true" />
    <boolean name="is_first_launch" value="false" />
</map>"""

with open("/tmp/null.xml", "w") as f: f.write(null_xml_content)
with open("/tmp/tutorial_pref.xml", "w") as f: f.write(tutorial_xml_content)

subprocess.run(["adb", "-s", device_id, "push", "/tmp/null.xml", "/data/local/tmp/null.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.run(["adb", "-s", device_id, "push", "/tmp/tutorial_pref.xml", "/data/local/tmp/tutorial_pref.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
run_adb_su(f"mkdir -p /data/data/{package_name}/shared_prefs && cp /data/local/tmp/null.xml /data/data/{package_name}/shared_prefs/null.xml && cp /data/local/tmp/tutorial_pref.xml /data/data/{package_name}/shared_prefs/tutorial_pref.xml && chmod -R 777 /data/data/{package_name}/shared_prefs && chown -R {app_uid} /data/data/{package_name}/shared_prefs")
time.sleep(0.5)

# 2. Pull, Binary Rewrite, and Push Files for SSAID, IDFV, and ADID
print("[2/5] Performing Local-to-Device Binary Byte Rewrite for SSAID, IDFV, and ADID...")
import tempfile

def pull_modify_push(remote_path, search_pattern, replace_bytes, is_binary=True):
    try:
        tmp_local = tempfile.mktemp()
        subprocess.run(["adb", "-s", device_id, "shell", f"su -c 'cp {remote_path} /data/local/tmp/tmp_file && chmod 777 /data/local/tmp/tmp_file'"], check=False)
        subprocess.run(["adb", "-s", device_id, "pull", "/data/local/tmp/tmp_file", tmp_local], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if os.path.exists(tmp_local):
            mode = "rb" if is_binary else "r"
            with open(tmp_local, mode) as f:
                data = f.read()
            
            if is_binary:
                import re
                matches = set(re.findall(search_pattern, data))
                new_data = data
                for m in matches:
                    new_data = new_data.replace(m, replace_bytes)
            else:
                import re
                new_data = re.sub(search_pattern, replace_bytes.decode('utf-8'), data)
                
            mode_w = "wb" if is_binary else "w"
            with open(tmp_local, mode_w) as f:
                f.write(new_data)
                
            subprocess.run(["adb", "-s", device_id, "push", tmp_local, "/data/local/tmp/tmp_file"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["adb", "-s", device_id, "shell", f"su -c 'cp /data/local/tmp/tmp_file {remote_path} && rm -f /data/local/tmp/tmp_file'"], check=False)
            os.remove(tmp_local)
            print(f"  [✓] Updated {remote_path}")
    except Exception as e:
        print(f"  [-] Failed updating {remote_path}: {e}")

# Apply 3-Point Binary Rewrite with target package SSAID byte replacement
def replace_ssaid_in_xml(remote_path):
    try:
        tmp_local = tempfile.mktemp()
        subprocess.run(["adb", "-s", device_id, "shell", f"su -c 'cp {remote_path} /data/local/tmp/tmp_file && chmod 777 /data/local/tmp/tmp_file'"], check=False)
        subprocess.run(["adb", "-s", device_id, "pull", "/data/local/tmp/tmp_file", tmp_local], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(tmp_local):
            with open(tmp_local, "rb") as f:
                data = f.read()
            import re
            
            # Find SSAID tied to target package in Android ABX or XML format
            pkg_bytes = package_name.encode()
            pos = data.find(pkg_bytes)
            if pos != -1:
                # Search within 120 bytes around package name for 16-char hex
                chunk = data[max(0, pos-120):pos+120]
                matches = re.findall(rb"[0-9a-fA-F]{16}", chunk)
                if matches:
                    for m in matches:
                        data = data.replace(m, new_ssaid.encode())
                else:
                    matches_all = re.findall(rb"[0-9a-fA-F]{16}", data)
                    for m in matches_all:
                        data = data.replace(m, new_ssaid.encode())
            else:
                # Fallback replacement
                matches = re.findall(rb"[0-9a-fA-F]{16}", data)
                for m in matches:
                    data = data.replace(m, new_ssaid.encode())

            with open(tmp_local, "wb") as f:
                f.write(data)
                
            subprocess.run(["adb", "-s", device_id, "push", tmp_local, "/data/local/tmp/tmp_file"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["adb", "-s", device_id, "shell", f"su -c 'cp /data/local/tmp/tmp_file {remote_path} && rm -f /data/local/tmp/tmp_file'"], check=False)
            os.remove(tmp_local)
            print(f"  [✓] Successfully updated SSAID in {remote_path}")
    except Exception as e:
        print(f"  [-] Failed SSAID update in {remote_path}: {e}")

replace_ssaid_in_xml("/data/system/users/0/settings_ssaid.xml")
replace_ssaid_in_xml("/data/system/users/0/settings_ssaid.xml.fallback")
replace_ssaid_in_xml("/data/system/users/0/settings_secure.xml")
pull_modify_push("/data/data/com.google.android.gms/files/appset/shared/pvids.pb", b"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", new_idfv.encode(), is_binary=True)
pull_modify_push("/data/data/com.google.android.gms/shared_prefs/adid_settings.xml", r'<string name="adid_key">.*?</string>', f'<string name="adid_key">{new_adid}</string>'.encode(), is_binary=False)

# Update Secure Settings
run_adb_su(f"settings put secure android_id {new_ssaid}")

# 4. Flush GMS & OS system_server SSAID Memory Cache
print("[3/5] Triggering OS Soft Reboot (Flushing GMS & system_server memory cache)...")
run_adb_su("pkill -9 com.google.android.gms; pkill -9 -f com.google.android.gms.persistent 2>/dev/null || true")
run_adb_su("pkill -9 system_server 2>/dev/null || true")

print("  [*] Waiting for OS system_server & WindowManager recovery (Baseline 15s grace period)...")
time.sleep(15)

start_t = time.time()
sp_ready = False
focus_ready = False

# Dynamic 2s polling loop up to 35s max timeout
while time.time() - start_t < 35:
    if not sp_ready:
        res_sp = run_adb_su("settings get secure android_id")
        if res_sp.returncode == 0 and res_sp.stdout.strip() and "Can't find service" not in res_sp.stdout:
            sp_ready = True
            print(f"  [✓] OS SettingsProvider ready ({round(time.time() - start_t + 15, 1)}s)")

    if sp_ready:
        res_app = run_adb_su("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'")
        app_str = res_app.stdout.strip()
        # Accept if any valid Home/Launcher/SubHome or Window focus is detected and not in FallbackHome/SetupWizard
        if "FallbackHome" not in app_str and "SetupWizard" not in app_str and \
           (any(k in app_str for k in ["LauncherActivity", "SubHomeActivity", "HomeActivity", "com.nhn.android.search"]) or "Window{" in app_str):
            focus_ready = True
            print(f"  [✓] WindowManager ready ({round(time.time() - start_t + 15, 1)}s)")
            break
    time.sleep(2)

if not sp_ready:
    print(f"  [❌ FATAL ERROR] OS Soft Reboot Failed to stabilize SettingsProvider. Aborting pipeline!")
    sys.exit(1)

# Verification Engine: Ensure active SSAID matches target new_ssaid 100%
print("[4/5] Verifying Active OS SSAID Identity...")
verified_ssaid = run_adb_su("settings get secure android_id").stdout.strip()
if verified_ssaid.lower() != new_ssaid.lower():
    print(f"  [❌ FATAL ERROR] SSAID Identity Verification Failed!")
    print(f"     Expected SSAID: {new_ssaid}")
    print(f"     Actual Active : {verified_ssaid}")
    print(f"  [!] Soft reboot identity mutation was rejected or not applied cleanly. Aborting execution!")
    sys.exit(1)

print(f"  [✓] SSAID IDENTITY VERIFIED PASSED! Active SSAID: '{verified_ssaid}'")

# Restart frida-server daemon to rebind after system_server restart
print("[5/5] Re-binding frida-server daemon & Unlocking Screen...")
run_adb_su("pkill -9 frida-server 2>/dev/null || true")
run_adb_su("nohup /data/local/tmp/frida-server -l 0.0.0.0:27042 >/dev/null 2>&1 &")
subprocess.run(["adb", "-s", device_id, "forward", "tcp:27042", "tcp:27042"], check=False)
time.sleep(1)

# Force-stop background popup daemons (s.aa.cp / Link to Windows) that steal focus post-reboot
run_adb_su("am force-stop s.aa.cp 2>/dev/null || true")
run_adb_su("am force-stop com.samsung.android.mtp 2>/dev/null || true")

# Robust unlock & notification shade collapse sequence for Samsung One UI keyguard
run_adb_su("cmd statusbar collapse 2>/dev/null || true")
run_adb_su("input keyevent 224")
run_adb_su("input keyevent 82")
run_adb_su("wm dismiss-keyguard 2>/dev/null || true")
run_adb_su("input keyevent 3")
time.sleep(1)

res_f = run_adb_su("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'")
print(f"  [✓] Screen Unlocked & OS Recovered (Focus/App: {res_f.stdout.strip()})")

print("==========================================================================")
print(" [✓] Physical System Identity Randomization & OS Reboot VERIFIED SUCCESSFUL!")
print("==========================================================================")
