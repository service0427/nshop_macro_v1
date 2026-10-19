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
    """[최초 1회 한정] baseline 구조 생성을 위한 1회성 초기화 및 권한 설정"""
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

    # IPv6 패킷 드랍 및 5초 DNS 타임아웃 방지를 위한 커널 IPv6 비활성화 보장
    run_adb_shell(device_id, "su -c 'sysctl -w net.ipv6.conf.all.disable_ipv6=1 net.ipv6.conf.default.disable_ipv6=1 >/dev/null'")

    # 튜토리얼 팝업 방지 null.xml 주입
    clean_cmd = (
        f"su -c '"
        f"mkdir -p /data/data/{pkg}/shared_prefs; "
        f"cat << \"EOF\" > /data/data/{pkg}/shared_prefs/null.xml\n"
        f"<?xml version=\"1.0\" encoding=\"utf-8\" standalone=\"yes\" ?>\n"
        f"<map>\n"
        f"    <boolean name=\"keyUniverseTutorialComplete\" value=\"true\" />\n"
        f"    <boolean name=\"keyNextTutorialComplete\" value=\"true\" />\n"
        f"    <boolean name=\"keyShowNewMainTutorial\" value=\"false\" />\n"
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

def force_stop_app(device_id: str = DEFAULT_DEVICE_ID, max_wait: float = 2.5):
    """
    네이버 앱 관련 모든 프로세스를 강제 종료하고,
    단말기 부하/렉 상황에서도 PID가 100% 소멸할 때까지 능동 대기 (Wait for Death)
    - am force-stop을 반드시 선행 호출하여 AMS ActivityStack에서 SearchHomePage 자동 부활을 원천 차단
    """
    pkg = NAVER_APP_PACKAGE
    run_adb_shell(device_id, f"am force-stop {pkg}")
    run_adb_shell(device_id, f"su -c 'pkill -9 -f {pkg}'")

    start_wait = time.time()
    while time.time() - start_wait < max_wait:
        pids = run_adb_shell(device_id, f"su -c 'pidof {pkg}'").strip()
        if not pids:
            break
        run_adb_shell(device_id, f"su -c 'kill -9 {pids}'")
        time.sleep(0.1)

    time.sleep(0.15)


def force_stop_gms(device_id: str = DEFAULT_DEVICE_ID, max_wait: float = 2.0):
    """
    GMS(com.google.android.gms) 프로세스를 강제 종료하고 캐시 플러시 대기
    """
    pkg = "com.google.android.gms"
    run_adb_shell(device_id, f"am force-stop {pkg}")
    run_adb_shell(device_id, f"su -c 'pkill -9 -f {pkg}'")

    start_wait = time.time()
    while time.time() - start_wait < max_wait:
        pids = run_adb_shell(device_id, f"su -c 'pidof {pkg}'").strip()
        if not pids:
            break
        run_adb_shell(device_id, f"su -c 'kill -9 {pids}'")
        time.sleep(0.1)

    time.sleep(0.15)

def start_intent(device_id: str, url: str, direct_browser: bool = False):
    # direct_browser=True인 경우 또는 재시도 시 InAppBrowserActivity로 직행 (메인홈 고착 원천 방지)
    if direct_browser:
        cmd = f"su -c 'am start -n {NAVER_APP_PACKAGE}/.browser.InAppBrowserActivity -d \"{url}\" -f 0x10000000'"
    else:
        # 네이버 앱의 공인 URL 처리 Activity인 SchemeProcessActivity로 명시적 라우팅
        # SearchHomePage에 머무르지 않고 즉각 InAppBrowserActivity 웹뷰로 직행하도록 보장
        cmd = (
            f'am start -n {NAVER_APP_PACKAGE}/.ui.pages.SchemeProcessActivity '
            f'-a android.intent.action.VIEW -d "{url}" '
            f'-f 0x10000000 --es android.intent.extra.REFERRER_NAME "android-app://{NAVER_APP_PACKAGE}"'
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
        f"GMS_UID=$(stat -c %u /data/data/com.google.android.gms 2>/dev/null || echo 1000); "
        f"chown $GMS_UID:$GMS_UID /data/data/com.google.android.gms/shared_prefs/adid_settings.xml; "
        f"chmod 660 /data/data/com.google.android.gms/shared_prefs/adid_settings.xml"
        f"'"
    )
    run_adb_shell(device_id, push_cmd)

def toggle_airplane_mode(device_id: str = DEFAULT_DEVICE_ID, off_duration: float = 3.0, wait_reconnect: float = 6.0) -> bool:
    """에어플레인 모드 토글로 셀룰러 공인 IP 변경"""
    try:
        run_adb_shell(device_id, "cmd connectivity airplane-mode enable")
        time.sleep(off_duration)
        run_adb_shell(device_id, "cmd connectivity airplane-mode disable")
        time.sleep(wait_reconnect)
        return True
    except Exception:
        return False

def press_home_key(device_id: str = DEFAULT_DEVICE_ID):
    """홈 키(KEYCODE_HOME=3) 발송하여 앱을 백그라운드로 전환하고 visibilitychange / pagehide 비콘 유도"""
    run_adb_shell(device_id, "input keyevent 3")


def fast_check_native_login_or_captcha(device_id: str = DEFAULT_DEVICE_ID):
    """
    안드로이드 최상위 포커스 윈도우에서 로그인(NidLoginActivity) 또는 캡차 액티비티 즉시 검출 (50~100ms)
    Returns: (is_blocked: bool, block_type: str, reason: str)
    """
    out = run_adb_shell(device_id, "dumpsys window | grep 'mCurrentFocus=Window'")
    if any(k in out for k in ["NidLoginActivity", "nid.login", "nhn.android.search/.login"]):
        return True, "LOGIN_REQUIRED", f"네이티브 로그인 화면 포커스 감지: {out.strip()}"
    if any(k in out for k in ["CaptchaActivity", "security.challenge"]):
        return True, "CAPTCHA_BLOCKED", f"네이티브 캡차 화면 포커스 감지: {out.strip()}"
    return False, "", ""


def show_device_status_notification(device_id: str, title: str, text: str):
    """단말기 화면 상단 상태바에 현재 진행 키워드/상태 알림 표시 (cmd notification)"""
    try:
        clean_text = text.replace("'", "").replace('"', '')
        clean_title = title.replace("'", "").replace('"', '')
        cmd = f"cmd notification post -t '{clean_title}' nshop_status '{clean_text}'"
        run_adb_shell(device_id, cmd)
    except Exception:
        pass



