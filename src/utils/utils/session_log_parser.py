#!/usr/bin/env python3
import os
import re
import json
import sys

def parse_logs(log_dir, dev_id):
    # 1. Parse frida.log
    frida_log = os.path.join(log_dir, "frida.log")
    android_id = "N/A"
    appset_id = "N/A"
    if os.path.exists(frida_log):
        with open(frida_log, "r", errors="ignore") as f:
            content = f.read()
            aid_m = re.search(r"Local Hook android_id\s*->\s*([a-f0-9]+)", content)
            if aid_m: android_id = aid_m.group(1)
            asid_m = re.search(r"Local Hook AppSetIdInfo\.a\(\)\s*->\s*([a-f0-9\-]+)", content)
            if asid_m: appset_id = asid_m.group(1)

    # 2. Parse all_packets.jsonl for cookies & network-level identifiers
    packets_path = os.path.join(log_dir, "all_packets.jsonl")
    napp_di, da_dd, da_dv, nnb, nac = "N/A", "N/A", "N/A", "N/A", "N/A"
    if os.path.exists(packets_path):
        with open(packets_path, "r", errors="ignore") as f:
            for line in f:
                if not line.strip(): continue
                try:
                    data = json.loads(line)
                    req = data.get("request", {})
                    url = req.get("url", "")
                    if "nlog.naver.com" in url or "lcs.naver.com" in url or "naver.com" in url:
                        headers = req.get("headers", {})
                        cookie = headers.get("cookie", "") or headers.get("Cookie", "")
                        if cookie:
                            napp_di_m = re.search(r"NAPP_DI=([^;,\s]+)", cookie)
                            if napp_di_m: napp_di = napp_di_m.group(1)
                            da_dd_m = re.search(r"DA_DD=([^;,\s]+)", cookie)
                            if da_dd_m: da_dd = da_dd_m.group(1)
                            da_dv_m = re.search(r"DA_DV=([^;,\s]+)", cookie)
                            if da_dv_m: da_dv = da_dv_m.group(1)
                            nnb_m = re.search(r"NNB=([^;,\s]+)", cookie)
                            if nnb_m: nnb = nnb_m.group(1)
                            nac_m = re.search(r"NAC=([^;,\s]+)", cookie)
                            if nac_m: nac = nac_m.group(1)
                except: pass

    # Print clean formatted block
    print("\n============================================================")
    print("   📊 SESSION ENVIRONMENT DATA & COOKIES")
    print("============================================================")
    print(f" 📱 Device ID   : {dev_id}")
    print(f" 🤖 Android ID  : {android_id}")
    print(f" 🆔 AppSet ID   : {appset_id}")
    print(f" 🌐 NAPP_DI     : {napp_di}")
    print(f" 📢 ADID (DA_DD): {da_dd}")
    print(f" 📱 IDFV (DA_DV): {da_dv}")
    print(f" 🍪 NNB Cookie  : {nnb}")
    print(f" 🍪 NAC Cookie  : {nac}")
    print("============================================================\n")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: ./session_log_parser.py <LOG_DIR> <DEVICE_ID>")
        sys.exit(1)
    parse_logs(sys.argv[1], sys.argv[2])
