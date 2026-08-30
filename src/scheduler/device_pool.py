# -*- coding: utf-8 -*-
"""
========================================================================================
[모듈명] 디바이스 풀 & 하드웨어/안전 관리자 (DevicePool)
(src/scheduler/device_pool.py)
========================================================================================
- 기능:
    1. 활성 단말기 리스트 관리 및 IDLE/BUSY 상태 추적
    2. 배터리 20% 미만 방전 보호 (작업 할당 PASS & 충전 대기)
    3. 배터리 43°C 이상 과열 보호 (쿨다운 대기)
    4. ADB offline / 무응답 시 USB 하드웨어 버스 전원 리셋 (usbreset)
    5. 매 10초 주기 실시간 워커 현황판 콘솔 출력
    6. 비상 종료 시 전 단말기 앱/WireGuard 일괄 강제 종료
========================================================================================
"""

import os
import glob
import time
import json
import logging
import threading
import subprocess
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
from src.modules.battery_tracker import BatteryTracker
from src.config import DEVICE_SET_FILE

logger = logging.getLogger("DevicePool")

DEFAULT_ACTIVE_DEVICES: List[str] = []


def get_online_adb_devices() -> List[str]:
    """현재 USB/ADB로 실제 연결되어 있는 온라인(device 상태) 단말기 시리얼 실시간 동적 스캔"""
    try:
        out = subprocess.check_output(["adb", "devices"], timeout=5, text=True, stderr=subprocess.DEVNULL)
        online = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                online.append(parts[0])
        return online
    except Exception as e:
        logger.warning(f"ADB 장치 목록 동적 조회 실패: {e}")
        return []


def load_device_set(config_path: str = DEVICE_SET_FILE) -> List[str]:
    """
    [실시간 동적 단말기 로드]
    1. adb devices로 현재 온라인인 단말기 시리얼을 실시간 스캔 (하드코딩 원천 제거)
    2. device_set.json에 등록된 설정 우선순위 반영 및 신규 기기 자동 포함
    3. 연결된 모든 온라인 단말기 목록을 동적으로 반환
    """
    online_devs = get_online_adb_devices()
    if not online_devs:
        # 폴백: device_set.json 또는 기본 목록
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return list(json.load(f).keys())
            except Exception:
                pass
        return DEFAULT_ACTIVE_DEVICES

    # device_set.json에 등록된 순서가 있으면 우선 정렬, 새로운 기기도 자동 포함
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                known = list(json.load(f).keys())
                sorted_devs = [d for d in known if d in online_devs] + [d for d in online_devs if d not in known]
                return sorted_devs
        except Exception:
            pass

    return online_devs


