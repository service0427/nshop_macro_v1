import subprocess
import secrets
import uuid
import sys
import time
import os
import tempfile
import re

class PhysicalDeviceRandomizer:
    def __init__(self, device_id="R5CT20Y2XYE", package_name="com.nhn.android.search"):
        self.device_id = device_id
        self.package_name = package_name

    def run_adb_su(self, cmd):
        full_cmd = f"su -c '{cmd}'"
        return subprocess.run(["adb", "-s", self.device_id, "shell", full_cmd], capture_output=True, text=True)

    def _pull_modify_push(self, remote_path, search_pattern, replace_bytes, is_binary=True):
        try:
            tmp_local = tempfile.mktemp()
            subprocess.run(["adb", "-s", self.device_id, "shell", f"su -c 'cp {remote_path} /data/local/tmp/tmp_file && chmod 777 /data/local/tmp/tmp_file'"], check=False)
            subprocess.run(["adb", "-s", self.device_id, "pull", "/data/local/tmp/tmp_file", tmp_local], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(tmp_local):
                mode = "rb" if is_binary else "r"
                with open(tmp_local, mode) as f:
                    data = f.read()
                
                if is_binary:
                    matches = set(re.findall(search_pattern, data))
                    new_data = data
                    for m in matches:
                        new_data = new_data.replace(m, replace_bytes)
                else:
                    new_data = re.sub(search_pattern, replace_bytes.decode('utf-8'), data)
                    
                mode_w = "wb" if is_binary else "w"
                with open(tmp_local, mode_w) as f:
                    f.write(new_data)
                    
                subprocess.run(["adb", "-s", self.device_id, "push", tmp_local, "/data/local/tmp/tmp_file"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["adb", "-s", self.device_id, "shell", f"su -c 'cp /data/local/tmp/tmp_file {remote_path} && rm -f /data/local/tmp/tmp_file'"], check=False)
                os.remove(tmp_local)
                print(f"  [✓] Updated {remote_path}")
        except Exception as e:
            print(f"  [-] Failed updating {remote_path}: {e}")

    def _replace_ssaid_in_xml(self, remote_path, new_ssaid):
        try:
            tmp_local = tempfile.mktemp()
            subprocess.run(["adb", "-s", self.device_id, "shell", f"su -c 'cp {remote_path} /data/local/tmp/tmp_file && chmod 777 /data/local/tmp/tmp_file'"], check=False)
            subprocess.run(["adb", "-s", self.device_id, "pull", "/data/local/tmp/tmp_file", tmp_local], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(tmp_local):
                with open(tmp_local, "rb") as f:
                    data = f.read()
                
                target_ids = set(re.findall(rb"[0-9a-f]{16}", data))
                new_data = data
                for tid in target_ids:
                    if len(tid) == 16:
                        new_data = new_data.replace(tid, new_ssaid.encode())
                    
                with open(tmp_local, "wb") as f:
                    f.write(new_data)
                    
                subprocess.run(["adb", "-s", self.device_id, "push", tmp_local, "/data/local/tmp/tmp_file"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["adb", "-s", self.device_id, "shell", f"su -c 'cp /data/local/tmp/tmp_file {remote_path} && rm -f /data/local/tmp/tmp_file'"], check=False)
                os.remove(tmp_local)
                print(f"  [✓] Successfully updated SSAID in {remote_path}")
        except Exception as e:
            print(f"  [-] Failed SSAID update in {remote_path}: {e}")

    def randomize(self):
        new_ssaid = secrets.token_hex(8)
        new_adid = str(uuid.uuid4())
        new_idfv = str(uuid.uuid4())

        print(f"==========================================================================")
        print(f" [PhysicalDeviceRandomizer] Mode-A Physical Identity Randomization")
        print(f" Target Device : {self.device_id}")
        print(f"  -> Fresh SSAID : {new_ssaid}")
        print(f"  -> Fresh ADID  : {new_adid}")
        print(f"  -> Fresh IDFV  : {new_idfv}")
        print(f"==========================================================================")

        # 1. Stop App & GMS + PM CLEAR + Pre-grant & Bypass Tutorial
        print("[1/4] Force stopping app & GMS services, clearing app data & bypassing tutorials...")
        self.run_adb_su(f"am force-stop {self.package_name}; am force-stop com.google.android.gms")
        self.run_adb_su(f"pm clear {self.package_name}")
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
            self.run_adb_su(f"pm grant {self.package_name} {p} 2>/dev/null || true")
        self.run_adb_su("settings put global disable_secure_windows 1 2>/dev/null || true")

        # Inject minimal XML tutorial bypass preferences directly
        owner_res = self.run_adb_su(f"stat -c %u:%g /data/data/{self.package_name}")
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

        subprocess.run(["adb", "-s", self.device_id, "push", "/tmp/null.xml", "/data/local/tmp/null.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["adb", "-s", self.device_id, "push", "/tmp/tutorial_pref.xml", "/data/local/tmp/tutorial_pref.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.run_adb_su(f"mkdir -p /data/data/{self.package_name}/shared_prefs && cp /data/local/tmp/null.xml /data/data/{self.package_name}/shared_prefs/null.xml && cp /data/local/tmp/tutorial_pref.xml /data/data/{self.package_name}/shared_prefs/tutorial_pref.xml && chmod -R 777 /data/data/{self.package_name}/shared_prefs && chown -R {app_uid} /data/data/{self.package_name}/shared_prefs")
        time.sleep(0.5)

        # 2. Binary rewrite
        print("[2/4] Rewriting SSAID, IDFV, ADID physical files...")
        self._replace_ssaid_in_xml("/data/system/users/0/settings_ssaid.xml", new_ssaid)
        self._replace_ssaid_in_xml("/data/system/users/0/settings_ssaid.xml.fallback", new_ssaid)
        self._replace_ssaid_in_xml("/data/system/users/0/settings_secure.xml", new_ssaid)
        self._pull_modify_push("/data/data/com.google.android.gms/files/appset/shared/pvids.pb", b"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", new_idfv.encode(), is_binary=True)
        self._pull_modify_push("/data/data/com.google.android.gms/shared_prefs/adid_settings.xml", r'<string name="adid_key">.*?</string>', f'<string name="adid_key">{new_adid}</string>'.encode(), is_binary=False)

        # 3. Secure settings update
        self.run_adb_su(f"settings put secure android_id {new_ssaid}")

        # 4. Flush caches
        print("[3/4] Flushing GMS daemon & OS system_server SSAID memory cache...")
        self.run_adb_su("pkill -9 com.google.android.gms; pkill -9 -f com.google.android.gms.persistent 2>/dev/null || true")
        self.run_adb_su("pkill -9 system_server 2>/dev/null || true")

        print("  [*] Waiting for OS system_server & WindowManager recovery (Initial 12s grace period)...")
        time.sleep(12)

        start_t = time.time()
        sp_ready = False
        focus_ready = False

        # Dynamic 1s polling loop up to 35s max timeout
        while time.time() - start_t < 35:
            if not sp_ready:
                res_sp = self.run_adb_su("settings get secure android_id")
                if res_sp.returncode == 0 and res_sp.stdout.strip() and "Can't find service" not in res_sp.stdout:
                    sp_ready = True
                    print(f"  [✓] OS SettingsProvider ready ({round(time.time() - start_t + 12, 1)}s)")

            if sp_ready:
                res_app = self.run_adb_su("dumpsys window | grep -i mFocusedApp")
                app_str = res_app.stdout.strip()
                if app_str and "FallbackHome" not in app_str and "SetupWizard" not in app_str and "null" not in app_str:
                    focus_ready = True
                    print(f"  [✓] WindowManager ready & out of FallbackHome (App: {app_str}) in {round(time.time() - start_t + 12, 1)}s")
                    break
            time.sleep(1)

        if not sp_ready or not focus_ready:
            print(f"  [ERROR] OS Soft Reboot Failed to stabilize within timeout (SP: {sp_ready}, Focus: {focus_ready}). Aborting!")
            sys.exit(1)

        # Restart frida-server daemon to rebind after system_server restart
        print("  [*] Re-binding frida-server daemon to re-initialized OS...")
        self.run_adb_su("pkill -9 frida-server 2>/dev/null || true")
        self.run_adb_su("nohup /data/local/tmp/frida-server -l 0.0.0.0:27042 >/dev/null 2>&1 &")
        subprocess.run(["adb", "-s", self.device_id, "forward", "tcp:27042", "tcp:27042"], check=False)
        time.sleep(1)

        # Direct unlock sequence for Samsung One UI keyguard
        self.run_adb_su("input keyevent 224")
        self.run_adb_su("wm dismiss-keyguard")
        self.run_adb_su("input swipe 500 1800 500 400 150")
        time.sleep(1)

        print("[+] Mode-A Complete Physical System Identity Randomization Applied!")
        return {
            "device_id": self.device_id,
            "ssaid": new_ssaid,
            "adid": new_adid,
            "idfv": new_idfv
        }

if __name__ == "__main__":
    dev = sys.argv[1] if len(sys.argv) > 1 else "R5CT20Y2XYE"
    pkg = sys.argv[2] if len(sys.argv) > 2 else "com.nhn.android.search"
    randomizer = PhysicalDeviceRandomizer(device_id=dev, package_name=pkg)
    randomizer.randomize()
