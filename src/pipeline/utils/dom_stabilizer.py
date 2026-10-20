# ==============================================================================
# src/pipeline/utils/dom_stabilizer.py
#
# [DOM 엘리먼트 정착 및 물리 터치 조준 검증기]
# - 1:N 동시 구동 시 발생하는 동적 레이아웃 시프트(Layout Shift / CLS) 완충
# - 블랙리스트(블로그/카페/사전 등) 방식 전면 배제
# - 오직 1) 타겟 본인 일치(isSelf) 및 2) 상하/크기 변위 멈춤(Delta <= tolerance)만으로 판정
# ==============================================================================

import time
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, Union
from src.browser.cdp_client import AsyncCDPClient

logger = logging.getLogger("DOMStabilizer")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
DOM_STABILIZATION_LOG_FILE = LOGS_DIR / "dom_stabilization.jsonl"


def _record_stabilization_log(record: Dict[str, Any]):
    """DOM 레이아웃 안정화 전용 감사 로그에 전수 기록"""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(DOM_STABILIZATION_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"Failed to record dom stabilization log: {e}")


async def wait_for_element_settled(
    cdp: AsyncCDPClient,
    target_selector_expr: str,
    max_retries: int = 3,
    interval_sec: float = 1.0,
    tolerance_px: float = 0.0,
    action_label: str = "TARGET",
    device_id: Optional[str] = None,
    task_id: Optional[Union[int, str]] = None,
    keyword: Optional[str] = None,
    nv_mid: Optional[str] = None,
    store_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    [순수 지오메트리 & 타겟 본인 일치 기반 정착 대기]
    - target_selector_expr: document.querySelector로 조회할 타겟 셀렉터
    - max_retries: 재시도 횟수 (기본 3회)
    - interval_sec: 점검 간격 (기본 1.0초)
    - tolerance_px: 허용 변위 (기본 0.0px: 1px의 흔들림도 불허하는 100% 완전 일치/정지 원칙)
    """
    check_js = f"""
    (() => {{
        const el = document.querySelector('{target_selector_expr}');
        if (!el) return {{ valid: false, error: "ELEMENT_NOT_FOUND" }};
        
        const r = el.getBoundingClientRect();
        if (r.width < 10 || r.height < 10) {{
            return {{ valid: false, error: "ELEMENT_ZERO_SIZE", width: r.width, height: r.height }};
        }}

        const winW = window.innerWidth || 360;
        const winH = window.innerHeight || 800;

        // 뷰포트 내 안전 중심점
        const cx = Math.max(10.0, Math.min(r.left + r.width / 2, winW - 10.0));
        const cy = Math.max(10.0, Math.min(r.top + r.height / 2, winH - 10.0));
        
        // 해당 좌표 상의 최상위 엘리먼트 추출
        const hitEl = document.elementFromPoint(cx, cy);
        
        // [단일 진실 판정] 조준 좌표의 엘리먼트가 타겟 본인 또는 그 자식 요소인가?
        const isSelf = !!(hitEl && (hitEl === el || el.contains(hitEl)));

        return {{
            valid: true,
            top: Math.round(r.top * 10) / 10,
            bottom: Math.round(r.bottom * 10) / 10,
            left: Math.round(r.left * 10) / 10,
            right: Math.round(r.right * 10) / 10,
            width: Math.round(r.width * 10) / 10,
            height: Math.round(r.height * 10) / 10,
            cx: Math.round(cx * 10) / 10,
            cy: Math.round(cy * 10) / 10,
            isSelf: isSelf,
            hitTag: hitEl ? hitEl.tagName : null,
            hitClass: hitEl ? (hitEl.className || '').slice(0, 40) : null,
            href: el.href || el.getAttribute('href') || ''
        }};
    }})()
    """

    t_start = time.time()
    attempts_detail = []

    # 1. 최초 위치 측정 (초기 상태 파악)
    prev = await cdp.evaluate(check_js)
    if not prev or not isinstance(prev, dict) or not prev.get("valid"):
        err = prev.get("error", "NOT_FOUND") if isinstance(prev, dict) else "CDP_FAIL"
        _record_stabilization_log({
            "timestamp": datetime.now().isoformat(),
            "time_epoch": round(time.time(), 3),
            "device_id": device_id,
            "task_id": task_id,
            "keyword": keyword,
            "nv_mid": nv_mid,
            "store_name": store_name,
            "action_label": action_label,
            "success": False,
            "status": "INITIAL_MEASURE_FAILED",
            "error": err,
            "initial_rect": None,
            "attempts": 0,
            "layout_shifted": False,
            "max_delta_px": 0.0,
            "settled": False,
            "final_coord": None,
            "attempts_detail": [],
            "duration_sec": round(time.time() - t_start, 3)
        })
        return {"success": False, "error": err}

    initial_rect = {
        "top": prev.get("top"),
        "bottom": prev.get("bottom"),
        "left": prev.get("left"),
        "right": prev.get("right"),
        "width": prev.get("width"),
        "height": prev.get("height"),
        "cx": prev.get("cx"),
        "cy": prev.get("cy"),
        "isSelf": prev.get("isSelf")
    }

    logger.info(
        f"📐 [{action_label} 최초 계측] top={prev['top']}, bottom={prev['bottom']}, "
        f"h={prev['height']}, w={prev['width']} | isSelf={prev['isSelf']} | 초기좌표=({prev['cx']}, {prev['cy']})"
    )

    settled = False
    final_res = prev
    max_delta_px = 0.0
    layout_shifted = False

    # 2. 1.0초 간격으로 최대 max_retries회 재계측하여 정착 확인
    for attempt in range(1, max_retries + 1):
        await asyncio.sleep(interval_sec)

        curr = await cdp.evaluate(check_js)
        if not curr or not isinstance(curr, dict) or not curr.get("valid"):
            logger.warning(f"⚠️ [{action_label} {attempt}/{max_retries}회] 엘리먼트 소실 또는 재계측 실패 -> 대기 지속")
            attempts_detail.append({
                "attempt": attempt,
                "valid": False,
                "error": curr.get("error", "CDP_FAIL") if isinstance(curr, dict) else "CDP_FAIL"
            })
            continue

        # 상단, 하단, 높이, 너비 변위(Delta) 계산
        delta_top = round(abs(curr["top"] - prev["top"]), 1)
        delta_bottom = round(abs(curr["bottom"] - prev["bottom"]), 1)
        delta_h = round(abs(curr["height"] - prev["height"]), 1)
        delta_w = round(abs(curr["width"] - prev["width"]), 1)

        curr_max_delta = max(delta_top, delta_bottom, delta_h, delta_w)
        if curr_max_delta > max_delta_px:
            max_delta_px = curr_max_delta

        if delta_top > tolerance_px or delta_bottom > tolerance_px or delta_h > tolerance_px or delta_w > tolerance_px:
            layout_shifted = True

        is_cur_settled = (
            delta_top <= tolerance_px and
            delta_bottom <= tolerance_px and
            delta_h <= tolerance_px and
            delta_w <= tolerance_px and
            curr.get("isSelf")
        )

        attempts_detail.append({
            "attempt": attempt,
            "valid": True,
            "delta_top": delta_top,
            "delta_bottom": delta_bottom,
            "delta_h": delta_h,
            "delta_w": delta_w,
            "isSelf": curr.get("isSelf"),
            "hitTag": curr.get("hitTag"),
            "hitClass": curr.get("hitClass"),
            "is_settled": is_cur_settled,
            "cx": curr.get("cx"),
            "cy": curr.get("cy")
        })

        logger.info(
            f"⏳ [{action_label} 정착 점검 {attempt}/{max_retries}] "
            f"Δtop={delta_top:.1f}px, Δbottom={delta_bottom:.1f}px, Δh={delta_h:.1f}px, Δw={delta_w:.1f}px | isSelf={curr['isSelf']}"
        )

        # 변위가 허용 오차 이하로 완전히 멈추었고, 그 좌표가 타겟 본인이면 즉시 정착 확정
        if is_cur_settled:
            logger.info(f"✨ [{action_label} 레이아웃 완전 정착 성공 ({attempt}회차)] 최종 확정 좌표: ({curr['cx']}, {curr['cy']})")
            settled = True
            final_res = curr
            break

        prev = curr
        final_res = curr

    duration_sec = round(time.time() - t_start, 3)

    # 대기 후에도 타겟 본인이 아니면 다른 요소가 침범했거나 밀려난 것이므로 안전 차단
    if not final_res.get("isSelf"):
        logger.error(
            f"❌ [{action_label}] 타겟이 다른 요소에 가려졌거나 조준 불일치 "
            f"(hitTag={final_res.get('hitTag')}, hitClass='{final_res.get('hitClass')}') -> 터치 취소"
        )
        _record_stabilization_log({
            "timestamp": datetime.now().isoformat(),
            "time_epoch": round(time.time(), 3),
            "device_id": device_id,
            "task_id": task_id,
            "keyword": keyword,
            "nv_mid": nv_mid,
            "store_name": store_name,
            "action_label": action_label,
            "success": False,
            "status": "OCCLUDED_OR_MISALIGNED",
            "error": "TARGET_NOT_AT_COORDINATES",
            "initial_rect": initial_rect,
            "attempts": len(attempts_detail),
            "layout_shifted": layout_shifted,
            "max_delta_px": max_delta_px,
            "settled": False,
            "final_coord": {"x": final_res.get("cx"), "y": final_res.get("cy")},
            "hitTag": final_res.get("hitTag"),
            "hitClass": final_res.get("hitClass"),
            "attempts_detail": attempts_detail,
            "duration_sec": duration_sec
        })
        return {"success": False, "error": "TARGET_NOT_AT_COORDINATES"}

    status_label = "SETTLED_IMMEDIATE" if (settled and len(attempts_detail) == 1 and not layout_shifted) else (
        "SETTLED_AFTER_SHIFT" if layout_shifted else "SETTLED"
    )
    if not settled:
        status_label = "SETTLED_TIMEOUT_ACCEPTED"

    _record_stabilization_log({
        "timestamp": datetime.now().isoformat(),
        "time_epoch": round(time.time(), 3),
        "device_id": device_id,
        "task_id": task_id,
        "keyword": keyword,
        "nv_mid": nv_mid,
        "store_name": store_name,
        "action_label": action_label,
        "success": True,
        "status": status_label,
        "error": None,
        "initial_rect": initial_rect,
        "attempts": len(attempts_detail),
        "layout_shifted": layout_shifted,
        "max_delta_px": max_delta_px,
        "settled": settled,
        "final_coord": {"x": final_res["cx"], "y": final_res["cy"]},
        "hitTag": final_res.get("hitTag"),
        "hitClass": final_res.get("hitClass"),
        "attempts_detail": attempts_detail,
        "duration_sec": duration_sec
    })

    return {
        "success": True,
        "x": final_res["cx"],
        "y": final_res["cy"],
        "rect": final_res,
        "href": final_res.get("href", ""),
        "settled": settled,
        "layout_shifted": layout_shifted,
        "max_delta_px": max_delta_px
    }
