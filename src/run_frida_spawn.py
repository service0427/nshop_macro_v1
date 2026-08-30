import frida
import sys
import time
import subprocess

device_id = sys.argv[1] if len(sys.argv) > 1 else "R3CRC0K2K7D"
js_script = sys.argv[2] if len(sys.argv) > 2 else "/home/tech/nshop_macro_v1/src/lib/hooks/network_hook.js"

print(f"[*] Initializing Frida connection for ADB device: {device_id}...")

# Ensure frida-server exists and is running on device
exists_chk = subprocess.run(["adb", "-s", device_id, "shell", "su 0 sh -c 'test -f /data/local/tmp/frida-server && echo EXISTS'"], capture_output=True, text=True).stdout
if "EXISTS" not in exists_chk:
    print(f"  [*] frida-server binary missing on device {device_id}. Pushing binary...")
    subprocess.run(["adb", "-s", device_id, "push", "/tmp/frida-server-android", "/data/local/tmp/frida-server"], check=False)
    subprocess.run(["adb", "-s", device_id, "shell", "su 0 sh -c 'chmod 777 /data/local/tmp/frida-server; chown shell:shell /data/local/tmp/frida-server'"], check=False)

chk = subprocess.run(["adb", "-s", device_id, "shell", "su 0 sh -c 'ps -ef | grep frida-server | grep -v grep'"], capture_output=True, text=True).stdout
if "frida-server" not in chk:
    print(f"  [*] Starting frida-server daemon as root on device {device_id}...")
    subprocess.run(["adb", "-s", device_id, "shell", "su -c 'chmod 777 /data/local/tmp/frida-server; nohup /data/local/tmp/frida-server -l 0.0.0.0:27042 >/dev/null 2>&1 &'"], check=False)
    time.sleep(1.5)

# Ensure ADB port forward for root frida-server
subprocess.run(["adb", "-s", device_id, "forward", "tcp:27042", "tcp:27042"], check=False)

device = None
mgr = frida.get_device_manager()
for attempt in range(1, 10):
    try:
        device = mgr.add_remote_device("127.0.0.1:27042")
        procs = device.enumerate_processes()
        print(f"  [✓] Connected to Root Frida on device '{device_id}' ({len(procs)} active procs)", flush=True)
        break
    except Exception as e:
        print(f"  [*] [Attempt {attempt}/10] Waiting for Frida on device '{device_id}'... ({e})", flush=True)
        time.sleep(1.0)

if not device:
    print(f"  [❌ FATAL ERROR] Unable to connect to Frida on device {device_id}")
    sys.exit(1)



# Attach or Spawn
session = None
is_spawn = False

# Force-stop and Fresh Spawn for early hook binding (Application.onCreate)
try:
    subprocess.run(["adb", "-s", device_id, "shell", "am force-stop com.nhn.android.search"], check=False)
    time.sleep(0.5)
except Exception:
    pass

print("  [+] Spawning com.nhn.android.search via Frida...")
pid = device.spawn(["com.nhn.android.search"])
session = device.attach(pid)
is_spawn = True


import os
import re

def load_bundled_frida_script(file_path, visited=None):
    if visited is None:
        visited = set()
    
    abs_path = os.path.abspath(file_path)
    if abs_path in visited:
        return ""
    visited.add(abs_path)
    
    base_dir = os.path.dirname(abs_path)
    with open(abs_path, "r", encoding="utf-8") as f:
        content = f.read()

    def replace_require(match):
        rel_path = match.group(1)
        if not rel_path.endswith('.js'):
            rel_path += '.js'
        target_path = os.path.normpath(os.path.join(base_dir, rel_path))
        if os.path.exists(target_path):
            print(f"  [+] Inlining imported Frida module: {target_path}")
            return f"\n/* --- Bundled: {os.path.basename(target_path)} --- */\n" + load_bundled_frida_script(target_path, visited)
        return match.group(0)

    content = re.sub(r'require\s*\(\s*[\'"](\.\/?[^\'"]+)[\'"]\s*\);?', replace_require, content)
    content = re.sub(r'//\s*@import\s+[\'"]?(\.\/?[^\'"\s]+)[\'"]?', replace_require, content)
    return content

code = load_bundled_frida_script(js_script)

script = session.create_script(code)


def on_message(message, data):
    if message['type'] == 'send':
        print(f"[Frida] {message['payload']}", flush=True)
    elif message['type'] == 'log':
        print(f"[Frida Log] {message['payload']}", flush=True)
    elif message['type'] == 'error':
        print(f"[Frida Error] {message['description']}\n{message.get('stack', '')}", flush=True)
    else:
        print(f"[Frida Msg] {message}", flush=True)
    sys.stdout.flush()


def on_spawn_added(spawn):
    print(f"  [+] Intercepted child spawn: {spawn.identifier} (PID: {spawn.pid})", flush=True)
    if "com.nhn.android.search" in spawn.identifier:
        try:
            child_session = device.attach(spawn.pid)
            child_script = child_session.create_script(code)
            child_script.on('message', on_message)
            child_script.load()
            print(f"  [✓] SSL Pinning Bypass injected into child: {spawn.identifier} (PID: {spawn.pid})", flush=True)
        except Exception as e:
            print(f"  [!] Failed to hook child {spawn.pid}: {e}", flush=True)
    try:
        device.resume(spawn.pid)
    except Exception:
        pass

device.on('spawn-added', on_spawn_added)
try:
    device.enable_spawn_gating()
    print("  [✓] Frida Spawn Gating enabled for all child processes", flush=True)
except Exception as e:
    print(f"  [!] Spawn gating warning: {e}", flush=True)

script.on('message', on_message)
script.load()

if is_spawn:
    device.resume(pid)
    # Wake up Java ART VM main thread immediately so Java.perform fires without delay
    subprocess.run(["adb", "-s", device_id, "shell", "am start -n com.nhn.android.search/.ui.pages.SearchHomePage"], check=False)


try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    if session:
        session.detach()
