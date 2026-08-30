#!/usr/bin/env python3
"""
단말기별 배터리 수명 효율(ASOC), 누적 충방전 사이클, 실질 만충용량 진단 스크립트
"""
import subprocess

devices = ["R3CR70KAZDM", "R3CR70SZ0JJ", "R3CRB0WCGET", "R5CR713T5WT", "R5CR9336DSB"]

print("=" * 105)
print(f"{'단말기 시리얼':<14} | {'배터리 수명(효율)':<16} | {'누적 사이클':<12} | {'실질 만충용량 (mAh)':<20} | {'신품 설계용량':<14} | {'수명 상태':<10}")
print("=" * 105)

for d in devices:
    try:
        cmd = """su -c '
            echo -n "asoc:"; cat /sys/class/power_supply/battery/fg_asoc 2>/dev/null
            echo -n "fullcap:"; cat /sys/class/power_supply/battery/fg_fullcapnom 2>/dev/null
            echo -n "design:"; cat /sys/class/power_supply/battery/charge_full_design 2>/dev/null
            echo -n "efs_discharge:"; cat /efs/FactoryApp/batt_discharge_level 2>/dev/null
        ' """
        out = subprocess.check_output(["adb", "-s", d, "shell", cmd], timeout=4, text=True)
        asoc, fullcap, design, discharge = "?", "?", 3200, "?"
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("asoc:"): asoc = line.split("asoc:")[1].strip()
            elif line.startswith("fullcap:"): fullcap = line.split("fullcap:")[1].strip()
            elif line.startswith("design:"): design = int(int(line.split("design:")[1].strip()) / 1000)
            elif line.startswith("efs_discharge:"): discharge = line.split("efs_discharge:")[1].strip()

        cycles = f"{int(discharge)/100.0:.0f}회" if discharge.isdigit() else "?"
        asoc_int = int(asoc) if asoc.isdigit() else 100
        
        status = "🟢 매우 양호" if asoc_int >= 90 else ("🟡 보통 (양호)" if asoc_int >= 80 else "🔴 점검 필요")
        asoc_str = f"{asoc}% (아이폰 효율 기준)"

        print(f"{d:<14} | {asoc_str:<16} | {cycles:<12} | {fullcap} mAh{' ':<12} | {design} mAh{' ':<6} | {status:<10}")
    except Exception as e:
        print(f"{d:<14} | 오류 발생: {e}")

print("=" * 105)
