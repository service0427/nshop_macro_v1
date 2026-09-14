#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 1-Cycle MITM Packet Inspection with Frida SSL Unpinning on R3CR70KAZDM
"""

import os
import sys
import time
import json
import glob
import shutil
import subprocess
from urllib.parse import urlparse, parse_qs

DEVICE_ID = "R3CR70KAZDM"
BASE_DIR = "/home/tech/nshop_macro_v1"
LOG_DIR = f"{BASE_DIR}/logs/mitm_test_cycle"

sys.path.insert(0, BASE_DIR)
from src.modules.soft_reboot_mutator import SoftRebootMutator

def clean_device_proxy():
    print("[*] Cleaning up proxy & mitmdump & frida...")
    subprocess.run(["adb", "-s", DEVICE_ID, "shell", "settings put global http_proxy :0; settings delete global global_http_proxy_host; settings delete global global_http_proxy_port"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["adb", "-s", DEVICE_ID, "reverse", "--remove-all"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "-f", "mitmdump"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "-f", "run_frida_spawn.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)

def main():
    clean_device_proxy()
    
    if os.path.exists(LOG_DIR):
        shutil.rmtree(LOG_DIR)
    os.makedirs(LOG_DIR, exist_ok=True)
    
    print("=" * 80)
    print(f"🚀 [MITM + Frida SSL Unpinning 1회 사이클] 단말기: {DEVICE_ID}")
    print(f"📂 로그 저장소: {LOG_DIR}")
    print("=" * 80)
    
    # 1. Start mitmdump
    print("[1/5] mitmdump 패킷 프록시 기동 (포트 8888)...")
    env = os.environ.copy()
    env["CAPTURE_LOG_DIR"] = LOG_DIR
    mitm_cmd = [
        "/home/tech/.local/bin/mitmdump",
        "-p", "8888",
        "-s", f"{BASE_DIR}/src/lib/pure_mitm_addon.py",
        "--ssl-insecure",
        "--quiet"
    ]
    mitm_proc = subprocess.Popen(mitm_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.0)
    
    # 2. Reverse port forward & set proxy
    print("[2/5] 단말기 Reverse 포트포워딩 및 HTTP 프록시 주입 (127.0.0.1:8888)...")
    subprocess.run(["adb", "-s", DEVICE_ID, "reverse", "tcp:8888", "tcp:8888"])
    subprocess.run(["adb", "-s", DEVICE_ID, "shell", "settings put global http_proxy 127.0.0.1:8888"])
    time.sleep(1.0)
    
    # 3. Soft Reboot (FRESH)
    print("[3/5] 초고속 소프트 리셋 신원 변조 (FRESH 모드)...")
    mutator = SoftRebootMutator(DEVICE_ID)
    mut_res = mutator.mutate_identity(mode="FRESH")
    print(f"  ↳ 신규 발급 SSAID: {mut_res.get('ssaid')} | ADID: {mut_res.get('adid')}")
    
    # Re-apply proxy after soft reboot
    time.sleep(2.0)
    subprocess.run(["adb", "-s", DEVICE_ID, "reverse", "tcp:8888", "tcp:8888"])
    subprocess.run(["adb", "-s", DEVICE_ID, "shell", "settings put global http_proxy 127.0.0.1:8888"])
    time.sleep(1.0)
    
    # 4. Compile Frida hook and spawn app
    print("[4/5] Frida SSL Pinning Bypass 훅 컴파일 및 네이버 앱 Spawn...")
    subprocess.run(["/home/tech/.local/bin/frida-compile", f"{BASE_DIR}/src/lib/hooks/network_hook.js", "-o", f"{BASE_DIR}/src/lib/hooks/compiled_network_hook.js"], check=False)
    
    frida_proc = subprocess.Popen([
        sys.executable, "-u", f"{BASE_DIR}/src/run_frida_spawn.py",
        DEVICE_ID, f"{BASE_DIR}/src/lib/hooks/compiled_network_hook.js"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5.0)
    
    # 5. Execute search '노트북' via ADB Keyboard & enter
    print("[5/5] '노트북' 검색 및 nlogapp 텔레메트리 패킷 유발...")
    subprocess.run(["adb", "-s", DEVICE_ID, "shell", "input tap 540 540"])
    time.sleep(1.5)
    subprocess.run(["adb", "-s", DEVICE_ID, "shell", "am broadcast -a ADB_INPUT_TEXT --es msg \"노트북\" 2>/dev/null; input keyevent 66"])
    time.sleep(3.0)
    
    # Light scroll to trigger view/impression beacons
    subprocess.run(["adb", "-s", DEVICE_ID, "shell", "input swipe 540 1600 540 1000 300"])
    time.sleep(2.0)
    subprocess.run(["adb", "-s", DEVICE_ID, "shell", "input swipe 540 1000 540 1600 300"])
    time.sleep(10.0)
    
    # 6. Teardown
    print("[*] 사이클 완료! 프록시 정리 및 로그 파싱 시작...")
    subprocess.run(["adb", "-s", DEVICE_ID, "shell", "am force-stop com.nhn.android.search"])
    clean_device_proxy()
    
    # 7. Parse captured packets
    json_files = sorted(glob.glob(f"{LOG_DIR}/*.json"))
    print("\n" + "=" * 80)
    print(f"📊 [MITM 패킷 심층 분석 결과] 총 수집된 패킷: {len(json_files)}개")
    print("=" * 80)
    
    nlog_packets = []
    install_time_hits = []
    nlog_details = []
    
    for jf in json_files:
        try:
            with open(jf, "r", encoding="utf-8") as f:
                data = json.load(f)
            req = data.get("request", {})
            url = req.get("url", "")
            headers = req.get("headers", {})
            body = req.get("body", "")
            raw_str = json.dumps(req, ensure_ascii=False)
            
            # Check for nlog / tracking hosts
            if any(h in url for h in ["nlog", "nlogapp", "l.naver.com", "cc.naver.com", "nelo", "g.naver.com"]):
                nlog_packets.append({
                    "file": os.path.basename(jf),
                    "url": url,
                    "body": body,
                    "headers": headers
                })
                
            # Check for install time keywords
            keywords = ["install", "firstInstall", "installTime", "installTimestamp", "install_time", "it=", "ft=", "ut="]
            for kw in keywords:
                if kw.lower() in raw_str.lower():
                    install_time_hits.append({
                        "file": os.path.basename(jf),
                        "keyword": kw,
                        "url": url,
                        "body": body,
                        "raw": raw_str
                    })
                    break
        except Exception as e:
            pass
            
    print(f"• nlog / 텔레메트리 패킷 수: {len(nlog_packets)}개")
    print(f"• 설치시간/타임스탬프 관련 키워드 검출 패킷: {len(install_time_hits)}개")
    
    print("\n--- [1. nlogapp / 텔레메트리 요청 목록] ---")
    for idx, p in enumerate(nlog_packets[:10], 1):
        print(f"[{idx}] 파일: {p['file']}")
        print(f"    URL: {p['url'][:110]}...")
        if p['body']:
            b_str = str(p['body'])
            if len(b_str) > 200: b_str = b_str[:200] + "..."
            print(f"    Body: {b_str}")
        print()
        
    print("--- [2. 설치시간(Install Time) 및 식별자 수집 내역 상세] ---")
    for hit in install_time_hits[:10]:
        print(f"• [파일: {hit['file']}] Keyword: '{hit['keyword']}'")
        print(f"  URL: {hit['url']}")
        if hit['body']:
            print(f"  Body: {hit['body']}")
        else:
            parsed = urlparse(hit['url'])
            qs = parse_qs(parsed.query)
            print(f"  Query Params: {qs}")
        print("-" * 60)

    print("\n" + "=" * 80)
    print(" [✓] 1회 MITM 패킷 검증 및 nlogapp 수집 분석 완료!")
    print("=" * 80)

if __name__ == "__main__":
    main()