class DevicePool:
    """단말기 풀 및 하드웨어 안전 관리자"""

    def __init__(self, device_ids: Optional[List[str]] = None, max_workers: Optional[int] = None):
        raw_devs = device_ids if device_ids else load_device_set()
        if max_workers and max_workers > 0:
            self.all_devices = raw_devs[:max_workers]
        else:
            self.all_devices = raw_devs
        self.max_workers = len(self.all_devices)
        self.lock = threading.Lock()
        self.busy_devices = set()

        self.device_status: Dict[str, Dict[str, Any]] = {
            dev: {
                "state": "IDLE",
                "cycle": 0,
                "job_type": "-",
                "keyword": "-",
                "allow_click": False,
                "start_time": 0.0,
                "last_duration": 0.0,
                "last_result": "대기 중",
                "completed_tasks": 0,
                "last_assigned_time": 0.0
            }
            for dev in self.all_devices
        }

    def get_device_battery_info(self, device_id: str) -> Dict[str, Any]:
        """단말기 배터리 정수 및 소수점 정밀 잔량(%), 잔여용량(mAh), 전압(V), 온도(°C) 확인"""
        return BatteryTracker.get_battery_info(device_id)

    def reset_usb_device(self, device_id: str) -> bool:
        """단말기 시리얼과 일치하는 USB 버스 포트를 하드웨어 레벨에서 전원 리셋 (usbreset)"""
        for s_path in glob.glob("/sys/bus/usb/devices/*/serial"):
            try:
                with open(s_path, "r") as f:
                    if f.read().strip() == device_id:
                        dev_dir = os.path.dirname(s_path)
                        busnum = open(os.path.join(dev_dir, "busnum")).read().strip().zfill(3)
                        devnum = open(os.path.join(dev_dir, "devnum")).read().strip().zfill(3)
                        usb_addr = f"{busnum}/{devnum}"
                        logger.warning(f"  [🔌 {device_id}] USB 하드웨어 버스 전원 리셋 실행 ({usb_addr})...")
                        subprocess.run(["usbreset", usb_addr], capture_output=True, timeout=5)
                        time.sleep(2.5)
                        subprocess.run(["adb", "-s", device_id, "wait-for-device"], timeout=12, capture_output=True)
                        logger.info(f"  [⚡ {device_id}] USB 전원 재인가 및 ADB 재연결 완료!")
                        return True
            except Exception:
                pass
        return False

    def get_idle_devices(self) -> List[str]:
        """가용 유휴 단말기 필터링 (초고속 비동기/논블로킹 분리)"""
        with self.lock:
            candidates = [d for d in self.all_devices if d not in self.busy_devices]

        if not candidates:
            return []

        available = []
        for dev in candidates:
            try:
                # 🔋 배터리 및 온도 안전 검사 (20% 미만 방전 방지 및 43°C 과열 보호)
                batt = self.get_device_battery_info(dev)
                level = batt.get("level", 100)
                level_precise = batt.get("level_precise", float(level))
                temp = batt.get("temp", 25.0)

                with self.lock:
                    idle_since = self.device_status[dev].get("idle_since", time.time())
                idle_dur = time.time() - idle_since
                BatteryTracker.log_idle_charge(dev, level_precise, temp, idle_dur)

                # 배터리 20% 미만 방전 보호
                if level < 20:
                    logger.warning(f"  [⚠️ {dev}] 배터리 부족 ({level}% < 20%) -> 방전 방지를 위해 이번 주기 할당 제외(PASS)")
                    with self.lock:
                        self.device_status[dev]["last_result"] = f"배터리부족({level}%) 충전대기"
                    continue

                # 배터리 43°C 이상 과열 보호
                if temp >= 43.0:
                    logger.warning(f"  [⚠️ {dev}] 단말기 과열 ({temp}°C >= 43°C) -> 쿨다운을 위해 이번 주기 할당 제외(PASS)")
                    with self.lock:
                        self.device_status[dev]["last_result"] = f"과열({temp}°C) 쿨다운"
                    continue

                available.append(dev)
            except Exception as e:
                logger.debug(f"  [⚠️ {dev}] 상태 검사 예외: {e}")
                available.append(dev)

        # ⚖️ [공평한 작업 분배 - Fair-Share Round Robin]
        with self.lock:
            available.sort(key=lambda d: (
                self.device_status[d].get("completed_tasks", 0),
                self.device_status[d].get("last_assigned_time", 0.0)
            ))
        return available

    def mark_busy(self, device_id: str, cycle_num: int, job_type: str, keyword: str, allow_click: bool):
        """단말기를 BUSY 상태로 전환"""
        with self.lock:
            self.busy_devices.add(device_id)
            prev_completed = self.device_status[device_id].get("completed_tasks", 0)
            self.device_status[device_id] = {
                "state": "BUSY",
                "cycle": cycle_num,
                "job_type": job_type,
                "keyword": keyword,
                "allow_click": allow_click,
                "start_time": time.time(),
                "last_duration": 0.0,
                "last_result": "작업 실행 중",
                "completed_tasks": prev_completed,
                "last_assigned_time": time.time()
            }

    def mark_idle(self, device_id: str, cycle_num: int, status_str: str, duration: float):
        """단말기를 IDLE 상태로 복구"""
        with self.lock:
            self.busy_devices.discard(device_id)
            res_tag = "성공" if status_str == "SUCCESS" else "실패"
            prev_completed = self.device_status[device_id].get("completed_tasks", 0)
            if status_str == "SUCCESS":
                prev_completed += 1
            last_assigned = self.device_status[device_id].get("last_assigned_time", 0.0)
            self.device_status[device_id] = {
                "state": "IDLE",
                "cycle": cycle_num,
                "job_type": "-",
                "keyword": "-",
                "allow_click": False,
                "start_time": 0.0,
                "idle_since": time.time(),
                "last_duration": duration,
                "last_result": f"주기 #{cycle_num} {res_tag}",
                "completed_tasks": prev_completed,
                "last_assigned_time": last_assigned
            }

    def print_status_board(self, cycle_num: int, idle_devices: List[str]):
        """실시간 워커 상태 현황판 콘솔 출력"""
        with self.lock:
            busy_cnt = len(self.busy_devices)
            idle_cnt = len(idle_devices)
            total_cnt = len(self.all_devices)

            logger.info("=" * 82)
            logger.info(f"⏱️  [스케줄러 주기 #{cycle_num}] 실시간 워커 현황판 (가용 유휴: {idle_cnt}대 / 작업 중: {busy_cnt}대 / 전체: {total_cnt}대)")
            logger.info("-" * 82)
            for idx, dev in enumerate(self.all_devices, 1):
                st = self.device_status[dev]
                if dev in self.busy_devices:
                    elapsed = int(time.time() - st.get("start_time", time.time()))
                    mode_tag = "🛒클릭모드" if st.get("allow_click") else "⚡탐색모드"
                    kw = st.get("keyword", "-")
                    cyc = st.get("cycle", 1)
                    logger.info(f"  [워커 #{idx}] {dev:<12} | 🏃 BUSY (주기 #{cyc} | {mode_tag} | 키워드: '{kw}' | 경과: {elapsed}s)")
                else:
                    last_res = st.get("last_result", "대기 중")
                    last_dur = st.get("last_duration", 0.0)
                    idle_sec = int(time.time() - st.get("idle_since", time.time())) if st.get("idle_since") else 0
                    dur_str = f"({last_dur}s)" if last_dur > 0 else ""
                    
                    if idle_sec >= 15:
                        idle_tag = f"⚠️ [재할당 대기 지연: {idle_sec}s]"
                    else:
                        idle_tag = f"[대기: {idle_sec}s]"

                    logger.info(f"  [워커 #{idx}] {dev:<12} | 🟢 IDLE ({last_res} {dur_str} | {idle_tag} ➔ 투입 대기)")
            logger.info("-" * 82)

    def emergency_cleanup_all(self):
        """비상 종료 시 전 단말기 앱 및 WireGuard 터널 일괄 강제 종료"""
        def _stop_dev(dev_id):
            try:
                subprocess.run(
                    ["adb", "-s", dev_id, "shell", "am force-stop com.nhn.android.search; am force-stop com.wireguard.android"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.0
                )
                logger.info(f"  [✓ {dev_id}] 네이버 앱 & WireGuard 터널 즉시 강제 종료 완료")
            except Exception as e:
                logger.warning(f"  [! {dev_id}] 종료 명령 오류: {e}")

        for dev_id in self.all_devices:
            _stop_dev(dev_id)
