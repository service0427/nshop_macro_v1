#!/usr/bin/env python3
# ==============================================================================
#  N-Shop 3-New (REAL OS SOFT REBOOT) + 1-Reuse Session Affinity Simulation
# ==============================================================================

import os
import sys
import time
import json
import subprocess
import urllib.request

API_BASE = "http://127.0.0.1:5050"
DEVICE_ID = "R3CRC0K2K7D"

def api_post(endpoint, data):
    req = urllib.request.Request(
        f"{API_BASE}{endpoint}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    return json.loads(res.read().decode("utf-8"))

print("==========================================================================")
print(" 🚀 STARTING REAL OS SOFT REBOOT (3-NEW + 1-REUSE) SIMULATION TEST")
print("==========================================================================")

profiles_history = []

# --- Run #1: Fresh Unique Profile #1 (Real OS Soft Reboot, IP: 211.234.100.1) ---
ip1 = "211.234.100.1"
print(f"\n[RUN 1/4] [REAL OS SOFT REBOOT #1] Generating Fresh Profile #1 for IP '{ip1}' (Keyword: '노트북')...")
subprocess.run(f"python3 /home/tech/nshop_macro_v1/src/randomize_physical_device_id.py {DEVICE_ID} com.nhn.android.search", shell=True)
cmd1 = f"./run.sh {DEVICE_ID} --no-reboot --ip \"{ip1}\" -k \"노트북\" -p \"87528666743\" --sleep 2"
subprocess.run(cmd1, shell=True, cwd="/home/tech/nshop_macro_v1")

bk1 = api_post("/api/v1/profiles/backup", {"device_id": DEVICE_ID, "ip_address": ip1})
profiles_history.append({"run": 1, "ip": ip1, "android_id": bk1.get("android_id"), "ntracker": bk1.get("ntracker_keys_found")})
print(f"  [✓] Profile #1 Saved to API: Android ID = {bk1.get('android_id')}")

# --- Run #2: Fresh Unique Profile #2 (Real OS Soft Reboot, IP: 211.234.100.2) ---
ip2 = "211.234.100.2"
print(f"\n[RUN 2/4] [REAL OS SOFT REBOOT #2] Generating Fresh Profile #2 for IP '{ip2}' (Keyword: '샴푸')...")
subprocess.run(f"python3 /home/tech/nshop_macro_v1/src/randomize_physical_device_id.py {DEVICE_ID} com.nhn.android.search", shell=True)
cmd2 = f"./run.sh {DEVICE_ID} --no-reboot --ip \"{ip2}\" -k \"샴푸\" --sleep 2"
subprocess.run(cmd2, shell=True, cwd="/home/tech/nshop_macro_v1")

bk2 = api_post("/api/v1/profiles/backup", {"device_id": DEVICE_ID, "ip_address": ip2})
profiles_history.append({"run": 2, "ip": ip2, "android_id": bk2.get("android_id"), "ntracker": bk2.get("ntracker_keys_found")})
print(f"  [✓] Profile #2 Saved to API: Android ID = {bk2.get('android_id')}")

# --- Run #3: Fresh Unique Profile #3 (Real OS Soft Reboot, IP: 211.234.100.3) ---
ip3 = "211.234.100.3"
print(f"\n[RUN 3/4] [REAL OS SOFT REBOOT #3] Generating Fresh Profile #3 for IP '{ip3}' (Keyword: '마우스')...")
subprocess.run(f"python3 /home/tech/nshop_macro_v1/src/randomize_physical_device_id.py {DEVICE_ID} com.nhn.android.search", shell=True)
cmd3 = f"./run.sh {DEVICE_ID} --no-reboot --ip \"{ip3}\" -k \"마우스\" --sleep 2"
subprocess.run(cmd3, shell=True, cwd="/home/tech/nshop_macro_v1")

bk3 = api_post("/api/v1/profiles/backup", {"device_id": DEVICE_ID, "ip_address": ip3})
profiles_history.append({"run": 3, "ip": ip3, "android_id": bk3.get("android_id"), "ntracker": bk3.get("ntracker_keys_found")})
print(f"  [✓] Profile #3 Saved to API: Android ID = {bk3.get('android_id')}")

# --- Run #4: REUSING Profile #1 via REST API (IP: 211.234.100.1) ---
print(f"\n[RUN 4/4] [SESSION REUSE] IP '{ip1}' Recurred! Querying Profile #1 from REST API and Injecting...")
cmd4 = f"./run.sh {DEVICE_ID} --reuse --ip \"{ip1}\" -k \"노트북\" -p \"87528666743\" --sleep 2"
subprocess.run(cmd4, shell=True, cwd="/home/tech/nshop_macro_v1")

cur_aid = subprocess.run(f"adb -s {DEVICE_ID} shell 'settings get secure android_id'", shell=True, capture_output=True, text=True).stdout.strip()
profiles_history.append({"run": 4, "ip": ip1, "android_id": cur_aid, "reused_from_run_1": (cur_aid == profiles_history[0]["android_id"])})

print("\n==========================================================================")
print(" 📊 REAL OS SOFT REBOOT (3-NEW + 1-REUSE) SIMULATION SUMMARY REPORT")
print("==========================================================================")
for p in profiles_history:
    r = p["run"]
    ip = p["ip"]
    aid = p["android_id"]
    if r == 4:
        match_str = "✅ REUSED MATCHED PROFILE #1!" if p.get("reused_from_run_1") else "❌ MISMATCH"
        print(f" Run #{r} | IP: {ip:15s} | Android ID: {aid} | Mode: REUSE -> {match_str}")
    else:
        print(f" Run #{r} | IP: {ip:15s} | Android ID: {aid} | Mode: REAL OS SOFT REBOOT (NEW IDENTITY)")
print("==========================================================================")
