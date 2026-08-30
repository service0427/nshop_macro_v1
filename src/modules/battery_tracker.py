import os
import time
import datetime
import subprocess
import threading
import logging
from typing import Dict, Any, Optional
from src.config import BATTERY_LOG_DIR, BATTERY_SUMMARY_LOG

logger = logging.getLogger("BatteryTracker")


class BatteryTracker:
    """
    단말기 배터리 잔량(%) 및 충전/소모 추이 전문 로깅 매니저
    - 1사이클당 배터리 소모량 (Start -> End delta)
    - 대기/유휴 시간 동안의 배터리 충전량 (Idle Charging delta)
    - 온도(°C) 및 소요 시간 정밀 기록
    """
    _lock = threading.Lock()
    _last_idle_record: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_battery_info(cls, device_id: str) -> Dict[str, Any]:
        """ADB를 통해 단말기 배터리 잔량(%), 온도(°C), 충전 상태(USB/AC) 실시간 조회"""
        level = 100
        temp = 25.0
        charging = True
        try:
            out = subprocess.check_output(
                ["adb", "-s", device_id, "shell", "dumpsys battery"],
                timeout=4, stderr=subprocess.DEVNULL, text=True
            )
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("level:"):
                    level = int(line.split(":")[1].strip())
                elif line.startswith("temperature:"):
                    temp = int(line.split(":")[1].strip()) / 10.0
                elif line.startswith("USB powered:"):
                    charging = "true" in line.lower()
        except Exception:
            pass
        return {"level": level, "temp": temp, "charging": charging}

    @classmethod
    def log_task_cycle(
        cls,
        device_id: str,
        job_type: str,
        keyword: str,
        batt_start: int,
        temp_start: float,
        batt_end: int,
        temp_end: float,
        duration_sec: float,
        status: str
    ):
        """작업 1사이클 소모 배터리 및 온도 변화 기록"""
        delta = batt_end - batt_start
        delta_str = f"+{delta}%" if delta > 0 else f"{delta}%"
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")

        log_line = (
            f"[{now_str}] [CYCLE_END] [{device_id}] "
            f"배터리: {batt_start}% ➔ {batt_end}% ({delta_str}) | "
            f"온도: {temp_start:.1f}°C ➔ {temp_end:.1f}°C | "
            f"소요: {duration_sec:.1f}s | 상태: {status} | 모드: {job_type} | 키워드: '{keyword}'"
        )
        cls._append_log(today_str, log_line)
        logger.info(f"[{device_id}] 🔋 [배터리 변화 기록] {batt_start}% ➔ {batt_end}% ({delta_str}) | 소요: {duration_sec:.1f}s")

    @classmethod
    def log_idle_charge(
        cls,
        device_id: str,
        current_batt: int,
        current_temp: float,
        idle_duration: float
    ):
        """대기(충전) 중 배터리 변화 추적 및 기록"""
        with cls._lock:
            prev = cls._last_idle_record.get(device_id)
            if not prev:
                cls._last_idle_record[device_id] = {
                    "batt": current_batt,
                    "temp": current_temp,
                    "time": time.time()
                }
                return

            prev_batt = prev["batt"]
            prev_time = prev["time"]
            elapsed = time.time() - prev_time

            # 배터리 잔량에 변화가 있거나 60초 이상 경과 시 기록
            if current_batt != prev_batt or elapsed >= 60.0:
                delta = current_batt - prev_batt
                delta_str = f"+{delta}%" if delta > 0 else f"{delta}%"
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                today_str = datetime.datetime.now().strftime("%Y-%m-%d")

                log_line = (
                    f"[{now_str}] [IDLE_CHARGE] [{device_id}] "
                    f"대기 충전: {prev_batt}% ➔ {current_batt}% ({delta_str}) | "
                    f"온도: {current_temp:.1f}°C | 대기시간: {idle_duration:.1f}s (간격: {elapsed:.1f}s)"
                )
                cls._append_log(today_str, log_line)
                cls._last_idle_record[device_id] = {
                    "batt": current_batt,
                    "temp": current_temp,
                    "time": time.time()
                }

    @classmethod
    def _append_log(cls, today_str: str, log_line: str):
        with cls._lock:
            try:
                os.makedirs(BATTERY_LOG_DIR, exist_ok=True)
                daily_file = os.path.join(BATTERY_LOG_DIR, f"battery_{today_str}.log")
                for path in [daily_file, BATTERY_SUMMARY_LOG]:
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(log_line + "\n")
            except Exception as e:
                logger.warning(f"배터리 로그 기록 실패: {e}")
