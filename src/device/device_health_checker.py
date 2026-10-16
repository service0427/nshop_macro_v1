#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/device/device_health_checker.py

단말기 환경 무결성 진단 및 베이스라인 자동 동기화 모듈 (Device Baseline Health Checker)
-------------------------------------------------------------------------------------
시스템 기동 시(run.py) 전 기기를 대상으로 무조건 1회 사전 실행하여 다음 항목을 검증 및 자동 업데이트:
  1. 네이버 앱 필수 런타임 권한 (위치, 알림, 백그라운드 팝업):
     - android.permission.ACCESS_FINE_LOCATION (쇼핑탭 지역배송 및 NPay 혜택 초기화용 필수)
     - android.permission.ACCESS_COARSE_LOCATION
     - android.permission.POST_NOTIFICATIONS
     - appops: POST_NOTIFICATION, SYSTEM_ALERT_WINDOW
  2. 키보드(IME) 설정:
     - com.android.adbkeyboard/.AdbIME 활성화 및 기본 입력기 고정
  3. 화면 유지 및 잠금 해제:
     - svc power stayon true (USB 충전 중 화면 꺼짐 방지)
     - locksettings set-disabled true (화면 잠금 팝업 방지)
     - cmd device_state state 3 (폴더블 펼침 보장) & wm dismiss-keyguard
  4. 위치(GPS) 서비스 모드:
     - location_mode 3 (HIGH_ACCURACY) 및 +gps,+network 프로바이더 활성화
  5. 통신사/유심 에뮬레이션 속성 (FDS 수집 필드 대응):
     - gsm.sim.state=LOADED,LOADED, gsm.operator.numeric=45008 (KT LTE)
     - gsm.network.type=LTE,LTE, gsm.operator.isroaming=false, gsm.operator.iso-country=kr
  6. 타임존 및 로케일:
     - persist.sys.timezone=Asia/Seoul (한국 표준시)
  7. 네이버 앱 온보딩 및 위치 동의 (null.xml):
     - keyLocationAgree=true, keyLocationUserAgreementAccepted=true
     - 온보딩 코치마크 및 튜토리얼 팝업 방지 플래그 완전 주입
