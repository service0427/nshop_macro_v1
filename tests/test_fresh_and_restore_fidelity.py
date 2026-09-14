#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 Full Fidelity Verification:
1. FRESH Mutation (Profile A) -> Run search -> Save snapshot -> Record all parameters
2. FRESH Mutation (Profile B) -> Verify 100% parameter differences between A and B (Zero Duplicates)
3. RESTORE Mutation (Profile A) -> Verify 100% state restoration back to Profile A (Exact Match)
"""

import os
import sys
import time
import json
import sqlite3
import tarfile
import tempfile
import glob
import subprocess
import xml.etree.ElementTree as ET

DEVICE_ID = "R3CR70FFFEK"
BASE_DIR = "/home/tech/nshop_macro_v1"
sys.path.insert(0, BASE_DIR)

from src.modules.soft_reboot_mutator import SoftRebootMutator
from src.modules.macro_core import NaverMacroCore

def extract_all_device_state(device_id: str, label: str):
    """단말기의 모든 신원, 쿠키, SharedPreferences, 시스템 설정 전수 수집"""
    time.sleep(1.0)
    
    state = {
        "label": label,
        "system": {},
        "cookies": {},
        "shared_prefs": {},
        "databases": []
    }
    
    # 1. System Settings
    ssaid = subprocess.run(["adb", "-s", device_id, "shell", "su -c 'cat /data/local/tmp/current_ssaid.txt 2>/dev/null'"], capture_output=True, text=True).stdout.strip()
    if not ssaid:
        ssaid = subprocess.run(["adb", "-s", device_id, "shell", "settings get secure android_id"], capture_output=True, text=True).stdout.strip()
    state["system"]["ssaid"] = ssaid
    
    # 2. Extract /data/data/com.nhn.android.search
    tmp_dir = tempfile.mkdtemp()
    tar_path = f"/data/local/tmp/state_{label}_{device_id}.tar.gz"
    local_tar = f"{tmp_dir}/state_{label}.tar.gz"
    
    dump_cmd = f"""
cd /data/data/com.nhn.android.search
TARGETS=""
for d in app_xwhale app_webview databases shared_prefs files; do
    [ -e "$d" ] && TARGETS="$TARGETS $d"
done
if [ -n "$TARGETS" ]; then
    tar -czf {tar_path} $TARGETS 2>/dev/null || true
