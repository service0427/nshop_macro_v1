# -*- coding: utf-8 -*-
"""
========================================================================================
[모듈명] 디바이스 전원 및 충전집중/슬립/Wakeup 관리자 (DevicePowerManager)
(src/modules/device_power_manager.py)
========================================================================================
- 핵심 기능:
    1. [충전 집중 모드 (Fast-Charge Sleep Mode)]:
       - 배터리 20% 미만 방전 감지 시 즉시 화면 OFF (`input keyevent 26`) 및 백그라운드 프로세스 정리
       - 10분간(600초) 단말기 대상 ADB 통신 0회(Zero-Polling) 보장 ➔ CPU Deep Sleep 유도 & 초고속 충전
    2. [과열 쿨다운 모드 (Overheat Cooldown Mode)]:
       - 배터리 온도 43°C 이상 감지 시 5분간 화면 OFF 및 Zero-Polling 쿨다운
    3. [스마트 Wakeup 복구 관리 (Smart Wakeup Lifecycle)]:
       - 10분/5분 쿨다운 만료 시점에 단 1회 헬스 체크
       - 배터리/온도 정상 복구 확인 시 화면 WAKEUP (`input keyevent 224`) 및 잠금 해제 후 정상 풀 복귀
    4. [단말기 화면 전원 직접 제어]:
       - `put_to_sleep(device_id, reason)`: 화면 OFF 및 슬립 진입
       - `wakeup_device(device_id)`: 화면 ON 및 슬립 해제
       - `is_screen_on(device_id)`: 화면 점등 여부 실시간 계측
========================================================================================
"""

import time
import logging
import threading
import subprocess
from typing import Dict, Any, Optional, Tuple

from src.modules.battery_tracker import BatteryTracker

logger = logging.getLogger("DevicePowerManager")


