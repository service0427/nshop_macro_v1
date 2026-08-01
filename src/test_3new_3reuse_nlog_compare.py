#!/usr/bin/env python3
# ==============================================================================
#  N-Shop 3-New (Soft Reboot) + 3-Reuse Full Unfiltered MITM Traffic Suite
# ==============================================================================

import os
import sys
import time
import json
import glob
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
print(" 🚀 STARTING FULL UNFILTERED MITM TRAFFIC CAPTURE SUITE (3-FRESH + 3-REUSE)")
print("==========================================================================")

# Ensure REST API server is listening
try:
    urllib.request.urlopen(f"{API_BASE}/api/v1/health")
except Exception:
    print("[*] Launching REST API server on port 5050...")
    subprocess.Popen(["python3", "/home/tech/nshop_macro_v1/api/session_server.py"])
    time.sleep(2)

results = []

def run_step(run_idx, mode, ip, keyword, target_p=None):
    print(f"\n==========================================================================")
    print(f" [RUN {run_idx}/6] Mode: {mode:6s} | IP: {ip:15s} | Keyword: {keyword}")
    print(f"==========================================================================")
    
    if mode == "FRESH":
        print(f"  [*] Executing OS Soft Reboot for Fresh Physical Identity...")
        subprocess.run(f"python3 /home/tech/nshop_macro_v1/src/randomize_physical_device_id.py {DEVICE_ID} com.nhn.android.search", shell=True)
        p_arg = f"-p \"{target_p}\"" if target_p else ""
        cmd = f"./run.sh {DEVICE_ID} --no-reboot --mitm --ip \"{ip}\" -k \"{keyword}\" {p_arg} --sleep 2"
        subprocess.run(cmd, shell=True, cwd="/home/tech/nshop_macro_v1")
        
        bk = api_post("/api/v1/profiles/backup", {"device_id": DEVICE_ID, "ip_address": ip})
        saved_aid = bk.get("android_id", "")
        print(f"  [✓] Fresh Profile Saved to API DB (Android ID: {saved_aid})")
    else:
        # Mode: REUSE
        p_arg = f"-p \"{target_p}\"" if target_p else ""
        cmd = f"./run.sh {DEVICE_ID} --reuse --mitm --ip \"{ip}\" -k \"{keyword}\" {p_arg} --sleep 2"
        subprocess.run(cmd, shell=True, cwd="/home/tech/nshop_macro_v1")
    
    date_str = time.strftime("%m%d")
    log_pattern = f"/home/tech/nshop_macro_v1/logs/naver_v1/{date_str}/{DEVICE_ID}/*"
    log_dirs = sorted(glob.glob(log_pattern), key=os.path.getmtime, reverse=True)
    
    log_dir = log_dirs[0] if log_dirs else ""
    captured_json_files = glob.glob(os.path.join(log_dir, "[0-9][0-9][0-9]_*.json")) if log_dir else []
    captured_json_files.sort()
    
    all_requests = []
    if log_dir and os.path.exists(os.path.join(log_dir, "all_requests.log")):
        with open(os.path.join(log_dir, "all_requests.log"), "r", encoding="utf-8") as f:
            all_requests = [line.strip() for line in f if line.strip()]

    cur_aid = subprocess.run(f"adb -s {DEVICE_ID} shell 'settings get secure android_id'", shell=True, capture_output=True, text=True).stdout.strip()
    
    info = {
        "run": run_idx,
        "mode": mode,
        "ip": ip,
        "keyword": keyword,
        "android_id": cur_aid,
        "json_files_count": len(captured_json_files),
        "total_requests_captured": len(all_requests),
        "request_logs": all_requests,
        "log_dir": log_dir
    }
    results.append(info)
    return info

# Execute 3 Fresh Runs
run_step(1, "FRESH", "211.234.200.1", "노트북", "87528666743")
run_step(2, "FRESH", "211.234.200.2", "샴푸")
run_step(3, "FRESH", "211.234.200.3", "마우스")

# Execute 3 Reuse Runs
run_step(4, "REUSE", "211.234.200.1", "노트북", "87528666743")
run_step(5, "REUSE", "211.234.200.2", "샴푸")
run_step(6, "REUSE", "211.234.200.3", "마우스")

print("\n==========================================================================")
print(" 📊 FULL UNFILTERED MITM TRAFFIC REPORT (3-FRESH vs 3-REUSE)")
print("==========================================================================")

for r in results:
    idx = r["run"]
    mode = r["mode"]
    ip = r["ip"]
    aid = r["android_id"]
    req_cnt = r["total_requests_captured"]
    json_cnt = r["json_files_count"]
    
    print(f" Run #{idx} [{mode:5s}] | IP: {ip:15s} | Android ID: {aid}")
    print(f"   ├─ Log Directory     : {r['log_dir']}")
    print(f"   ├─ Total Requests    : {req_cnt} HTTP/HTTPS flows captured")
    print(f"   └─ JSON Flow Files   : {json_cnt} individual request/response JSON files created")
    
    if r["request_logs"]:
        print("   ├─ Captured Traffic Endpoints Overview:")
        for log_line in r["request_logs"][:5]:
            print(f"   │    • {log_line}")
        if len(r["request_logs"]) > 5:
            print(f"   │    ... and {len(r['request_logs']) - 5} more endpoints.")
    print("--------------------------------------------------------------------------")

print("==========================================================================")
