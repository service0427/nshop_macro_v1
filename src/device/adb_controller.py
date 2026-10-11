#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/device/adb_controller.py

단말기 ADB 저수준 제어 모듈
- pm clear 및 튜토리얼 스킵 주입
- 권한 및 AdbIME 설정
- 스크린샷 캡처 및 최상단 액티비티 판독
"""

import os
import time
import subprocess
from pathlib import Path
from typing import Optional

from config.settings import NAVER_APP_PACKAGE, DEFAULT_DEVICE_ID

def run_adb_shell(device_id: str, cmd: str, timeout: int = 15) -> str:
    try:
        res = subprocess.run(
            ["adb", "-s", device_id, "shell", cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return res.stdout.strip()
    except Exception:
        return ""

def reset_pm_clear(device_id: str = DEFAULT_DEVICE_ID):
    """1회용 완전 클린 pm clear 및 튜토리얼 스킵 설정 주입"""
    pkg = NAVER_APP_PACKAGE
    run_adb_shell(device_id, f"pm clear {pkg}")
    time.sleep(0.4)

    # 필수 런타임 권한 승인
    for perm in [
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.ACCESS_COARSE_LOCATION"
    ]:
        run_adb_shell(device_id, f"pm grant {pkg} {perm} 2>/dev/null")

    run_adb_shell(device_id, f"cmd appops set {pkg} POST_NOTIFICATION allow")
    run_adb_shell(device_id, "ime set com.android.adbkeyboard/.AdbIME")

    # 튜토리얼 팝업 방지 null.xml 주입
    clean_cmd = (
        f"su -c '"
        f"mkdir -p /data/data/{pkg}/shared_prefs; "
        f"cat << \"EOF\" > /data/data/{pkg}/shared_prefs/null.xml\n"
        f"<?xml version=\"1.0\" encoding=\"utf-8\" standalone=\"yes\" ?>\n"
        f"<map>\n"
        f"    <boolean name=\"keyUniverseTutorialComplete\" value=\"true\" />\n"
        f"    <boolean name=\"keyNextTutorialComplete\" value=\"true\" />\n"
        f"    <boolean name=\"keyShowNewMainTutorial\" value=\"true\" />\n"
        f"    <boolean name=\"keyDarkTutorialComplete\" value=\"true\" />\n"
        f"    <boolean name=\"keyNewmainTutorialComplete\" value=\"true\" />\n"
        f"    <boolean name=\"keyFirstRun\" value=\"false\" />\n"
        f"    <boolean name=\"keyTutorialLocProcessed\" value=\"true\" />\n"
        f"</map>\n"
        f"EOF\n"
        f"APP_UID=$(stat -c %u /data/data/{pkg}); "
        f"chown -R $APP_UID:$APP_UID /data/data/{pkg}/shared_prefs; "
        f"chmod 771 /data/data/{pkg}/shared_prefs; "
        f"chmod 660 /data/data/{pkg}/shared_prefs/null.xml; "
        f"'"
    )
    run_adb_shell(device_id, clean_cmd)
    time.sleep(0.2)

def force_stop_app(device_id: str = DEFAULT_DEVICE_ID):
    run_adb_shell(device_id, f"am force-stop {NAVER_APP_PACKAGE}")
    run_adb_shell(device_id, f"su -c 'pkill -9 -f {NAVER_APP_PACKAGE}'")
    time.sleep(0.3)

def start_intent(device_id: str, url: str):
    cmd = (
        f'am start -a android.intent.action.VIEW -d "{url}" -p {NAVER_APP_PACKAGE} '
        f'-f 0x14000000 --es android.intent.extra.REFERRER_NAME "android-app://{NAVER_APP_PACKAGE}"'
    )
    run_adb_shell(device_id, cmd)


def get_top_resumed_activity(device_id: str = DEFAULT_DEVICE_ID) -> str:
    return run_adb_shell(device_id, "dumpsys activity activities | grep topResumedActivity")

def take_screenshot(device_id: str, target_path: Path) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "wb") as f:
        subprocess.run(["adb", "-s", device_id, "exec-out", "screencap", "-p"], stdout=f)
    return target_path

def update_gms_adid(device_id: str, adid: str):
    """GMS Core의 adid_settings.xml을 새 ADID/da-dd로 갱신"""
    payload = (
        f"<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\\n"
        f"<map>\\n"
        f"    <string name=\\\"adid_key\\\">{adid}</string>\\n"
        f"    <boolean name=\\\"enable_limit_ad_tracking\\\" value=\\\"false\\\" />\\n"
        f"</map>"
    )
    push_cmd = (
        f"su -c '"
        f"mkdir -p /data/data/com.google.android.gms/shared_prefs; "
        f"printf \"{payload}\" > /data/data/com.google.android.gms/shared_prefs/adid_settings.xml; "
        f"chmod 660 /data/data/com.google.android.gms/shared_prefs/adid_settings.xml"
        f"'"
    )
    run_adb_shell(device_id, push_cmd)

