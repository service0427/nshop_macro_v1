import frida
import sys
import time
import subprocess

device_id = sys.argv[1] if len(sys.argv) > 1 else "R5CT20Y2XYE"
js_script = sys.argv[2] if len(sys.argv) > 2 else "/home/tech/nshop_macro_v1/frida_device_randomizer_pure.js"

print(f"[*] Connecting Frida to device: {device_id}...")
try:
    mgr = frida.get_device_manager()
    device = mgr.add_remote_device("127.0.0.1:27042")
    print(f"[+] Connected to Frida server at 127.0.0.1:27042: {device}")
except Exception as e:
    print(f"[*] Fallback to get_device({device_id}): {e}")
    device = frida.get_device(device_id)

try:
    pid = device.get_process("com.nhn.android.search").pid
    print(f"[+] Attaching to existing process (PID: {pid})")
    session = device.attach(pid)
    is_spawn = False
except Exception:
    print("[+] Spawning com.nhn.android.search via Frida...")
    pid = device.spawn(["com.nhn.android.search"])
    session = device.attach(pid)
    is_spawn = True
with open(js_script, "r", encoding="utf-8") as f:
    code = f.read()

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

script.load()
if is_spawn:
    device.resume(pid)
print("[+] Pure Dynamic Device Randomizer Hooks Injected Successfully!", flush=True)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    session.detach()