"""

import os
import sys
import time
import subprocess
import concurrent.futures
from typing import List, Dict, Any, Optional
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import NAVER_APP_PACKAGE, DEFAULT_DEVICE_ID
from src.device.adb_controller import run_adb_shell, force_stop_app


REQUIRED_PERMISSIONS = [
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.POST_NOTIFICATIONS"
]

REQUIRED_APPOPS = [
    ("POST_NOTIFICATION", "allow"),
    ("SYSTEM_ALERT_WINDOW", "allow"),
]

REQUIRED_GSM_PROPS = {
    "gsm.sim.state": "LOADED,LOADED",
    "gsm.operator.numeric": "45008",
    "gsm.network.type": "LTE,LTE",
    "gsm.sim.operator.numeric": "45008",
    "gsm.sim.operator.alpha": "KT",
    "gsm.operator.alpha": "KT",
    "gsm.operator.isroaming": "false",
    "gsm.operator.iso-country": "kr",
    "gsm.sim.operator.iso-country": "kr",
    "gsm.current.phone-type": "1"
}


def check_and_update_device(device_id: str, pkg: str = NAVER_APP_PACKAGE) -> Dict[str, Any]:
    """
    단일 단말기에 대한 상태 진단 및 자동 보정(Update) 수행
    """
    t0 = time.time()
    results = {
        "device_id": device_id,
        "permissions_updated": 0,
        "appops_updated": 0,
        "ime_updated": False,
        "screen_updated": False,
        "gps_mode_updated": False,
        "gsm_props_updated": 0,
        "timezone_updated": False,
        "null_xml_updated": False,
        "status": "PASS",
        "details": []
    }

    # 1. 패키지 설치 확인
    pkg_chk = run_adb_shell(device_id, f"pm path {pkg}")
    if not pkg_chk:
        results["status"] = "FAIL"
        results["details"].append(f"패키지({pkg}) 미설치")
        return results

    # 1-1. 고속 무결성 점검 (Fast-Path: ~0.1초)
    # 03_device_init.sh 또는 이전 회차에서 정상 세팅된 경우, 불필요한 force-stop 및 쓰기 작업 생략
    fast_loc_chk = run_adb_shell(device_id, f"dumpsys package {pkg} | grep 'ACCESS_FINE_LOCATION: granted=true'")
    if fast_loc_chk:
        run_adb_shell(device_id, "cmd device_state state 3 2>/dev/null; input keyevent 224; wm dismiss-keyguard")
        run_adb_shell(device_id, "su -c 'sysctl -w net.ipv6.conf.all.disable_ipv6=1 net.ipv6.conf.default.disable_ipv6=1 >/dev/null 2>&1'")
        run_adb_shell(device_id, "appops set com.genymobile.gnirehtet ACTIVATE_VPN allow 2>/dev/null; appops set com.genymobile.gnirehtet ACTIVATE_PLATFORM_VPN allow 2>/dev/null")
        results["elapsed_sec"] = round(time.time() - t0, 2)
        results["details"].append("고속 베이스라인 유지")
        return results

    # 2. 런타임 권한 확인 및 부여 (Full Path: 누락 기기 복구)
    pkg_dump = run_adb_shell(device_id, f"dumpsys package {pkg}")
    for perm in REQUIRED_PERMISSIONS:
        perm_short = perm.split(".")[-1]
        is_granted = f"{perm}: granted=true" in pkg_dump
        if not is_granted:
            grant_out = run_adb_shell(device_id, f"pm grant {pkg} {perm} 2>&1")
            results["permissions_updated"] += 1
            results["details"].append(f"권한 부여: {perm_short}")

    # 3. AppOps 확인 및 설정
    for op, val in REQUIRED_APPOPS:
        run_adb_shell(device_id, f"cmd appops set {pkg} {op} {val}")
        results["appops_updated"] += 1

    # 4. 키보드(AdbIME) 확인 및 설정
    cur_ime = run_adb_shell(device_id, "settings get secure default_input_method")
    if "com.android.adbkeyboard/.AdbIME" not in cur_ime:
        run_adb_shell(device_id, "ime enable com.android.adbkeyboard/.AdbIME")
        run_adb_shell(device_id, "ime set com.android.adbkeyboard/.AdbIME")
        results["ime_updated"] = True
        results["details"].append("AdbIME 기본설정")

    # 5. 화면 상시 켜짐 및 잠금 해제
    run_adb_shell(device_id, "svc power stayon true")
    run_adb_shell(device_id, "settings put system screen_off_timeout 2147483647")
    run_adb_shell(device_id, "locksettings set-disabled true")
    run_adb_shell(device_id, "cmd device_state state 3 2>/dev/null || true")
    run_adb_shell(device_id, "input keyevent 224")  # KEYCODE_WAKEUP
    run_adb_shell(device_id, "wm dismiss-keyguard")
    run_adb_shell(device_id, "su -c 'sysctl -w net.ipv6.conf.all.disable_ipv6=1 net.ipv6.conf.default.disable_ipv6=1 >/dev/null 2>&1'")
    run_adb_shell(device_id, "appops set com.genymobile.gnirehtet ACTIVATE_VPN allow 2>/dev/null; appops set com.genymobile.gnirehtet ACTIVATE_PLATFORM_VPN allow 2>/dev/null")
    results["screen_updated"] = True

    # 6. 위치(GPS) 서비스 고정확도 모드 설정
    loc_mode = run_adb_shell(device_id, "settings get secure location_mode")
    if loc_mode.strip() != "3":
        run_adb_shell(device_id, "settings put secure location_mode 3")
        run_adb_shell(device_id, "settings put secure location_providers_allowed +gps,+network")
        results["gps_mode_updated"] = True
        results["details"].append("GPS 고정확도 활성화")

    # 7. GSM / 통신사 속성 설정
    gsm_cmds = []
    for prop_k, prop_v in REQUIRED_GSM_PROPS.items():
        gsm_cmds.append(f"setprop {prop_k} {prop_v}")
    run_adb_shell(device_id, f"su -c '{'; '.join(gsm_cmds)}'")
    results["gsm_props_updated"] = len(gsm_cmds)

    # 8. 타임존 점검
    tz = run_adb_shell(device_id, "getprop persist.sys.timezone")
    if tz.strip() != "Asia/Seoul":
        run_adb_shell(device_id, "su -c 'setprop persist.sys.timezone Asia/Seoul'")
        results["timezone_updated"] = True
        results["details"].append("타임존 Asia/Seoul 설정")

    # 9. null.xml 점검 및 위치 동의/온보딩 억제 주입
    null_xml_path = f"/data/data/{pkg}/shared_prefs/null.xml"
    force_stop_app(device_id)

    # null.xml 생성 또는 갱신 스크립트 실행
    xml_sync_cmd = (
        f"su -c '"
        f"mkdir -p /data/data/{pkg}/shared_prefs; "
        f"if [ ! -f {null_xml_path} ]; then "
        f"cat << \"EOF\" > {null_xml_path}\n"
        f"<?xml version=\"1.0\" encoding=\"utf-8\" standalone=\"yes\" ?>\n"
        f"<map>\n"
        f"    <boolean name=\"keyUniverseTutorialComplete\" value=\"true\" />\n"
        f"    <boolean name=\"keyNextTutorialComplete\" value=\"true\" />\n"
        f"    <boolean name=\"keyShowNewMainTutorial\" value=\"false\" />\n"
        f"    <boolean name=\"keyDarkTutorialComplete\" value=\"true\" />\n"
        f"    <boolean name=\"keyNewmainTutorialComplete\" value=\"true\" />\n"
        f"    <boolean name=\"keyFirstRun\" value=\"false\" />\n"
        f"    <boolean name=\"keyTutorialLocProcessed\" value=\"true\" />\n"
        f"    <boolean name=\"keyLocationAgree\" value=\"true\" />\n"
        f"    <boolean name=\"keyLocationUserAgreementAccepted\" value=\"true\" />\n"
        f"</map>\n"
        f"EOF\n"
        f"else "
        f"sed -i \"s/keyLocationAgree\\\" value=\\\"false\\\"/keyLocationAgree\\\" value=\\\"true\\\"/\" {null_xml_path}; "
        f"grep -q keyLocationAgree {null_xml_path} || sed -i \"s/<\\/map>/    <boolean name=\\\"keyLocationAgree\\\" value=\\\"true\\\" \\/>\\n<\\/map>/\" {null_xml_path}; "
        f"grep -q keyLocationUserAgreementAccepted {null_xml_path} || sed -i \"s/<\\/map>/    <boolean name=\\\"keyLocationUserAgreementAccepted\\\" value=\\\"true\\\" \\/>\\n<\\/map>/\" {null_xml_path}; "
        f"grep -q keyTutorialLocProcessed {null_xml_path} || sed -i \"s/<\\/map>/    <boolean name=\\\"keyTutorialLocProcessed\\\" value=\\\"true\\\" \\/>\\n<\\/map>/\" {null_xml_path}; "
        f"grep -q keyShowNewMainTutorial {null_xml_path} && sed -i \"s/keyShowNewMainTutorial\\\" value=\\\"[^\"]*\\\"/keyShowNewMainTutorial\\\" value=\\\"false\\\"/\" {null_xml_path} || sed -i \"s/<\\/map>/    <boolean name=\\\"keyShowNewMainTutorial\\\" value=\\\"false\\\" \\/>\\n<\\/map>/\" {null_xml_path}; "
        f"grep -q keyNewmainTutorialComplete {null_xml_path} && sed -i \"s/keyNewmainTutorialComplete\\\" value=\\\"[^\"]*\\\"/keyNewmainTutorialComplete\\\" value=\\\"true\\\"/\" {null_xml_path} || sed -i \"s/<\\/map>/    <boolean name=\\\"keyNewmainTutorialComplete\\\" value=\\\"true\\\" \\/>\\n<\\/map>/\" {null_xml_path}; "
        f"grep -q keyNextTutorialComplete {null_xml_path} && sed -i \"s/keyNextTutorialComplete\\\" value=\\\"[^\"]*\\\"/keyNextTutorialComplete\\\" value=\\\"true\\\"/\" {null_xml_path} || sed -i \"s/<\\/map>/    <boolean name=\\\"keyNextTutorialComplete\\\" value=\\\"true\\\" \\/>\\n<\\/map>/\" {null_xml_path}; "
        f"grep -q keyDarkTutorialComplete {null_xml_path} && sed -i \"s/keyDarkTutorialComplete\\\" value=\\\"[^\"]*\\\"/keyDarkTutorialComplete\\\" value=\\\"true\\\"/\" {null_xml_path} || sed -i \"s/<\\/map>/    <boolean name=\\\"keyDarkTutorialComplete\\\" value=\\\"true\\\" \\/>\\n<\\/map>/\" {null_xml_path}; "
        f"fi; "
        f"APP_UID=$(stat -c %u /data/data/{pkg}); "
        f"chown -R $APP_UID:$APP_UID /data/data/{pkg}/shared_prefs; "
        f"chmod 771 /data/data/{pkg}/shared_prefs; "
        f"chmod 660 {null_xml_path}; "
        f"'"
    )
    run_adb_shell(device_id, xml_sync_cmd)
    results["null_xml_updated"] = True

    results["elapsed_sec"] = round(time.time() - t0, 2)
    return results


def run_fleet_health_check(
    device_ids: Optional[List[str]] = None,
    pkg: str = NAVER_APP_PACKAGE,
    max_workers: int = 20
) -> List[Dict[str, Any]]:
    """
    전체 투입 단말기를 대상으로 병렬 환경 무결성 진단 및 업데이트 수행 (소요시간 ~1.5초)
    """
    if not device_ids:
        from src.device.device_selector import get_online_devices
        device_ids = get_online_devices()

    if not device_ids:
        print("⚠️ [Device Baseline] 연결된 온라인 단말기가 없습니다.")
        return []

    print("=" * 95)
    print("🩺 [단말기 환경 무결성 진단 & 베이스라인 자동 동기화 (Fleet Baseline Check)]")
    print(f"   • 대상 기기 수 : {len(device_ids)}대")
    print(f"   • 점검 항목   : 위치권한(FINE/COARSE), 알림권한, AdbIME, 화면유지, 고정확도 GPS, KT 통신사, null.xml")
    print("=" * 95)

    t0_fleet = time.time()
    try:
        from src.device.ensure_frida_fleet import ensure_fleet_frida
        ensure_fleet_frida(device_ids)
    except Exception as e:
        print(f"⚠️ [Frida Baseline 점검 예외] {e}")

    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(device_ids), max_workers)) as executor:
        futures = {executor.submit(check_and_update_device, d, pkg): d for d in device_ids}
        for fut in concurrent.futures.as_completed(futures):
            dev = futures[fut]
            try:
                res = fut.result()
                results.append(res)
            except Exception as e:
                results.append({
                    "device_id": dev,
                    "status": "ERROR",
                    "details": [str(e)],
                    "permissions_updated": 0,
                    "elapsed_sec": 0.0
                })

    # 정렬하여 출력
    results.sort(key=lambda x: x["device_id"])
    total_elapsed = round(time.time() - t0_fleet, 2)

    total_perms_fixed = sum(r.get("permissions_updated", 0) for r in results)
    total_pass = sum(1 for r in results if r["status"] == "PASS")

    # 콘솔 요약 테이블 출력
    print(f"{'디바이스 ID':<16} | {'권한보정':<8} | {'GPS모드':<8} | {'AdbIME':<8} | {'null.xml':<9} | {'상태':<8} | {'소요':<6} | {'비고'}")
    print("-" * 95)
    for r in results:
        perm_str = f"🔄 +{r['permissions_updated']}" if r.get("permissions_updated", 0) > 0 else "✅ 정상"
        gps_str = "🔄 갱신" if r.get("gps_mode_updated") else "✅ 정상"
        ime_str = "🔄 설정" if r.get("ime_updated") else "✅ 정상"
        xml_str = "🔄 갱신" if r.get("null_xml_updated") else "✅ 정상"
        status_str = "✅ PASS" if r["status"] == "PASS" else "❌ FAIL"
        time_str = f"{r.get('elapsed_sec', 0.0)}s"
        note = ", ".join(r.get("details", [])) if r.get("details") else "기존 베이스라인 유지"
        print(f"{r['device_id']:<16} | {perm_str:<8} | {gps_str:<8} | {ime_str:<8} | {xml_str:<9} | {status_str:<8} | {time_str:<6} | {note}")
    print("-" * 95)
    print(f"✅ [동기화 마감] 총 {len(device_ids)}대 중 {total_pass}대 정상 통과 (권한 갱신: {total_perms_fixed}건) | 총 소요: {total_elapsed}s")
    print("=" * 95 + "\n")

    return results


if __name__ == "__main__":
    run_fleet_health_check()
