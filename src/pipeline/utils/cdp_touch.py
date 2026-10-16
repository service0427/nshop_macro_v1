#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/pipeline/utils/cdp_touch.py

Clean, pinpoint CDP touch dispatcher with human-like timing and visual crosshair capture.

📌 [절대 철칙 9: 자바스크립트 el.click() 영구 금지 & 100% CDP Real Touch 필수]
- 좌표는 CDP getBoundingClientRect()로 정밀 실측하되, 클릭은 무조건 CDP Input.dispatchTouchEvent로만 발송!
- JavaScript el.click() 사용 절대 금지: 터치 이벤트(Pointer/Touch) 및 FDS 필수 텔레메트리/비콘 패킷(WTM, nlog)이
  통째로 누락되어 네이버 FDS에 비정상 매크로로 즉시 탐지(로그인 팝업/캡차 유발/유효타 무효화)됨.
"""

import time
import random
import asyncio
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Union
import logging

from config.settings import CAPTURES_DIR, TIMINGS
from src.browser.cdp_client import AsyncCDPClient

logger = logging.getLogger("ConveyorExecutor")


def save_stage_screenshot(device_id: str, stage_name: str, task_id: Any, output_dir: Optional[Union[str, Path]] = None) -> str:
    try:
        cap_dir = Path(output_dir) if output_dir else CAPTURES_DIR
        cap_dir.mkdir(parents=True, exist_ok=True)
        timestamp_str = time.strftime('%Y%m%d_%H%M%S')
        filename = f"{stage_name}_{device_id}_task{task_id}_{timestamp_str}.png"
        shot_path = cap_dir / filename
        cmd = f"adb -s {device_id} exec-out screencap -p > {shot_path}"
        subprocess.run(cmd, shell=True, check=True, timeout=TIMINGS.SCREENSHOT_EXEC_TIMEOUT)
        logger.info(f"📸 [{stage_name} 단계 캡처 완료] {filename}")
        return str(shot_path)
    except Exception as e:
        logger.warning(f"⚠️ [{stage_name} 단계 캡처 실패] {e}")
        return ""


async def cdp_real_touch(
    cdp: AsyncCDPClient,
    device_id: str,
    task_id: Union[str, int],
    action_name: str,
    click_x: float,
    click_y: float,
    target_selector_expr: Optional[str] = None,
    output_dir: Optional[Union[str, Path]] = None,
    capture_screenshot: bool = True,
    use_jitter: bool = True
) -> Dict[str, Any]:
    """
    Dispatches a human-like pinpoint touch event via CDP:
    1. Injects visual crosshair overlay at (click_x, click_y)
    2. Takes physical screencap for verification (before_click)
    3. Human cognition & eye-focus dwell delay (0.50 ~ 0.65s)
    4. CDP Input.dispatchTouchEvent (touchStart -> hold 75~110ms -> touchEnd)
    5. Cleans up overlay
    """
    shot_path_str: Optional[str] = None
    target_cap_dir = Path(output_dir) if output_dir else CAPTURES_DIR
    target_cap_dir.mkdir(parents=True, exist_ok=True)
    timestamp_str = time.strftime("%Y%m%d_%H%M%S")

    # [Hard Shield] Search header protection
    if click_y < 68.0 or click_x < 10.0:
        logger.critical(f"🚨 [터치 발송 차단] 이상 좌표 감지: click_x={click_x:.1f}, click_y={click_y:.1f}")
        return {
            "action": action_name,
            "x": click_x,
            "y": click_y,
            "success": False,
            "blocked": True,
            "reason": "INVALID_COORDINATES",
            "capture_path": None
        }

    # 1. Clean Physical Screenshot (Zero DOM Mutation, Zero MutationObserver trace)
    if capture_screenshot:
        shot_filename = f"click_{device_id}_task{task_id}_{action_name}_{timestamp_str}.png"
        shot_path = target_cap_dir / shot_filename
        try:
            cmd = f"adb -s {device_id} exec-out screencap -p > {shot_path}"
            subprocess.run(cmd, shell=True, check=True, timeout=8.0)
            shot_path_str = str(shot_path)
            logger.info(f"📸 [클릭 직전 캡쳐 완료] {shot_filename} | 조준 좌표: ({click_x:.1f}, {click_y:.1f})")

            before_click_filename = f"before_click_{device_id}_task{task_id}_{timestamp_str}.png"
            before_click_path = target_cap_dir / before_click_filename
            try:
                import shutil
                shutil.copy2(str(shot_path), str(before_click_path))
            except Exception:
                pass

            # [FDS 돌파 핵심] 웹뷰 DOM 변조 없이 순수 이미지 위에 오프라인 조준경 합성 (PIL Offline Drawing)
            try:
                from PIL import Image, ImageDraw
                for target_img_path in [shot_path, before_click_path]:
                    if target_img_path.exists():
                        with Image.open(target_img_path) as img:
                            img = img.convert("RGBA")
                            # DPR (기기 디스플레이 해상도 대비 웹뷰 뷰포트 비율: 가로 기준)
                            scale = img.width / 360.0
                            # 안드로이드 시스템 상태바(StatusBar) 높이 보정 (1080x2640 기준 94px, CSS 31.3px)
                            # 웹뷰는 상태바 아래에서 렌더링되므로 screencap 오프라인 드로잉 시 상태바 높이 오프셋 가산
                            statusbar_offset = round(31.33 * scale) if img.height > 2000 else 0
                            px = click_x * scale
                            py = (click_y * scale) + statusbar_offset
                            r = 16.0 * scale

                            overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
                            draw = ImageDraw.Draw(overlay)
                            # 핑크색 원형 조준경
                            draw.ellipse([px - r, py - r, px + r, py + r], fill=(255, 0, 85, 90), outline=(255, 0, 85, 255), width=max(2, int(2 * scale)))
                            # 십자선
                            line_len = 10.0 * scale
                            line_w = max(2, int(2 * scale))
                            draw.line([px - line_len, py, px + line_len, py], fill=(255, 255, 255, 240), width=line_w)
                            draw.line([px, py - line_len, px, py + line_len], fill=(255, 255, 255, 240), width=line_w)
                            # 노란색 중앙점
                            dot_r = 3.0 * scale
                            draw.ellipse([px - dot_r, py - dot_r, px + dot_r, py + dot_r], fill=(255, 255, 0, 255))

                            composite = Image.alpha_composite(img, overlay)
                            composite.convert("RGB").save(target_img_path, "PNG")
            except Exception as e:
                logger.warning(f"⚠️ [오프라인 조준경 드로잉 경고] {e}")

        except Exception as e:
            logger.warning(f"⚠️ [화면 캡쳐 예외] {e}")

    # 2. Human perception dwell delay
    pre_touch_delay = random.uniform(TIMINGS.TOUCH_PRE_DELAY_MIN, TIMINGS.TOUCH_PRE_DELAY_MAX)
    logger.info(f"👀 [리얼 터치 직전 인지 지연] {pre_touch_delay:.2f}초 체류 후 물리 터치 발송")
    await asyncio.sleep(pre_touch_delay)

    # 3. CDP Pinpoint Touch Event with Human Micro-Jitter (손가락 미세 떨림 & 압력 곡선)
    rad_x = round(random.uniform(18.0, 24.5), 1)
    rad_y = round(random.uniform(22.0, 30.5), 1)
    touch_force = round(random.uniform(0.85, 0.95), 2)
    hold_ms = random.uniform(TIMINGS.TOUCH_HOLD_MS_MIN, TIMINGS.TOUCH_HOLD_MS_MAX)
    jx1, jy1, jx2, jy2 = None, None, None, None
    logger.info(f"👉 [{action_name} CDP 탭 발송] 좌표: ({click_x:.1f}, {click_y:.1f}) | 지터: {use_jitter} | 누름: {hold_ms*1000:.1f}ms | 압력: {touch_force}")

    try:
        # Step A: touchStart (디스플레이 최초 접촉)
        await cdp.call("Input.dispatchTouchEvent", {
            "type": "touchStart",
            "touchPoints": [{"x": click_x, "y": click_y, "radiusX": rad_x, "radiusY": rad_y, "force": touch_force}]
        })

        if use_jitter:
            # Step B: touchMove 1 (인간 지문 가압 및 0.5~1.2px 미세 지터 1)
            jitter_t1 = hold_ms * random.uniform(0.35, 0.45)
            await asyncio.sleep(jitter_t1)
            jx1 = round(click_x + random.uniform(-0.8, 0.8), 1)
            jy1 = round(click_y + random.uniform(-0.8, 0.8), 1)
            jf1 = min(1.0, round(touch_force + random.uniform(0.04, 0.08), 2))
            await cdp.call("Input.dispatchTouchEvent", {
                "type": "touchMove",
                "touchPoints": [{"x": jx1, "y": jy1, "radiusX": rad_x + 0.4, "radiusY": rad_y + 0.4, "force": jf1}]
            })

            # Step C: touchMove 2 (접촉 유지 및 미세 떨림 2)
            jitter_t2 = hold_ms - jitter_t1
            await asyncio.sleep(jitter_t2)
            jx2 = round(jx1 + random.uniform(-0.5, 0.5), 1)
            jy2 = round(jy1 + random.uniform(-0.5, 0.5), 1)
            jf2 = round(jf1 - random.uniform(0.03, 0.06), 2)
            await cdp.call("Input.dispatchTouchEvent", {
                "type": "touchMove",
                "touchPoints": [{"x": jx2, "y": jy2, "radiusX": rad_x, "radiusY": rad_y, "force": jf2}]
            })
        else:
            # [사용자 엄명: 쇼핑 더보기 시 지터 완전 배제]
            # 터치무브 없이 순수 탭 유지 시간만 거친 후 즉시 touchEnd (스크롤 오인식 원천 방지)
            await asyncio.sleep(hold_ms)

        # Step D: touchEnd (손가락 떼기)
        await cdp.call("Input.dispatchTouchEvent", {
            "type": "touchEnd",
            "touchPoints": []
        })
    except Exception as e:
        logger.warning(f"⚠️ [CDP 터치 발송 예외] {type(e).__name__}: {e}")

    return {
        "action": action_name,
        "x": click_x,
        "y": click_y,
        "success": True,
        "blocked": False,
        "capture_path": shot_path_str,
        "use_jitter": use_jitter,
        "hold_ms": round(hold_ms * 1000, 1),
        "pre_touch_delay": round(pre_touch_delay, 3),
        "touch_force": touch_force,
        "jitter_points": {"p1": [jx1, jy1], "p2": [jx2, jy2]} if use_jitter else None
    }
