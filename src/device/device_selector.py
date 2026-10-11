#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Device Selector Module:
- Discovers online devices via ADB
- Selects random device by default
- Supports explicit device override
"""

import subprocess
import random
import logging
from typing import List, Optional

logger = logging.getLogger("DeviceSelector")

def get_online_devices() -> List[str]:
    """
    Returns list of connected and authorized ADB serial numbers that support root (su).
    """
    try:
        res = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True)
        lines = res.stdout.strip().split("\n")[1:]
        devices = []
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == "device":
                serial = parts[0]
                # Check root capability
                su_check = subprocess.run(
                    ["adb", "-s", serial, "shell", "which su"],
                    capture_output=True, text=True, timeout=2
                )
                if su_check.returncode == 0 and "su" in su_check.stdout:
                    devices.append(serial)
                else:
                    logger.warning(f"⚠️ 기기 {serial}은(는) root(su) 권한이 없어 매크로 구동 대상에서 제외됩니다.")
        return devices
    except Exception as e:
        logger.error(f"❌ Failed to query ADB devices: {e}")
        return []

def select_device(explicit_device: Optional[str] = None) -> str:
    """
    Selects target ADB device.
    - If explicit_device is given and available, uses it.
    - Otherwise, randomly selects an available device (Default behavior).
    """
    online = get_online_devices()
    if not online:
        raise RuntimeError("❌ No online ADB devices connected! Check USB or adb server.")

    if explicit_device:
        if explicit_device in online:
            logger.info(f"📱 [단말기 지정 선택] {explicit_device}")
            return explicit_device
        else:
            logger.warning(f"⚠️ 지정된 단말기({explicit_device})가 오프라인입니다. 온라인 기기 중 랜덤 선택합니다.")

    chosen = random.choice(online)
    logger.info(f"🎲 [랜덤 단말기 선택] {chosen} (전체 온라인 기기: {len(online)}대)")
    return chosen
