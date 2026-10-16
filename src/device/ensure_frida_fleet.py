#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/device/ensure_frida_fleet.py

전체 온라인 단말기(20대)의 frida-server 무결성을 병렬로 검증 및 자동 복구/기동
"""

import sys
import subprocess
import concurrent.futures
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.device.device_selector import get_online_devices

LOCAL_FRIDA_BIN = Path("/tmp/frida-server")


def ensure_device_frida(device_id: str) -> bool:
    try:
        # 1. frida-server 프로세스 실행 여부 확인
        res = subprocess.run(
            ["adb", "-s", device_id, "shell", "su -c 'ps -ef | grep frida-server | grep -v grep'"],
            capture_output=True, text=True, timeout=5
        )
        if "frida-server" in res.stdout:
            return True

        # 2. /data/local/tmp/frida-server 파일 존재 및 실행 가능 확인
        chk_file = subprocess.run(
            ["adb", "-s", device_id, "shell", "su -c 'ls -l /data/local/tmp/frida-server'"],
            capture_output=True, text=True, timeout=5
        )
        if "No such file" in chk_file.stdout or chk_file.returncode != 0:
            if not LOCAL_FRIDA_BIN.exists():
                print(f"❌ [{device_id}] 호스트 /tmp/frida-server 파일이 없습니다.")
                return False
            # 파일 푸시
            subprocess.run(["adb", "-s", device_id, "push", str(LOCAL_FRIDA_BIN), "/data/local/tmp/frida-server"], capture_output=True, timeout=15)
            subprocess.run(["adb", "-s", device_id, "shell", "su -c 'chmod 755 /data/local/tmp/frida-server'"], capture_output=True, timeout=5)

        # 3. frida-server 백그라운드 데몬 기동
        subprocess.run(
            ["adb", "-s", device_id, "shell", "su -c 'nohup /data/local/tmp/frida-server >/dev/null 2>&1 &'"],
            capture_output=True, timeout=5
        )

        # 4. 재확인
        res_after = subprocess.run(
            ["adb", "-s", device_id, "shell", "su -c 'ps -ef | grep frida-server | grep -v grep'"],
            capture_output=True, text=True, timeout=5
        )
        return "frida-server" in res_after.stdout

    except Exception as e:
        print(f"⚠️ [{device_id}] frida 점검 예외: {e}")
        return False


def ensure_fleet_frida(devices=None):
    if devices is None:
        devices = get_online_devices()
    print(f"🔍 [Frida-Server Fleet 점검] 총 {len(devices)}대 단말기 검증 시작...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(devices), 20)) as ex:
        results = list(ex.map(ensure_device_frida, devices))

    success_cnt = sum(1 for r in results if r)
    print(f"✅ [Frida-Server Fleet 완료] {success_cnt}/{len(devices)}대 가동 확인!")
    return success_cnt == len(devices)


if __name__ == "__main__":
    ensure_fleet_frida()
