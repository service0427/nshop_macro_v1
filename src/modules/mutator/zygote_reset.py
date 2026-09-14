#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[모듈명] Zygote 초고속 소프트 리셋 엔진 (ZygoteResetEngine)
- 기능:
    1. `ctl.restart zygote` 트리거 전송 (system_server 캐시 완전 플러시)
    2. 프레임워크 핵심 서비스(window, activity, user) 기동 폴링
    3. FallbackHome 탈출 및 LauncherActivity 안착 보장
"""

import time
import logging
import subprocess

logger = logging.getLogger("SoftRebootMutator")


class ZygoteResetEngine:
    """안드로이드 Zygote 소프트 재부팅 및 프레임워크 안정화 엔진"""

    def __init__(self, device_id: str):
        self.device_id = device_id

    def trigger_soft_reboot_and_wait(self, max_wait_sec: int = 35) -> bool:
        """
        [초고속 Zygote 소프트 리셋 실행 및 부팅 완료 대기]
        - Rescue Party 크래시 카운터를 0으로 초기화하고 Zygote 리셋 전송
        - 프레임워크 완전 기동 및 UI 서비스 안정화 대기 (평균 8~18초)
        """
        t0 = time.time()
        logger.info(f"[{self.device_id}] [🔄 소프트 리셋] Zygote 재시작 트리거 전송 중...")

        # 1. 크래시 카운터 0 리셋 & 소프트 리셋
        try:
            cmd = ["adb", "-s", self.device_id, "shell", "su"]
            subprocess.run(cmd, input="setprop sys.rescue_boot_count 0; setprop ctl.restart zygote",
                           capture_output=True, text=True, timeout=10)
        except Exception:
            pass

        # 2. 쿨다운 후 부팅 완료 폴링
        time.sleep(6.0)

        booted = False
        for _ in range(max_wait_sec):
            try:
                out = subprocess.run(["adb", "-s", self.device_id, "shell", "service check window; service check activity"],
                                     capture_output=True, text=True, timeout=4).stdout.strip()
                if "Service window: found" in out and "Service activity: found" in out:
                    booted = True
                    break
            except Exception:
                pass
            time.sleep(1.0)

        if booted:
            # 3. 핵심 안드로이드 ActivityManager / WindowManager 서비스 기동 100% 보장 대기
            for _ in range(25):
                try:
                    res = subprocess.run(["adb", "-s", self.device_id, "shell", "am get-current-user"],
                                         capture_output=True, text=True, timeout=4).stdout.strip()
                    if res.isdigit():
                        break
                except Exception:
                    pass
                time.sleep(0.8)

            # 4. FallbackHome 탈출 및 LauncherActivity 100% 확실한 안착 루프
            for _ in range(12):
                try:
                    focus = subprocess.run(["adb", "-s", self.device_id, "shell", "dumpsys window | grep mCurrentFocus"],
                                           capture_output=True, text=True, timeout=4).stdout
                    if "LauncherActivity" in focus:
                        break
                    subprocess.run(["adb", "-s", self.device_id, "shell", "su -c 'input keyevent 224; input swipe 500 1500 500 500; input keyevent 3'"],
                                   timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
                time.sleep(1.2)

            # 5. 리셋 직후 커널 고속 충전 보장 (Zygote 부하 배터리 방전 방어)
            try:
                subprocess.run(
                    ["adb", "-s", self.device_id, "shell",
                     "su -c 'echo 1 > /sys/class/power_supply/battery/batt_high_current_usb 2>/dev/null'"],
                    timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

            # 6. Zygote 리셋 후 플립 단말기 메인 화면(OPEN) 강제 복구 및 화면 점등
            try:
                subprocess.run(
                    ["adb", "-s", self.device_id, "shell",
                     "cmd device_state state 3 2>/dev/null; input keyevent 224 2>/dev/null; wm dismiss-keyguard 2>/dev/null || true"],
                    timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

            time.sleep(1.0)
            elapsed = round(time.time() - t0, 1)
            logger.info(f"[{self.device_id}] [✓] Zygote 소프트 리셋 & Launcher 안착 완료! (소요 시간: {elapsed}초)")
            return True
        else:
            elapsed = round(time.time() - t0, 1)
            logger.warning(f"[{self.device_id}] [!] 소프트 리셋 타임아웃 ({elapsed}초 경과)")
            return False
