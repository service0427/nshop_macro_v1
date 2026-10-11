#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/browser/frida_runner.py

Frida 앱 스폰 및 Chromium DevTools 원격 디버깅 활성화 모듈
- 0초 인프로세스 SSAID 동적 가로채기 주입 지원
- DevTools 추상 소켓 CDP 포트 포워딩
"""

import time
import subprocess
from typing import Tuple, Any, Optional
from pathlib import Path
import frida

from config.settings import (
    NAVER_APP_PACKAGE,
    DEFAULT_DEVICE_ID,
    DEFAULT_CDP_PORT,
    FRIDA_AGENT_PATH
)

from src.browser.hooks import build_hook_bundle

import secrets

def spawn_app_with_cdp(
    device_id: str = DEFAULT_DEVICE_ID,
    cdp_port: int = DEFAULT_CDP_PORT,
    spoof_ssaid: Optional[str] = None,
    spoof_google_account: Optional[str] = None,
    spoof_dadd: Optional[str] = None,
    spoof_dadv: Optional[str] = None,
    spoof_network_type: Optional[str] = "cellular",
    spoof_mcc_mnc: Optional[str] = "450_08",
    spoof_lat: Optional[float] = 37.4979,
    spoof_lng: Optional[float] = 127.0276,
    spoof_acc: Optional[float] = 5.0,
    spoof_alt: Optional[float] = 35.0,
    spoof_bearing: Optional[float] = 0.0,
    fake_install_time: Optional[int] = None,
    fake_update_time: Optional[int] = None,
    fake_boot_time: Optional[int] = None,
    target_nnb: Optional[str] = None
) -> Tuple[int, Any]:
    """
    네이버 앱을 Frida로 스폰하고 cdp_clean_agent.js를 로드하여
    DevTools 추상 소켓을 cdp_port로 포워딩.
    spoof_ssaid: android_id 실시간 가로채기 주입
    spoof_google_account: 가상 구글 계정 (AccountManager) 상시 로그인 주입
    spoof_dadd: Google ADID (AdvertisingIdClient$Info.a / DA_DD) 실시간 가로채기 주입
    spoof_dadv: Google AppSetId (AppSetIdInfo / DA_DV / Scope 1) 실시간 가로채기 주입
    spoof_network_type: cellular / wifi / cellular111 등 가상 네트워크망 주입
    spoof_mcc_mnc: 통신사 MCC/MNC (450_08, 4555555 등) 가상 주입
    spoof_lat, spoof_lng: GPS 위치(위도, 경도) 최심부 주입 -> m_loc 쿠키 자동 생성
    fake_install_time, fake_update_time, fake_boot_time: 기기 설치/부팅 라이프사이클 위조
    """
    from src.core.profile_generator import generate_realistic_google_account

    with open(FRIDA_AGENT_PATH, "rb") as f:
        raw = f.read()

    parts = raw.split(b"\xe2\x9c\x84")
    js_code = parts[1].decode("utf-8")

    # 가상 구글 계정이 미지정되었으나 ADID/AppSetId를 주입하는 경우 1회용 신생 계정 자동 발급
    if not spoof_google_account and (spoof_dadd or spoof_dadv):
        spoof_google_account = generate_realistic_google_account()

    # 모듈화된 Core Root 훅 번들 생성
    hook_code = build_hook_bundle(
        spoof_ssaid=spoof_ssaid,
        spoof_google_account=spoof_google_account,
        spoof_dadd=spoof_dadd,
        spoof_dadv=spoof_dadv,
        spoof_network_type=spoof_network_type,
        spoof_mcc_mnc=spoof_mcc_mnc,
        spoof_lat=spoof_lat,
        spoof_lng=spoof_lng,
        spoof_acc=spoof_acc,
        spoof_alt=spoof_alt,
        spoof_bearing=spoof_bearing,
        fake_install_time=fake_install_time,
        fake_update_time=fake_update_time,
        fake_boot_time=fake_boot_time,
        target_nnb=target_nnb
    )


    anchor = 'frida_java_bridge_default.perform(() => {'
    final_js = js_code.replace(anchor, anchor + "\n" + hook_code)

    device = frida.get_device(device_id)
    pid = device.spawn([NAVER_APP_PACKAGE])
    session = device.attach(pid)
    script = session.create_script(final_js)

    def on_frida_message(message, data):
        if message.get("type") == "send":
            print(f"  [Frida] {message.get('payload')}")
        elif message.get("type") == "error":
            print(f"  [Frida Error] {message.get('description')}")
    script.on("message", on_frida_message)

    script.load()
    device.resume(pid)

    time.sleep(1.0)
    target_socket = f"localabstract:xwhale_devtools_remote_{pid}"
    subprocess.run(["adb", "-s", device_id, "forward", f"tcp:{cdp_port}", target_socket], check=True)

    return pid, session
