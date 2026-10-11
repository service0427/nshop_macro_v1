#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NNB & BUC Provider Module:
- Supports fetching from Remote Aging Server (http://114.207.112.173:8000/api/v1/nnb/random)
- Supports fallback to Local NNB Harvester Pool
- 1200초 (20분) 세션 유지 정책: 1200초 이내에는 동일한 NNB/BUC를 유지하고 초과 시에만 신규 교체
"""

import time
import json
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

from src.core.nnb_harvester import get_next_ready_nnb

logger = logging.getLogger("NNBProvider")
DEFAULT_REMOTE_URL = "http://114.207.112.173:8000/api/v1/nnb/assign"

# 1200초 세션 캐시 관리
_CURRENT_SESSION_NNB: Optional[Dict[str, Any]] = None
_SESSION_START_TIME: float = 0.0
MAX_SESSION_AGE_SECONDS: int = 1200  # 20분 세션 수명


def fetch_remote_nnb(
    device_id: Optional[str] = None,
    api_url: str = DEFAULT_REMOTE_URL,
    timeout: float = 3.0
) -> Optional[Dict[str, Any]]:
    """
    Fetch aged NNB and BUC packet from remote assign server (/api/v1/nnb/assign).
    Supports GET with ?device_id=...
    Expected response:
    {
      "success": true,
      "nnb": "...",
      "buc": "...",
      "device_id": "...",
      "ip": "...",
      "use_count": 1,
      "age_seconds": 246084
    }
    """
    url = api_url
    if device_id:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}device_id={urllib.parse.quote(str(device_id))}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NShopMacro/1.0", "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                if body.get("success"):
                    # Check new assign endpoint format (flat keys)
                    if "nnb" in body:
                        return {
                            "nnb": body.get("nnb", ""),
                            "buc": body.get("buc", ""),
                            "source": "remote_assign_api",
                            "device_id": body.get("device_id", device_id),
                            "ip": body.get("ip", ""),
                            "use_count": body.get("use_count", 1),
                            "age_seconds": body.get("age_seconds", 0)
                        }
                    # Legacy data wrapper format
                    elif body.get("data") and isinstance(body["data"], dict):
                        data = body["data"]
                        return {
                            "nnb": data.get("nnb", ""),
                            "buc": data.get("buc", ""),
                            "source": "remote_api",
                            "id": data.get("id"),
                            "age_seconds": data.get("age_seconds", 0)
                        }
                else:
                    msg = body.get("message", "Unknown error")
                    retry = body.get("retry_after_seconds")
                    logger.warning(f"⚠️ [NNB 서버 응답] 할당 실패: {msg} (대기 필요: {retry}초)")
    except Exception as e:
        logger.warning(f"⚠️ Remote NNB API fetch failed ({e}), falling back to local pool")
    return None


def get_nnb_packet(
    device_id: Optional[str] = None,
    use_remote: bool = True,
    remote_url: str = DEFAULT_REMOTE_URL,
    max_age_seconds: int = MAX_SESSION_AGE_SECONDS,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Universal NNB Packet Provider with 1200초 세션 캐싱.
    - device_id 별 독립 NNB 발급 지원
    - 1200초 이내: 동일한 NNB & BUC를 재사용 유지 (단일 기기 모드)
    - 1200초 초과 (또는 force_refresh=True): 원격/로컬 신규 NNB & BUC 획득 및 세션 리셋
    """
    global _CURRENT_SESSION_NNB, _SESSION_START_TIME

    now = time.time()
    if not force_refresh and _CURRENT_SESSION_NNB is not None:
        elapsed = now - _SESSION_START_TIME
        if elapsed < max_age_seconds:
            logger.info(
                f"🔄 [NNB/BUC 세션 재사용] NNB={_CURRENT_SESSION_NNB.get('nnb')} | "
                f"BUC={'있음' if _CURRENT_SESSION_NNB.get('buc') else '없음'} | "
                f"세션 경과: {int(elapsed)}초 / {max_age_seconds}초"
            )
            return _CURRENT_SESSION_NNB
        else:
            logger.info(f"⏱️ [NNB 세션 만료] 세션 수명({int(elapsed)}초 > {max_age_seconds}초) 초과 -> 신규 NNB 교체 진행")

    # 신규 NNB 획득 (원격 우선 -> 로컬 폴백 -> 비상)
    packet = None
    if use_remote:
        remote_res = fetch_remote_nnb(device_id=device_id, api_url=remote_url)
        if remote_res and remote_res.get("nnb"):
            logger.info(
                f"✅ [NNB 신규 할당] 원격 서버 NNB 획득 성공: {remote_res['nnb']} "
                f"(기기: {remote_res.get('device_id')}, 원격숙성: {remote_res.get('age_seconds')}초, "
                f"IP: {remote_res.get('ip')}, use_count: {remote_res.get('use_count')})"
            )
            packet = remote_res

    if not packet:
        local_packet = get_next_ready_nnb()
        if local_packet and local_packet.get("nnb"):
            logger.info(f"📦 [NNB 신규 할당] 로컬 풀 NNB 획득: {local_packet['nnb']}")
            packet = {
                "nnb": local_packet["nnb"],
                "buc": local_packet.get("buc", ""),
                "source": "local_pool",
                "age_seconds": local_packet.get("age_seconds", 0)
            }

    if not packet:
        fallback_nnb = "WSQIOYAAZ3CGU"
        logger.warning(f"⚠️ [NNB 신규 할당] 모든 NNB 풀 소진 -> 비상 NNB 사용: {fallback_nnb}")
        packet = {
            "nnb": fallback_nnb,
            "buc": "",
            "source": "emergency_static",
            "age_seconds": 0
        }

    _CURRENT_SESSION_NNB = packet
    _SESSION_START_TIME = now
    logger.info(f"✨ [신규 NNB/BUC 세션 발급] NNB={packet.get('nnb')} (수명 {max_age_seconds}초 시작)")
    return packet


def get_current_session_info() -> Dict[str, Any]:
    global _CURRENT_SESSION_NNB, _SESSION_START_TIME
    if _CURRENT_SESSION_NNB is None:
        return {"active": False, "elapsed_seconds": 0, "nnb": None}
    elapsed = time.time() - _SESSION_START_TIME
    return {
        "active": True,
        "elapsed_seconds": int(elapsed),
        "remaining_seconds": max(0, int(MAX_SESSION_AGE_SECONDS - elapsed)),
        "nnb": _CURRENT_SESSION_NNB.get("nnb"),
        "buc": _CURRENT_SESSION_NNB.get("buc"),
        "source": _CURRENT_SESSION_NNB.get("source")
    }


def reset_nnb_session():
    global _CURRENT_SESSION_NNB, _SESSION_START_TIME
    _CURRENT_SESSION_NNB = None
    _SESSION_START_TIME = 0.0
    logger.info("🧹 [NNB 세션 초기화] 세션 캐시가 강제 리셋되었습니다.")
