#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 Frida Interactive Hook & Search Test ('노트북' 실시간 응답 가로채기 & 화면 대기)
Target Device: R3CR70KAZDM
"""

import sys
import os
sys.path.insert(0, '/home/tech/nshop_macro_v1')

import time
import subprocess
import frida
from src.modules.macro_core import NaverMacroCore

DEVICE_ID = "R3CR70KAZDM"
SEARCH_KEYWORD = "노트북"
PORT = 27042

print(f"==========================================================================")
print(f"🚀 [Frida Test] '{DEVICE_ID}' 단말기 대상 '{SEARCH_KEYWORD}' 0.001s 실시간 가로채기 & 대기 시작")
print(f"==========================================================================")

# 1. Port Forwarding
subprocess.run(["adb", "-s", DEVICE_ID, "forward", f"tcp:{PORT}", f"tcp:{PORT}"], check=False)
time.sleep(0.5)

# 2. Frida Manager 연결
mgr = frida.get_device_manager()
device = None
for attempt in range(1, 6):
    try:
        device = mgr.add_remote_device(f"127.0.0.1:{PORT}")
        procs = device.enumerate_processes()
        print(f"[✓] Frida Server 연결 성공 ({len(procs)}개 프로세스 감지)")
        break
    except Exception as e:
        print(f"[*] Frida 연결 재시도 ({attempt}/5): {e}")
        time.sleep(1.0)

if not device:
    print("❌ [오류] Frida 연결 실패")
    sys.exit(1)

# 3. 앱 종료 후 Fresh Spawn
print("[*] com.nhn.android.search 앱 Fresh Spawn 실행...")
subprocess.run(["adb", "-s", DEVICE_ID, "shell", "am force-stop com.nhn.android.search"], check=False)
time.sleep(0.5)

pid = device.spawn(["com.nhn.android.search"])
session = device.attach(pid)

# 4. Compiled Hook 스크립트 로드
hook_path = "/home/tech/nshop_macro_v1/src/lib/hooks/compiled_network_hook.js"
with open(hook_path, "r", encoding="utf-8") as f:
    hook_code = f.read()

intercepted_results = []

def on_message(message, data):
    if message['type'] == 'send':
        payload = message['payload']
        if isinstance(payload, dict) and payload.get("type") == "SEARCH_RESPONSE_INTERCEPTED":
            has_price = payload.get("has_price_comp")
            mids = payload.get("mids", [])
            print(f"\n⚡⚡ [Frida 0.001s 실시간 가로채기 감지!]")
            print(f"   • Gate 1 (네이버 가격비교 섹션): {'✅ 존재' if has_price else '❌ 없음'}")
            print(f"   • Gate 2 (추출된 타겟 MID 수): {len(mids)}개")
            print(f"   • MID 샘플: {mids[:5]}\n")
            intercepted_results.append(payload)
        else:
            print(f"[Frida Send] {payload}", flush=True)
    elif message['type'] == 'log':
        print(f"[Frida Log] {message['payload']}", flush=True)
    elif message['type'] == 'error':
        print(f"[Frida Err] {message['description']}", flush=True)
    else:
        print(f"[Frida Msg] {message}", flush=True)

def on_spawn_added(spawn):
    if "com.nhn.android.search" in spawn.identifier:
        try:
            child_session = device.attach(spawn.pid)
            child_script = child_session.create_script(hook_code)
            child_script.on('message', on_message)
            child_script.load()
        except Exception:
            pass
    try:
        device.resume(spawn.pid)
    except Exception:
        pass

device.on('spawn-added', on_spawn_added)
try:
    device.enable_spawn_gating()
except Exception:
    pass

script = session.create_script(hook_code)
script.on('message', on_message)
script.load()
print("[✓] 0.001초 응답 인터셉터가 포함된 Frida 스크립트 로드 완료!")

# 5. 프로세스 재개
device.resume(pid)
subprocess.run(["adb", "-s", DEVICE_ID, "shell", "am start -n com.nhn.android.search/.ui.pages.SearchHomePage"], check=False)
print(f"[✓] 앱 프로세스 재개 완료 (PID: {pid})")
time.sleep(3.0)

# 6. MacroCore를 통한 '노트북' 검색 실행
core = NaverMacroCore(DEVICE_ID)
print(f"[*] 검색 모드 진입 및 '{SEARCH_KEYWORD}' 타이핑...")
core.enter_search_mode()
core.execute_search(SEARCH_KEYWORD)

# 7. 검색 결과 화면 XML 덤프 및 PNG 캡처 저장
xml_dest = "/home/tech/nshop_macro_v1/tests/notebook_search_dump.xml"
png_dest = "/home/tech/nshop_macro_v1/tests/notebook_search_dump.png"

subprocess.run(["adb", "-s", DEVICE_ID, "shell", "uiautomator dump /sdcard/nb_screen.xml"], check=False)
subprocess.run(["adb", "-s", DEVICE_ID, "pull", "/sdcard/nb_screen.xml", xml_dest], check=False)
subprocess.run(["adb", "-s", DEVICE_ID, "shell", "screencap -p /sdcard/nb_screen.png"], check=False)
subprocess.run(["adb", "-s", DEVICE_ID, "pull", "/sdcard/nb_screen.png", png_dest], check=False)

print(f"==========================================================================")
print(f"🎉 [성공] '{SEARCH_KEYWORD}' Frida 실시간 가로채기 및 화면 대기 세션 활성 중!")
print(f"  • XML 덤프: {xml_dest}")
print(f"  • PNG 캡처: {png_dest}")
print(f"  • 상태: 무한 대기 (화면 유지 및 상호작용 분석 가능)")
print(f"==========================================================================")

# 8. 무한 대기 루프
try:
    while True:
        time.sleep(1.0)
except KeyboardInterrupt:
    print("\n[*] 사용자에 의해 대기 종료됨.")
