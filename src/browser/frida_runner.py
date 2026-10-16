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

_CACHED_AGENT_JS: Optional[str] = None

def _get_agent_template() -> str:
    global _CACHED_AGENT_JS
    if _CACHED_AGENT_JS is None:
        with open(FRIDA_AGENT_PATH, "rb") as f:
            raw = f.read()
        parts = raw.split(b"\xe2\x9c\x84")
        if len(parts) > 1:
            _CACHED_AGENT_JS = parts[1].decode("utf-8")
        else:
            _CACHED_AGENT_JS = parts[0].decode("utf-8")
    return _CACHED_AGENT_JS

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
    target_nnb: Optional[str] = None,
    on_message_callback: Optional[Any] = None,
    clean_mode: bool = True
) -> Tuple[int, Any]:
    """
    네이버 앱을 Frida로 스폰하고 cdp_clean_agent.js를 로드하여
    DevTools 추상 소켓을 cdp_port로 포워딩.
    clean_mode: True일 경우 WTM 무결성 필터 회피를 위해 일체의 OS/네트워크 인위적 변조 훅을 배제하고
                순수 100% 클린 DevTools 원격 디버깅 활성화 코드만 단독 주입.
    """
    from src.core.profile_generator import generate_realistic_google_account

    js_code = _get_agent_template()

    if clean_mode:
        # 순수 식별자 & 통신사 무결성 모드:
        # WTM/C++ 소켓 불일치를 유발하는 위험 훅(Inet4Address, NetworkCapabilities, Runtime.exec)은 배제하고,
        # 실사용자 인증의 핵심인 SSAID, 구글 계정, ADID(da-dd), AppSetId(da-dv), KT LTE(450_08), GPS 위치 정보는 100% 완전 주입!
        from src.browser.hooks.identity_hook import build_identity_hook
        from src.browser.hooks.google_identity_hook import build_google_identity_hook
        from src.browser.hooks.network_hook import build_network_hook
        from src.browser.hooks.location_hook import build_location_hook
        from src.browser.hooks.login_tracer_hook import build_login_tracer_hook

        if not spoof_google_account and (spoof_dadd or spoof_dadv):
            spoof_google_account = generate_realistic_google_account()

        hooks = []
        if spoof_ssaid:
            hooks.append(build_identity_hook(spoof_ssaid))
        if spoof_google_account or spoof_dadd or spoof_dadv:
            hooks.append(build_google_identity_hook(
                spoof_google_account=spoof_google_account,
                spoof_dadd=spoof_dadd,
                spoof_dadv=spoof_dadv
            ))
        if spoof_mcc_mnc:
            # NetworkCapabilities 조작 없이 순수 TelephonyManager(450_08, KT LTE)만 주입
            hooks.append(build_network_hook(spoof_network_type=None, spoof_mcc_mnc=spoof_mcc_mnc))
        if spoof_lat and spoof_lng:
            # 하드웨어 GPS 및 GMS FusedLocation 최심부 좌표 주입 (모의위치 차단)
            hooks.append(build_location_hook(
                latitude=spoof_lat,
                longitude=spoof_lng,
                accuracy=spoof_acc or 5.0,
                altitude=spoof_alt or 35.0,
                bearing=spoof_bearing or 0.0
            ))
        # [안티-로그인 쉴드] 네이티브 NidLoginActivity 팝업 원천 차단 및 타겟 자동 복구
        hooks.append(build_login_tracer_hook(target_nnb=target_nnb or ""))

        if hooks:
            anchor = 'frida_java_bridge_default.perform(() => {'
            final_js = js_code.replace(anchor, anchor + "\n" + "\n".join(hooks))
        else:
            final_js = js_code
    else:
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

    # =========================================================================
    # [Pre-flight Gate] 6대 핵심 식별자/통신사/위치 훅 무결성 실시간 감시 엔진
    # =========================================================================
    MANDATORY_HOOKS = {
        "Settings.Secure",      # 1. SSAID (android_id -> NAPP_DI MD5 연동)
        "AccountManager",       # 2. 실사용자 가상 구글 계정 상시 로그인
        "AppSetIdInfo",         # 3. GMS AppSetId UUID 및 Scope 1 (SCOPE_DEVELOPER) 승격
        "AdvertisingIdClient",  # 4. GMS ADID UUID 및 광고 추적 허용 (LAT: false)
        "TelephonyManager",     # 5. KT LTE 450_08 정상 개통 및 SIM READY
        "LocationManager"       # 6. 하드웨어 GPS 최심부 좌표 주입 및 모의위치 차단 (isMock=false)
    }
    verified_hooks = set()
    hook_errors = {}

    def on_frida_message(message, data):
        if message.get("type") == "send":
            payload = message.get("payload")
            if on_message_callback:
                try:
                    on_message_callback(payload)
                except Exception:
                    pass
            if isinstance(payload, dict):
                p_type = payload.get("type")
                if p_type == "hook_verification":
                    h_name = payload.get("hook")
                    h_status = payload.get("status")
                    if h_status == "OK":
                        verified_hooks.add(h_name)
                    else:
                        hook_errors[h_name] = payload.get("error")
                    return
                elif p_type == "native_telemetry":
                    print(f"  📡 [Native Telemetry] {payload.get('method')} {payload.get('url')}")
                    return
            print(f"  [Frida] {payload}")
        elif message.get("type") == "error":
            print(f"  [Frida Error] {message.get('description')}")
    script.on("message", on_frida_message)

    script.load()
    device.resume(pid)

    # 5대 훅 발화 및 검증 대기 (최대 1.5초)
    t_deadline = time.time() + 1.5
    while time.time() < t_deadline:
        if len(verified_hooks & MANDATORY_HOOKS) == len(MANDATORY_HOOKS):
            break
        time.sleep(0.05)

    missing = MANDATORY_HOOKS - verified_hooks
    if missing or hook_errors:
        from src.device.adb_controller import force_stop_app
        force_stop_app(device_id)
        err_msg = f"필수 5대 식별자/통신사 훅 누락: {missing}" if missing else f"훅 런타임 오류: {hook_errors}"
        raise RuntimeError(f"🚨 [Frida Pre-flight 감시 실패] {err_msg} -> 보안 누출 방지를 위해 즉시 중단")

    time.sleep(0.3)
    target_socket = f"localabstract:xwhale_devtools_remote_{pid}"
    subprocess.run(["adb", "-s", device_id, "forward", f"tcp:{cdp_port}", target_socket], check=True)

    return pid, session
