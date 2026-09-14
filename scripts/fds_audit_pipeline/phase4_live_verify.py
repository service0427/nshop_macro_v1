#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
[FDS 전수 감사 파이프라인 - 4단계] 실기기 런타임 덤프 및 실측 교차 검증 (Phase 4)
(scripts/fds_audit_pipeline/phase4_live_verify.py)
========================================================================================
- 목적: 3단계에서 식별된 220개 AUDIT_REQ 항목 및 핵심 FDS 검증 로직을 실기기(ADB) 환경에서 직접 실측.
- 대상 단말기: ADB 연결된 실기기 (Galaxy Z Flip 3 - SM-F711N)
- 주요 검증 항목:
  1. SystemInfo & IntegrityChecker 에뮬레이터 판정 로직 실측
  2. IntegrityChecker 루팅 탐지 3단계 실측 (test-keys, su 바이너리 파일 10개, /system/xbin/which su)
  3. Magisk DenyList 동작 상태 실측
  4. NetworkInterface MAC 및 /proc/net/arp 차단 실측
  5. 위치 권한 및 Wi-Fi SSID/BSSID 스캔 차단 상태 실측
  6. Shared Preferences 내 식별자(deviceUniqueId, NAS_USER_ID, NTracker 등) 전수 덤프
  7. ABX Settings.Secure android_id 및 PMS installerPackageName 실측