class DevicePowerManager:
    """
    단말기 저전력 슬립, 충전 집중 모드 및 Wakeup 전담 라이프사이클 관리자
    """
    # 안전 임계값 정의
    LOW_BATT_THRESHOLD: float = 20.0        # 배터리 방전 보호 진입 임계값 (%)
    LOW_BATT_RECOVER_THRESHOLD: float = 20.0# 충전 복귀 임계값 (%)
    LOW_BATT_SLEEP_SEC: float = 600.0       # 충전 집중 모드 유지 시간 (10분 = 600초)

    OVERHEAT_THRESHOLD: float = 43.0        # 과열 보호 진입 임계값 (°C)
    OVERHEAT_COOLDOWN_SEC: float = 300.0    # 과열 쿨다운 유지 시간 (5분 = 300초)

    def __init__(self):
        self._lock = threading.Lock()
        # 단말기별 쿨다운 만료 타임스탬프 (device_id -> timestamp)
        self._low_batt_cooldown: Dict[str, float] = {}
        self._overheat_cooldown: Dict[str, float] = {}
        # 마지막 기록된 배터리 정보 캐시
        self._last_battery_info: Dict[str, Dict[str, Any]] = {}

    # =========================================================================
    # 1. 화면 및 전원 저수준 ADB 제어 (Sleep / Wakeup)
    # =========================================================================

    @staticmethod
    def put_to_sleep(device_id: str, reason: str = "FAST_CHARGE") -> bool:
        """
        [단말기 강제 슬립] 화면 즉시 OFF 및 백그라운드 프로세스 완전 종료
        - CPU 절전 (Deep Sleep) 및 AMOLED 0W 블랙아웃으로 충전 속도 극대화
        """
        try:
            logger.info(f"[{device_id}] 💤 [화면 OFF & 슬립 진입] 사유: {reason} ➔ 고속 충전 전류 확보")
            cmd = (
                "am force-stop com.nhn.android.search 2>/dev/null; "
                "am force-stop com.wireguard.android 2>/dev/null; "
                "input keyevent 26 2>/dev/null || true"
            )
            subprocess.run(
                ["adb", "-s", device_id, "shell", cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3.0
            )
            return True
        except Exception as e:
            logger.warning(f"[{device_id}] 슬립 전환 명령 실패: {e}")
            return False

    @staticmethod
    def wakeup_device(device_id: str) -> bool:
        """
        [단말기 Wakeup] 화면 WAKEUP 신호 전송 및 잠금 해제
        """
        try:
            logger.info(f"[{device_id}] 🔋 [화면 WAKEUP] 충전/쿨다운 완료 ➔ 화면 점등 및 작업 풀 복귀")
            # 224 = KEYCODE_WAKEUP, 82 = KEYCODE_MENU (잠금화면 슬라이드 해제)
            cmd = "input keyevent 224 2>/dev/null; sleep 0.2; input keyevent 82 2>/dev/null || true"
            subprocess.run(
                ["adb", "-s", device_id, "shell", cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3.0
            )
            return True
        except Exception as e:
            logger.warning(f"[{device_id}] Wakeup 명령 실패: {e}")
            return False

    @staticmethod
    def is_screen_on(device_id: str) -> bool:
        """단말기 화면이 현재 켜져 있는지 확인"""
        try:
            out = subprocess.check_output(
                ["adb", "-s", device_id, "shell", "dumpsys power | grep -iE 'Display Power: state=|mHoldingDisplaySuspendBlocker'"],
                stderr=subprocess.DEVNULL,
                timeout=3.0,
                text=True
            )
            return "state=ON" in out or "mHoldingDisplaySuspendBlocker=true" in out
        except Exception:
            return True

    # =========================================================================
    # 2. 충전 집중 모드 및 쿨다운 라이프사이클 관리
    # =========================================================================

    def evaluate_device_power_state(self, device_id: str) -> Dict[str, Any]:
        """
        [가용성 및 충전집중모드 통합 판별 (Zero-Polling 최적화)]
        
        1. 이미 10분 충전집중 모드 중인 경우:
           - ADB 통신을 100% 생략(Zero-Polling)하고 즉시 대기 상태 반환
        2. 10분 쿨다운이 만료된 경우:
           - 단 1회 실제 배터리 잔량 검사 -> 복구 시 wakeup 및 풀 복귀, 미복구 시 10분 추가 연장
        3. 정상 상태인 경우:
           - 실시간 배터리/온도 검사 후 임계값 미달 시 충전집중모드로 전환
        """
        now = time.time()

        with self._lock:
            low_batt_end = self._low_batt_cooldown.get(device_id, 0.0)
            overheat_end = self._overheat_cooldown.get(device_id, 0.0)

        # -------------------------------------------------------------
        # Case A: 10분 충전 집중 모드(Zero-Polling) 실행 중
        # -------------------------------------------------------------
        if now < low_batt_end:
            remain_sec = int(low_batt_end - now)
            m, s = divmod(remain_sec, 60)
            return {
                "is_available": False,
                "mode": "FAST_CHARGE_SLEEP",
                "remaining_sec": remain_sec,
                "status_text": f"⚡충전집중({m}분{s}초대기)",
                "reason": "LOW_BATTERY_SLEEP"
            }

        # -------------------------------------------------------------
        # Case B: 5분 과열 쿨다운(Zero-Polling) 실행 중
        # -------------------------------------------------------------
        if now < overheat_end:
            remain_sec = int(overheat_end - now)
            m, s = divmod(remain_sec, 60)
            return {
                "is_available": False,
                "mode": "OVERHEAT_COOLDOWN",
                "remaining_sec": remain_sec,
                "status_text": f"❄️과열쿨다운({m}분{s}초대기)",
                "reason": "OVERHEAT_COOLDOWN"
            }

        # -------------------------------------------------------------
        # Case C: 쿨다운 만료 시점 또는 평시 헬스 체크 (1회 ADB 계측)
        # -------------------------------------------------------------
        try:
            batt = BatteryTracker.get_battery_info(device_id)
            level = batt.get("level", 100)
            level_precise = batt.get("level_precise", float(level))
            temp = batt.get("temp", 25.0)

            with self._lock:
                self._last_battery_info[device_id] = batt

            # 1. 저배터리 (<20%) 검사 및 충전 집중 모드 진입
            if level < self.LOW_BATT_THRESHOLD:
                with self._lock:
                    self._low_batt_cooldown[device_id] = now + self.LOW_BATT_SLEEP_SEC
                
                logger.warning(
                    f"[{device_id}] ⚠️ 배터리 부족 ({level}% < {self.LOW_BATT_THRESHOLD}%) 감지 "
                    f"➔ 10분간 [충전 집중 모드(Zero-Polling Fast-Charge)] 진입 (화면 OFF & ADB 통신 차단)"
                )
                self.put_to_sleep(device_id, reason=f"LOW_BATTERY_{level}%")
                return {
                    "is_available": False,
                    "mode": "FAST_CHARGE_SLEEP",
                    "remaining_sec": int(self.LOW_BATT_SLEEP_SEC),
                    "status_text": f"⚡충전집중(10분대기, {level}%)",
                    "reason": "LOW_BATTERY_ENTERED",
                    "battery_info": batt
                }

            # 기존 쿨다운 상태였다가 복구된 경우: Wakeup 실행
            with self._lock:
                was_low = device_id in self._low_batt_cooldown
                if was_low:
                    del self._low_batt_cooldown[device_id]

            if was_low:
                logger.info(f"[{device_id}] 🎉 배터리 정상 복구 확인 ({level}% >= {self.LOW_BATT_RECOVER_THRESHOLD}%) ➔ 화면 WAKEUP 및 정상 풀 복귀!")
                self.wakeup_device(device_id)

            # 2. 과열 (>=43°C) 검사 및 쿨다운 진입
            if temp >= self.OVERHEAT_THRESHOLD:
                with self._lock:
                    self._overheat_cooldown[device_id] = now + self.OVERHEAT_COOLDOWN_SEC

                logger.warning(
                    f"[{device_id}] ⚠️ 단말기 과열 ({temp}°C >= {self.OVERHEAT_THRESHOLD}°C) 감지 "
                    f"➔ 5분간 [쿨다운 모드] 진입 (화면 OFF & ADB 통신 차단)"
                )
                self.put_to_sleep(device_id, reason=f"OVERHEAT_{temp}C")
                return {
                    "is_available": False,
                    "mode": "OVERHEAT_COOLDOWN",
                    "remaining_sec": int(self.OVERHEAT_COOLDOWN_SEC),
                    "status_text": f"❄️과열쿨다운(5분대기, {temp}°C)",
                    "reason": "OVERHEAT_ENTERED",
                    "battery_info": batt
                }

            with self._lock:
                was_hot = device_id in self._overheat_cooldown
                if was_hot:
                    del self._overheat_cooldown[device_id]

            if was_hot:
                logger.info(f"[{device_id}] ❄️ 단말기 쿨다운 완료 ({temp}°C) ➔ 화면 WAKEUP 및 정상 풀 복귀!")
                self.wakeup_device(device_id)

            # 모든 조건 충족 ➔ 정상 가용
            return {
                "is_available": True,
                "mode": "NORMAL",
                "remaining_sec": 0,
                "status_text": "정상 가용",
                "reason": "HEALTHY",
                "battery_info": batt
            }

        except Exception as e:
            logger.debug(f"[{device_id}] 전원 상태 검사 예외: {e}")
            return {
                "is_available": True,
                "mode": "NORMAL",
                "remaining_sec": 0,
                "status_text": "상태 확인 지연",
                "reason": "EXCEPTION_FALLBACK"
            }

    def is_in_cooldown(self, device_id: str) -> bool:
        """단말기가 현재 충전 집중 모드 또는 쿨다운 중인지 여부 (0.0001초 메모리 확인)"""
        now = time.time()
        with self._lock:
            return (now < self._low_batt_cooldown.get(device_id, 0.0) or
                    now < self._overheat_cooldown.get(device_id, 0.0))

    def reset_cooldown(self, device_id: str):
        """특정 단말기 쿨다운 강제 해제 및 즉시 Wakeup"""
        with self._lock:
            self._low_batt_cooldown.pop(device_id, None)
            self._overheat_cooldown.pop(device_id, None)
        self.wakeup_device(device_id)
