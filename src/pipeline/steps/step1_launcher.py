#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/pipeline/steps/step1_launcher.py

Step 1: Clean App Launcher & Frida Hooking
- Executes surgical clean reset (cache-preserving static assets + selective session wipe)
- Spawns Naver search app with Frida hooks and DevTools forced ON
- Fires Intent to search query via ackey-based URL: https://m.search.naver.com/search.naver?sm={sm}&where=m&query={keyword}&ackey={ackey}...
- Establishes WebSocket CDP connection and synchronizes NNB/BUC cookies
"""

import time
import asyncio
import logging
import websockets
from typing import Tuple, Dict, Any, Optional

from config.settings import TIMINGS
from src.device.adb_controller import start_intent, force_stop_app
from src.device.surgical_cleaner import perform_surgical_cycle
from src.browser.frida_runner import spawn_app_with_cdp
from src.browser.cdp_client import AsyncCDPClient, find_serp_debugger_url
from src.core.profile_generator import build_intent_url, build_shopping_intent_url
from src.pipeline.models import TaskInput, TaskResult

logger = logging.getLogger("ConveyorExecutor")


async def launch_app_and_connect_cdp(
    task: TaskInput,
    device_id: str,
    cdp_port: int,
    nnb: str,
    buc: str,
    profile: Dict[str, Any],
    traffic_logger: Optional[Any] = None,
    result: Optional[TaskResult] = None
) -> Tuple[Optional[AsyncCDPClient], Optional[websockets.WebSocketClientProtocol], Optional[str]]:
    """
    Initializes clean session and returns (cdp_client, ws_connection, error_message).
    """
    t0_start = time.time()

    # 1. 캐시 보존형 외과수술식 정밀 세정 (Surgical Cycle: 정적 캐시 100% 보존 + 쿠키/식별자 핀셋 리셋)
    logger.info(f"🧹 [{device_id}] 캐시 보존형 외과수술식 정밀 세정(Surgical Clean) 실행...")
    try:
        perform_surgical_cycle(
            device_id=device_id,
            aged_nnb=nnb,
            aged_buc=buc,
            fresh_ssaid=profile["ssaid"],
            fresh_dadd=profile["dadd"],
            fresh_dadv=profile["dadv"],
            fresh_lat=profile["lat"],
            fresh_lng=profile["lng"],
            cdp_port=cdp_port
        )
    except Exception as e:
        logger.error(f"❌ [{device_id}] Surgical Clean 실패: {e}")
        return None, None, f"SURGICAL_CLEAN_FAILED: {e}"

    # 2. Frida Hook & DevTools ON
    def _on_frida_msg(payload):
        if not isinstance(payload, dict):
            return
        p_type = payload.get("type")
        if p_type == "login_intercept":
            action = payload.get("action", "UNKNOWN")
            detail = f"[{action}] {payload.get('source', '')} | {payload.get('component') or payload.get('client') or ''} -> {payload.get('url') or payload.get('uri') or payload.get('target') or ''}".strip()
            if result:
                result.login_detected = True
                result.login_handling_type = "LOGIN_CHALLENGE_DETECTED"
                result.login_intercept_count += 1
                result.login_intercept_details.append(detail)
            if traffic_logger:
                traffic_logger.record_event("LOGIN_INTERCEPT", detail, payload)
            logger.warning(f"🚨 [{device_id}] [네이버 FDS 로그인 챌린지 감지] {detail}")
        elif p_type == "native_telemetry" and traffic_logger:
            u = payload.get("url", "")
            m = payload.get("method", "POST")
            traffic_logger.record_event(
                "NATIVE_TELEMETRY",
                f"[{m}] {u[:110]}",
                {"url": u, "method": m, "source": "Native App"}
            )

    try:
        spawn_app_with_cdp(
            device_id, cdp_port,
            spoof_ssaid=profile["ssaid"],
            spoof_google_account=profile["google_account"],
            spoof_dadd=profile["dadd"],
            spoof_dadv=profile["dadv"],
            spoof_lat=profile["lat"],
            spoof_lng=profile["lng"],
            target_nnb=nnb,
            on_message_callback=_on_frida_msg,
            clean_mode=True
        )
    except Exception as e:
        logger.error(f"❌ [{device_id}] Frida Spawning 실패: {e}")
        return None, None, f"FRIDA_SPAWN_FAILED: {e}"

    # 3. Intent 실행 및 SERP 탭 연결
    target_intent_url = build_intent_url(task.keyword)
    serp_ws = None
    for attempt in range(TIMINGS.LAUNCH_MAX_ATTEMPTS):
        if attempt > 0:
            await asyncio.sleep(0.5)
            # 2차 이상 재시도 시 메인홈 고착 회피를 위해 InAppBrowserActivity로 직행
            start_intent(device_id, target_intent_url, direct_browser=True)
        else:
            start_intent(device_id, target_intent_url, direct_browser=False)

        if traffic_logger:
            traffic_logger.record_event("INTENT_LAUNCH", f"Launch Naver App (attempt {attempt+1}): {target_intent_url}", {"attempt": attempt+1})
        serp_ws = await find_serp_debugger_url(cdp_port, timeout=8.0 if attempt < TIMINGS.LAUNCH_MAX_ATTEMPTS - 1 else 15.0)
        if serp_ws:
            logger.info(f"🔗 [통합검색 탭 연결 성공 (시도 {attempt+1}/{TIMINGS.LAUNCH_MAX_ATTEMPTS})] {serp_ws}")
            break
        logger.warning(f"⚠️ SERP 탭 미발견 (시도 {attempt+1}/{TIMINGS.LAUNCH_MAX_ATTEMPTS}) -> InAppBrowser 직행 재시도...")

    if not serp_ws:
        return None, None, "SERP_TAB_NOT_FOUND"

    # 4. WebSocket 연결
    ws_conn = None
    for attempt in range(TIMINGS.LAUNCH_MAX_ATTEMPTS):
        try:
            ws_conn = await websockets.connect(serp_ws, ping_interval=None, open_timeout=TIMINGS.LAUNCH_WS_CONNECT_TIMEOUT)
            break
        except Exception as e:
            if attempt < TIMINGS.LAUNCH_MAX_ATTEMPTS - 1:
                await asyncio.sleep(0.3)
    if not ws_conn:
        return None, None, "WS_CONNECT_FAILED"

    cdp = AsyncCDPClient(ws_conn)
    cdp.ws_url = serp_ws
    try:
        await cdp.call("Network.enable")
        # [데이터 다이어트] 1KB lcs/wcs 이미지 비콘 및 모든 정규 이미지는 100% 정상 허용하되,
        # 수십 MB를 잠식하는 동영상/라이브 미디어 스트리밍만 선별 차단
        await cdp.call("Network.setBlockedURLs", {
            "urls": [
                "*.mp4*", "*.m3u8*", "*.webm*", "*.ts*",
                "*vod.pstatic.net*", "*naver-live*", "*shoppinglive*"
            ]
        })
    except Exception:
        pass

    # 5. [초반 2단계: In-flight Gate] NNB/BUC/NAPP_DI/DA_DD/DA_DV/m_loc 메모리 캐시 동기화 및 실측 쐐기
    from src.device.cookie_rollback_manager import CookieRollbackManager
    await CookieRollbackManager.in_flight_gate(cdp, profile, nnb=nnb, buc=buc)

    logger.info(f"⚡ [Step 1 완료] 네이버 앱 정상 기동 및 통합검색 연결 완료 (소요: {time.time() - t0_start:.2f}s)")
    return cdp, ws_conn, None