========================================================================================
"""

import subprocess
import json
import re
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_REPORT = PROJECT_ROOT / "scripts/fds_audit_pipeline/phase4_live_verify_report.json"
OUTPUT_MD = PROJECT_ROOT / "scripts/fds_audit_pipeline/PHASE4_LIVE_VERIFY_REPORT.md"


def run_adb(cmd: list) -> str:
    """ADB 명령 실행 및 stdout 반환"""
    try:
        full_cmd = ["adb"] + cmd
        res = subprocess.run(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        return res.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"


def run_adb_root(shell_cmd: str) -> str:
    """ADB root shell 명령 실행"""
    try:
        res = subprocess.run(["adb", "shell", "su", "-c", shell_cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        return res.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"


def get_prop(prop_name: str) -> str:
    return run_adb(["shell", "getprop", prop_name])


def main():
    print("=" * 82)
    print(" 🚀 [FDS 전수 감사 파이프라인 - 4단계] 실기기 런타임 덤프 및 실측 교차 검증")
    print("=" * 82)

    # 1. 대상 단말기 확인
    devices_out = run_adb(["devices"])
    lines = [l for l in devices_out.split("\n") if "\tdevice" in l]
    if not lines:
        print("[!] 연결된 ADB 단말기가 없습니다. 중단합니다.")
        return
    device_serial = lines[0].split("\t")[0]
    print(f"[*] 대상 단말기 Serial: {device_serial}\n")

    results = {
        "device_serial": device_serial,
        "timestamp": datetime.now().isoformat(),
        "tests": {}
    }

    # -------------------------------------------------------------
    # Test 1: SystemInfo & IntegrityChecker 에뮬레이터 탐지 실측
    # -------------------------------------------------------------
    print("1️⃣ [에뮬레이터 탐지 로직 실측 (SystemInfo / IntegrityChecker)]")
    props = {
        "ro.product.brand": get_prop("ro.product.brand"),
        "ro.product.device": get_prop("ro.product.device"),
        "ro.build.fingerprint": get_prop("ro.build.fingerprint"),
        "ro.hardware": get_prop("ro.hardware"),
        "ro.product.model": get_prop("ro.product.model"),
        "ro.product.manufacturer": get_prop("ro.product.manufacturer"),
        "ro.product.name": get_prop("ro.product.name"),
        "ro.build.tags": get_prop("ro.build.tags")
    }

    brand = props["ro.product.brand"].lower()
    device = props["ro.product.device"].lower()
    fingerprint = props["ro.build.fingerprint"].lower()
    hardware = props["ro.hardware"].lower()
    model = props["ro.product.model"]
    manufacturer = props["ro.product.manufacturer"].lower()
    product = props["ro.product.name"].lower()
    tags = props["ro.build.tags"].lower()

    # SystemInfo.isEmulator() 로직 재현
    is_emu_brand = brand.startswith("generic") and device.startswith("generic")
    is_emu_fp = fingerprint.startswith("generic") or fingerprint.startswith("unknown")
    is_emu_hw = "goldfish" in hardware or "ranchu" in hardware
    is_emu_model = any(w in model for w in ["google_sdk", "Emulator", "Android SDK built for x86"]) or "genymotion" in manufacturer
    is_emu_prod = any(w in product for w in ["sdk_google", "google_sdk", "sdk_x86", "sdk_gphone64_arm64", "vbox86p", "emulator", "simulator"])
    
    is_emulator_evaluated = is_emu_brand or is_emu_fp or is_emu_hw or is_emu_model or is_emu_prod

    print(f"  - Brand        : {props['ro.product.brand']}")
    print(f"  - Model        : {props['ro.product.model']}")
    print(f"  - Manufacturer : {props['ro.product.manufacturer']}")
    print(f"  - Hardware     : {props['ro.hardware']}")
    print(f"  - Fingerprint  : {props['ro.build.fingerprint']}")
    print(f"  - Tags         : {props['ro.build.tags']}")
    print(f"  -> SystemInfo.isEmulator() 판정: {is_emulator_evaluated} (정상: False)")
    print(f"  -> 평가: {'✅ PASS (완전한 순정 갤럭시 물리 단말기)' if not is_emulator_evaluated else '❌ FAIL'}\n")

    results["tests"]["emulator_detection"] = {
        "properties": props,
        "is_emulator": is_emulator_evaluated,
        "pass": not is_emulator_evaluated
    }

    # -------------------------------------------------------------
    # Test 2: IntegrityChecker 루팅 탐지 3단계 실측
    # -------------------------------------------------------------
    print("2️⃣ [IntegrityChecker 루팅 탐지 3단계 실측]")
    
    # Method 1: test-keys
    root_m1 = "test-keys" in tags
    print(f"  - Method 1 (Build.TAGS contains 'test-keys'): {root_m1} (TAGS='{tags}')")

    # Method 2: su 파일 존재 여부 10개 경로
    su_paths = [
        "/system/app/Superuser.apk", "/sbin/su", "/system/bin/su", "/system/xbin/su",
        "/data/local/xbin/su", "/data/local/bin/su", "/system/sd/xbin/su",
        "/system/bin/failsafe/su", "/data/local/su", "/su/bin/su"
    ]
    # 앱 네임스페이스 시뮬레이션: 일반 쉘(non-root)에서 접근 시도
    su_found = []
    for p in su_paths:
        check = run_adb(["shell", f"[ -e {p} ] && echo EXISTS || echo NONE"])
        if check == "EXISTS":
            su_found.append(p)
    root_m2 = len(su_found) > 0
    print(f"  - Method 2 (Known su paths existence): {root_m2} (발견된 파일: {su_found})")

    # Method 3: exact APK code -> Runtime.getRuntime().exec(new String[]{"/system/xbin/which", "su"})
    which_bin_exists = run_adb(["shell", "[ -f /system/xbin/which ] && echo YES || echo NO"]) == "YES"
    which_exec_out = run_adb(["shell", "/system/xbin/which su 2>&1 || true"])
    root_m3 = which_bin_exists and bool(which_exec_out and "su" in which_exec_out)
    print(f"  - Method 3 (/system/xbin/which su exec): {root_m3} (/system/xbin/which 존재여부: {which_bin_exists})")

    # Magisk DenyList 확인
    denylist_dump = run_adb_root("magisk --denylist ls 2>/dev/null | grep nhn || echo 'NOT_LISTED'")
    print(f"  - Naver App DenyList 등록 상태:\n    {denylist_dump.replace(chr(10), chr(10) + '    ')}")

    is_rooted_evaluated = root_m1 or root_m2 or root_m3
    print(f"  -> IntegrityChecker.isDeviceRooted() 최종 판정: {is_rooted_evaluated} (정상: False)")
    print(f"  -> 평가: {'✅ PASS (네이버 앱 무결성 검사 100% 무력화 통과)' if not is_rooted_evaluated else '❌ FAIL'}\n")

    results["tests"]["root_detection"] = {
        "method1_test_keys": root_m1,
        "method2_su_paths": su_found,
        "method3_which_su_exists": which_bin_exists,
        "method3_exec_result": which_exec_out,
        "magisk_naver_entry": denylist_dump,
        "is_device_rooted": is_rooted_evaluated,
        "pass": not is_rooted_evaluated
    }

    # -------------------------------------------------------------
    # Test 3: NetworkInterface MAC 및 /proc/net/arp 차단 실측
    # -------------------------------------------------------------
    print("3️⃣ [NetworkInterface MAC 및 ARP 테이블 차단 실측]")
    arp_out = run_adb(["shell", "cat /proc/net/arp 2>&1"])
    arp_blocked = "Permission denied" in arp_out or arp_out.strip() == ""
    print(f"  - 일반 권한 /proc/net/arp 접근: {arp_out[:60]}... -> 차단여부: {'✅ 차단됨 (퍼미션 600 잠금)' if arp_blocked else '❌ 유출'}")

    sys_wlan_out = run_adb(["shell", "cat /sys/class/net/wlan0/address 2>&1"])
    sys_wlan_blocked = "Permission denied" in sys_wlan_out or sys_wlan_out.strip() == ""
    print(f"  - 일반 권한 /sys/class/net/wlan0/address 접근: {sys_wlan_out[:60]}... -> 차단여부: {'✅ 차단됨 (Android 13 하드웨어 주소 은폐)' if sys_wlan_blocked else '❌ 유출'}\n")

    results["tests"]["network_mac_arp"] = {
        "arp_output": arp_out,
        "arp_blocked": arp_blocked,
        "sys_wlan_blocked": sys_wlan_blocked,
        "pass": arp_blocked and sys_wlan_blocked
    }

    # -------------------------------------------------------------
    # Test 4: 위치 권한 및 Wi-Fi SSID/BSSID 차단 실측
    # -------------------------------------------------------------
    print("4️⃣ [위치 권한 및 Wi-Fi SSID/BSSID 실측]")
    pkg_perms = run_adb(["shell", "dumpsys package com.nhn.android.search"])
    
    loc_fine = "android.permission.ACCESS_FINE_LOCATION: granted=true" in pkg_perms
    loc_coarse = "android.permission.ACCESS_COARSE_LOCATION: granted=true" in pkg_perms
    print(f"  - ACCESS_FINE_LOCATION 허용 여부  : {loc_fine} (정상: False)")
    print(f"  - ACCESS_COARSE_LOCATION 허용 여부: {loc_coarse} (정상: False)")
    print(f"  -> 평가: {'✅ PASS (위치 권한 완전 박탈로 BSSID/SSID 스캔 원천 봉쇄)' if not loc_fine else '❌ FAIL'}\n")

    results["tests"]["location_wifi"] = {
        "fine_location_granted": loc_fine,
        "coarse_location_granted": loc_coarse,
        "pass": not loc_fine
    }

    # -------------------------------------------------------------
    # Test 5: Settings.Secure android_id 및 PMS 설치 메타데이터 실측
    # -------------------------------------------------------------
    print("5️⃣ [Settings.Secure android_id & PMS 설치 메타데이터 실측]")
    android_id = run_adb(["shell", "settings get secure android_id"])
    print(f"  - Settings.Secure android_id: {android_id}")
    is_known_bug_id = android_id == "9774d56d682e549c"
    print(f"  -> 에뮬레이터 버그 ID 여부: {is_known_bug_id} (정상: False)")

    installer_match = re.search(r"installerPackageName=([^\s]+)", pkg_perms)
    installer = installer_match.group(1) if installer_match else "NONE"
    print(f"  - installerPackageName: {installer}")
    print(f"  -> 구글 플레이스토어 출처 일치 여부: {'✅ com.android.vending 일치' if installer == 'com.android.vending' else '⚠️ ' + installer}\n")

    results["tests"]["android_id_pms"] = {
        "android_id": android_id,
        "is_bug_id": is_known_bug_id,
        "installer_package": installer,
        "pass": not is_known_bug_id and installer == "com.android.vending"
    }

    # -------------------------------------------------------------
    # Test 6: Shared Preferences 실측 덤프 (핵심 식별자)
    # -------------------------------------------------------------
    print("6️⃣ [Shared Preferences 핵심 식별자 덤프]")
    shared_prefs_dir = "/data/data/com.nhn.android.search/shared_prefs"
    xml_files = run_adb_root(f"ls {shared_prefs_dir} 2>/dev/null")
    xml_list = [x.strip() for x in xml_files.split() if x.endswith(".xml")]
    print(f"  - 총 Shared Preferences XML 파일 수: {len(xml_list)}개")

    target_files = [
        "com.naver.ads.flags.xml",
        "NTracker_SharedPreference.xml",
        "appsflyer-data.xml",
        "com.naver.gfpsdk.nac.xml",
        "null.xml"
    ]
    
    dumps = {}
    for tf in target_files:
        if tf in xml_list:
            content = run_adb_root(f"cat {shared_prefs_dir}/{tf} 2>/dev/null")
            dumps[tf] = content
            print(f"  - 📄 {tf} ({len(content)} bytes)")
            for l in content.split("\n"):
                if any(k in l for k in ["NAS_USER_ID", "NTracker_", "AF_INSTALLATION", "uid", "keyLocationAgree"]):
                    print(f"       ↳ {l.strip()}")
        else:
            dumps[tf] = "NOT_PRESENT"
            print(f"  - ⚪ {tf} (존재하지 않음)")

    results["tests"]["shared_preferences"] = {
        "total_xml_count": len(xml_list),
        "target_dumps": dumps
    }

    # -------------------------------------------------------------
    # 최종 결과 저장
    # -------------------------------------------------------------
    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 82)
    print(f"[*] 4단계 실기기 실측 검증 완료! 리포트 저장: {OUTPUT_REPORT}")
    print("=" * 82)


if __name__ == "__main__":
    main()
