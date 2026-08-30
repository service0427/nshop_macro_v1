import os
import time
import datetime
import subprocess
import json

LOG_DIR = "/home/tech/nshop_macro_v1/logs/battery_history"
os.makedirs(LOG_DIR, exist_ok=True)
CSV_FILE = os.path.join(LOG_DIR, "charging_benchmark_20min.csv")
LOG_FILE = os.path.join(LOG_DIR, "charging_benchmark_20min.log")

DEVICES = ["R3CR70KAZDM", "R3CR70SZ0JJ", "R3CRB0WCGET", "R5CR713T5WT", "R5CR9336DSB"]

def get_batt_info(dev):
    level = None
    temp = None
    status = None
    try:
        out = subprocess.check_output(["adb", "-s", dev, "shell", "dumpsys battery"], timeout=4, text=True)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("level:"):
                level = int(line.split(":")[1].strip())
            elif line.startswith("temperature:"):
                temp = int(line.split(":")[1].strip()) / 10.0
            elif line.startswith("status:"):
                status = line.split(":")[1].strip()
    except Exception:
        pass
    return level, temp, status

# CSV Header if not exists
with open(CSV_FILE, "w", encoding="utf-8") as f:
    f.write("timestamp,minute,device_id,battery_level,temperature,status\n")

with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write(f"=== 20분 충전 벤치마크 시작 ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===\n")

total_minutes = 20

for minute in range(total_minutes + 1):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    print(f"[{now_str}] ⏱️ [{minute:02d}/{total_minutes}분] 실시간 배터리 측정:")
    for dev in DEVICES:
        lvl, tmp, stat = get_batt_info(dev)
        if lvl is not None:
            lines.append(f"{now_str},{minute},{dev},{lvl},{tmp},{stat}")
            log_entry = f"[{now_str}] Minute {minute:02d} | {dev}: {lvl}% | {tmp}°C"
            print(f"   ↳ {dev}: {lvl}% ({tmp}°C)")
            with open(LOG_FILE, "a", encoding="utf-8") as lf:
                lf.write(log_entry + "\n")
    
    with open(CSV_FILE, "a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
    
    if minute < total_minutes:
        time.sleep(60)

print(f"\n[✓] 20분간 충전 벤치마크 완료! ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