fi
"""
    subprocess.run(["adb", "-s", device_id, "shell", "su"], input=dump_cmd, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["adb", "-s", device_id, "pull", tar_path, local_tar], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["adb", "-s", device_id, "shell", "su"], input=f"rm -f {tar_path}", text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    extract_dir = f"{tmp_dir}/extracted"
    os.makedirs(extract_dir, exist_ok=True)
    if os.path.exists(local_tar) and os.path.getsize(local_tar) > 0:
        try:
            with tarfile.open(local_tar, "r:gz") as t:
                t.extractall(extract_dir)
        except Exception:
            pass
            
        # Parse Cookies
        cookie_dbs = glob.glob(f"{extract_dir}/**/Cookies", recursive=True)
        for cdb in cookie_dbs:
            try:
                conn = sqlite3.connect(cdb)
                c = conn.cursor()
                c.execute("SELECT name, value, host_key FROM cookies")
                for name, val, host in c.fetchall():
                    state["cookies"][f"{name}@{host}"] = val
                conn.close()
            except Exception:
                pass
                
        # Parse SharedPreferences
        pref_xmls = glob.glob(f"{extract_dir}/**/shared_prefs/*.xml", recursive=True)
        for pxml in pref_xmls:
            pname = os.path.basename(pxml)
            try:
                tree = ET.parse(pxml)
                for elem in tree.getroot():
                    k = elem.get("name")
                    v = elem.get("value") or elem.text
                    if k:
                        state["shared_prefs"][f"{pname}:{k}"] = v
            except Exception:
                pass
                
        # Databases list
        dbs = glob.glob(f"{extract_dir}/**/databases/*.db", recursive=True)
        state["databases"] = [os.path.basename(d) for d in dbs]
        
    return state

def main():
    print("=" * 80)
    print(f"🧪 [신규 디바이스 완전 변조 & 100% 원본 복원 정밀 무결성 검증] 단말기: {DEVICE_ID}")
    print("=" * 80)
    
    mut = SoftRebootMutator(DEVICE_ID)
    macro = NaverMacroCore(DEVICE_ID)
    
    # =========================================================================
    # STEP 1: Profile A 생성 (FRESH)
    # =========================================================================
    print("\n" + "#" * 60)
    print("🔹 [STAGE 1] 프로필 A 신규 생성 (FRESH)")
    print("#" * 60)
    mut_a = mut.mutate_identity(mode="FRESH", reset_method="SELECTIVE")
    print(f"  • Profile A SSAID: {mut_a.get('ssaid')}")
    print(f"  • Profile A ADID: {mut_a.get('adid')}")
    print(f"  • Profile A InstallTS: {mut_a.get('install_ts')}")
    print(f"  • Profile A GPS: ({mut_a.get('gps_lat')}, {mut_a.get('gps_lng')})")
    
    print("[*] 네이버 앱 기동 및 '노트북' 검색 (세션 활성화)...")
    macro.launch_clean_home()
    macro.enter_search_mode()
    macro.execute_search("노트북")
    time.sleep(3.0)
    
    print("[*] Profile A 스냅샷 저장 (pf_fidelity_A)...")
    snap_a, size_a = mut.save_profile_snapshot("pf_fidelity_A")
    subprocess.run(["adb", "-s", DEVICE_ID, "shell", "am force-stop com.nhn.android.search"])
    
    state_a = extract_all_device_state(DEVICE_ID, "Profile_A_Origin")
    print(f"  ↳ Profile A 쿠키 수: {len(state_a['cookies'])}개 | Prefs: {len(state_a['shared_prefs'])}개")
    print(f"  ↳ Profile A NNB: {state_a['cookies'].get('NNB@.naver.com')} | NAC: {state_a['cookies'].get('NAC@.naver.com')}")
    
    # =========================================================================
    # STEP 2: Profile B 생성 (FRESH) -> A와 B의 전수 비교 (중복성 검사)
    # =========================================================================
    print("\n" + "#" * 60)
    print("🔹 [STAGE 2] 프로필 B 신규 생성 (FRESH) - 완전 새로운 디바이스 전환")
    print("#" * 60)
    mut_b = mut.mutate_identity(mode="FRESH", reset_method="SELECTIVE")
    print(f"  • Profile B SSAID: {mut_b.get('ssaid')}")
    print(f"  • Profile B ADID: {mut_b.get('adid')}")
    print(f"  • Profile B InstallTS: {mut_b.get('install_ts')}")
    print(f"  • Profile B GPS: ({mut_b.get('gps_lat')}, {mut_b.get('gps_lng')})")
    
    print("[*] 네이버 앱 기동 및 '키보드' 검색 (세션 활성화)...")
    macro.launch_clean_home()
    macro.enter_search_mode()
    macro.execute_search("키보드")
    time.sleep(3.0)
    
    print("[*] Profile B 스냅샷 저장 (pf_fidelity_B)...")
    snap_b, size_b = mut.save_profile_snapshot("pf_fidelity_B")
    subprocess.run(["adb", "-s", DEVICE_ID, "shell", "am force-stop com.nhn.android.search"])
    
    state_b = extract_all_device_state(DEVICE_ID, "Profile_B_Origin")
    print(f"  ↳ Profile B 쿠키 수: {len(state_b['cookies'])}개 | Prefs: {len(state_b['shared_prefs'])}개")
    print(f"  ↳ Profile B NNB: {state_b['cookies'].get('NNB@.naver.com')} | NAC: {state_b['cookies'].get('NAC@.naver.com')}")
    
    # =========================================================================
    # STEP 3: Profile A 복원 (RESTORE) -> 원본 A와 복원 A의 일치성 검사
    # =========================================================================
    print("\n" + "#" * 60)
    print("🔹 [STAGE 3] 프로필 A 완전 복원 (RESTORE pf_fidelity_A)")
    print("#" * 60)
    mut_a_restored = mut.mutate_identity(
        mode="RESTORE",
        profile_tar=snap_a,
        ssaid=mut_a["ssaid"],
        adid=mut_a["adid"],
        install_ts=mut_a["install_ts"],
        update_ts=mut_a["update_ts"],
        mock_lat=mut_a["gps_lat"],
        mock_lng=mut_a["gps_lng"],
        reset_method="SELECTIVE"
    )
    
    state_a_restored = extract_all_device_state(DEVICE_ID, "Profile_A_Restored")
    print(f"  ↳ 복원된 Profile A 쿠키 수: {len(state_a_restored['cookies'])}개 | Prefs: {len(state_a_restored['shared_prefs'])}개")
    print(f"  ↳ 복원된 Profile A NNB: {state_a_restored['cookies'].get('NNB@.naver.com')} | NAC: {state_a_restored['cookies'].get('NAC@.naver.com')}")
    
    # =========================================================================
    # 📊 종합 정밀 분석 보고서
    # =========================================================================
    print("\n" + "=" * 80)
    print("📊 [1] 신규 디바이스 격리도 검증 (Profile A vs Profile B - 독립성)")
    print("=" * 80)
    
    diff_checks = [
        ("SSAID (Android ID)", mut_a["ssaid"], mut_b["ssaid"]),
        ("ADID (Google Ad ID)", mut_a["adid"], mut_b["adid"]),
        ("Install Timestamp (ms)", mut_a["install_ts"], mut_b["install_ts"]),
        ("GPS Latitude", mut_a["gps_lat"], mut_b["gps_lat"]),
        ("GPS Longitude", mut_a["gps_lng"], mut_b["gps_lng"]),
        ("NNB Cookie", state_a["cookies"].get("NNB@.naver.com"), state_b["cookies"].get("NNB@.naver.com")),
        ("NAC Cookie", state_a["cookies"].get("NAC@.naver.com"), state_b["cookies"].get("NAC@.naver.com")),
        ("NAPP_DI Cookie", state_a["cookies"].get("NAPP_DI@.naver.com"), state_b["cookies"].get("NAPP_DI@.naver.com")),
        ("GFP SDK NAC Token", state_a["shared_prefs"].get("com.naver.gfpsdk.nac.xml:nac"), state_b["shared_prefs"].get("com.naver.gfpsdk.nac.xml:nac")),
    ]
    
    all_diff_pass = True
    for label, val_a, val_b in diff_checks:
        is_different = (val_a != val_b) and (val_a is not None) and (val_b is not None)
        status_icon = "✅ PASS" if is_different else "❌ FAIL"
        if not is_different: all_diff_pass = False
        print(f"• {label:<25}: {status_icon}")
        print(f"   - Profile A: {str(val_a)[:40]}")
        print(f"   - Profile B: {str(val_b)[:40]}")
        
    print("\n" + "=" * 80)
    print("📊 [2] 100% 원본 복원 무결성 검증 (Profile A Origin vs Profile A Restored - 일치성)")
    print("=" * 80)
    
    match_checks = [
        ("SSAID (Android ID)", mut_a["ssaid"], state_a_restored["system"]["ssaid"]),
        ("ADID (Google Ad ID)", mut_a["adid"], mut_a_restored["adid"]),
        ("Install Timestamp (ms)", mut_a["install_ts"], mut_a_restored["install_ts"]),
        ("GPS Latitude", mut_a["gps_lat"], mut_a_restored["gps_lat"]),
        ("GPS Longitude", mut_a["gps_lng"], mut_a_restored["gps_lng"]),
        ("NNB Cookie", state_a["cookies"].get("NNB@.naver.com"), state_a_restored["cookies"].get("NNB@.naver.com")),
        ("NAC Cookie", state_a["cookies"].get("NAC@.naver.com"), state_a_restored["cookies"].get("NAC@.naver.com")),
        ("NAPP_DI Cookie", state_a["cookies"].get("NAPP_DI@.naver.com"), state_a_restored["cookies"].get("NAPP_DI@.naver.com")),
        ("GFP SDK NAC Token", state_a["shared_prefs"].get("com.naver.gfpsdk.nac.xml:nac"), state_a_restored["shared_prefs"].get("com.naver.gfpsdk.nac.xml:nac")),
    ]
    
    all_match_pass = True
    for label, val_orig, val_rest in match_checks:
        is_matched = (val_orig == val_rest) and (val_orig is not None)
        status_icon = "✅ 100% 일치" if is_matched else "❌ 불일치"
        if not is_matched: all_match_pass = False
        print(f"• {label:<25}: {status_icon}")
        print(f"   - 원본 Profile A : {str(val_orig)[:40]}")
        print(f"   - 복원 Profile A : {str(val_rest)[:40]}")

    print("\n" + "=" * 80)
    if all_diff_pass and all_match_pass:
        print("🎉 [최종 판정: PERFECT SUCCESS] 완벽한 신규 디바이스 격리(0% 중복) 및 100% 원본 복원 성공!")
    else:
        print("🚨 [최종 판정: PARTIAL FAILURE] 일부 항목 검증 불일치 발생")
    print("=" * 80)
    
    # Cleanup test files
    subprocess.run(["adb", "-s", DEVICE_ID, "shell", f"su -c 'rm -f {snap_a} {snap_b}'"])

if __name__ == "__main__":
    main()
