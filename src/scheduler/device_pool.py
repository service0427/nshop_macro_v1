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
from src.modules.device_power_manager import DevicePowerManager
from src.config import (
    DEVICE_SET_FILE,
    EXCLUDED_DEVICES,
    DEVICE_COOLDOWN_SEC,
    DEVICE_COOLDOWN_FILE,
    DEVICE_FAIL_COOLDOWN_SEC,
    DEVICE_FAIL_COOLDOWN_FILE
)

logger = logging.getLogger("DevicePool")

DEFAULT_ACTIVE_DEVICES: List[str] = []


def get_online_adb_devices() -> List[str]:
    """현재 USB/ADB로 실제 연결되어 있는 온라인(device 상태) 단말기 시리얼 실시간 100% 동적 스캔"""
    for retry in range(3):
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
            if online:
                return online
        except Exception as e:
            logger.warning(f"ADB 장치 목록 동적 조회 재시도 ({retry + 1}/3): {e}")
            time.sleep(0.5)
    return []


def load_device_set(config_path: str = DEVICE_SET_FILE) -> List[str]:
    """
    [실시간 100% 동적 단말기 로드]
    - adb devices에서 실시간으로 감지된 온라인 단말기 목록만 즉시 반환
    - 하드코딩이나 정적 파일 기반 폴백을 원천 배제하여 현재 연결된 실단말기만 정확히 투입
    """
    online_devs = get_online_adb_devices()
    return online_devs


class DevicePool:
    """단말기 풀 및 하드웨어 안전 관리자"""

    def __init__(
        self,
        device_ids: Optional[List[str]] = None,
        exclude_device_ids: Optional[List[str]] = None,
        max_workers: Optional[int] = None,
        device_cooldown_sec: Optional[float] = None,
        device_fail_cooldown_sec: Optional[float] = None
    ):
        self.exclude_device_ids = set(exclude_device_ids if exclude_device_ids is not None else EXCLUDED_DEVICES)
        self.specified_device_ids = [d for d in device_ids if d not in self.exclude_device_ids] if device_ids else None
        raw_devs = self.specified_device_ids if self.specified_device_ids else [d for d in load_device_set() if d not in self.exclude_device_ids]
        if max_workers and max_workers > 0:
            self.all_devices = raw_devs[:max_workers]
        else:
            self.all_devices = raw_devs
        self.max_workers = len(self.all_devices)
        self.lock = threading.Lock()
        self.busy_devices = set()
        self.power_manager = DevicePowerManager()

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
        self.device_cooldown_sec: float = float(device_cooldown_sec) if device_cooldown_sec is not None else DEVICE_COOLDOWN_SEC
        self.device_fail_cooldown_sec: float = float(device_fail_cooldown_sec) if device_fail_cooldown_sec is not None else DEVICE_FAIL_COOLDOWN_SEC
        self.cooldown_history: Dict[str, float] = self._load_cooldown_history()
        self.fail_cooldown_history: Dict[str, float] = self._load_fail_cooldown_history()

        # 기존 쿨다운 이력 기반 초기 상태 반영
        now_ts = time.time()
        for dev in self.all_devices:
            # 1. 24h 성공 쿨다운 검사
            last_done = self.cooldown_history.get(dev, 0.0)
            if last_done > 0:
                elapsed = now_ts - last_done
                if elapsed < self.device_cooldown_sec:
                    remain_sec = int(self.device_cooldown_sec - elapsed)
                    remain_h = round(remain_sec / 3600, 1)
                    self.device_status[dev]["state"] = "COOLDOWN"
                    self.device_status[dev]["last_result"] = f"24h 쿨다운 ({remain_h}h 남음)"
                    continue

            # 2. 실패 쿨다운 검사
            last_fail = self.fail_cooldown_history.get(dev, 0.0)
            if last_fail > 0:
                elapsed_fail = now_ts - last_fail
                if elapsed_fail < self.device_fail_cooldown_sec:
                    remain_sec = int(self.device_fail_cooldown_sec - elapsed_fail)
                    remain_h = round(remain_sec / 3600, 1)
                    remain_m = round(remain_sec / 60, 1)
                    time_str = f"{remain_h}h" if remain_sec >= 3600 else f"{remain_m}m"
                    self.device_status[dev]["state"] = "FAIL_COOLDOWN"
                    self.device_status[dev]["last_result"] = f"실패 쿨다운 ({time_str} 남음)"

        self.usb_port_map: Dict[str, str] = self._detect_usb_ports()
        self._print_startup_hardware_summary()

    def _load_cooldown_history(self) -> Dict[str, float]:
        """디바이스별 24시간 쿨다운 영구 기록 로드"""
        try:
            if os.path.exists(DEVICE_COOLDOWN_FILE):
                with open(DEVICE_COOLDOWN_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return {k: float(v) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"[-] 디바이스 쿨다운 히스토리 로드 실패: {e}")
        return {}

    def _save_cooldown_history(self):
        """디바이스별 24시간 쿨다운 영구 기록 저장"""
        try:
            os.makedirs(os.path.dirname(DEVICE_COOLDOWN_FILE), exist_ok=True)
            with open(DEVICE_COOLDOWN_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cooldown_history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[-] 디바이스 쿨다운 히스토리 저장 실패: {e}")

    def _load_fail_cooldown_history(self) -> Dict[str, float]:
        """디바이스별 실패 쿨다운 기록 로드"""
        try:
            if os.path.exists(DEVICE_FAIL_COOLDOWN_FILE):
                with open(DEVICE_FAIL_COOLDOWN_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return {k: float(v) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"[-] 디바이스 실패 쿨다운 히스토리 로드 실패: {e}")
        return {}

    def _save_fail_cooldown_history(self):
        """디바이스별 실패 쿨다운 기록 저장"""
        try:
            os.makedirs(os.path.dirname(DEVICE_FAIL_COOLDOWN_FILE), exist_ok=True)
            with open(DEVICE_FAIL_COOLDOWN_FILE, "w", encoding="utf-8") as f:
                json.dump(self.fail_cooldown_history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[-] 디바이스 실패 쿨다운 히스토리 저장 실패: {e}")

    def send_to_back(self, device_id: str):
        """단말기를 대기열의 최후순위(맨 뒤)로 회전 이동하여 대기 중인 다른 모든 단말기가 먼저 소진되도록 보장"""
        with self.lock:
            if device_id in self.all_devices:
                self.all_devices.remove(device_id)
                self.all_devices.append(device_id)
                logger.info(f"[{device_id}] 🔄 [대기열 후순위 회전] 단말기를 큐 맨 뒤로 배치 완료 (다른 단말기 우선 투입)")

    def _detect_usb_ports(self) -> Dict[str, str]:
        """단말기 시리얼별 물리 USB 포트 경로 매핑 딕셔너리 산출"""
        mapping = {}
        for s_path in glob.glob("/sys/bus/usb/devices/*/serial"):
            try:
                with open(s_path, "r") as f:
                    serial = f.read().strip()
                    dev_dir = os.path.dirname(s_path)
                    port_name = os.path.basename(dev_dir)
                    busnum = open(os.path.join(dev_dir, "busnum")).read().strip().zfill(3)
                    devnum = open(os.path.join(dev_dir, "devnum")).read().strip().zfill(3)
                    mapping[serial] = f"{port_name} (Bus {busnum}/{devnum})"
            except Exception:
                pass
        return mapping

    def _print_startup_hardware_summary(self):
        """데몬 시작 시 연결된 모든 단말기 및 물리 USB 포트, 배터리 현황 요약 출력"""
        logger.info("=" * 82)
        logger.info(f"📱 [하드웨어 초기화] 총 {len(self.all_devices)}대 온라인 단말기 및 USB 포트 감지 완료")
        logger.info("-" * 82)
        for idx, dev in enumerate(self.all_devices, 1):
            port = self.usb_port_map.get(dev, "Unknown Port")
            batt = BatteryTracker.get_battery_info(dev)
            level = batt.get("level", "N/A")
            temp = batt.get("temp", "N/A")
            logger.info(f"  [단말기 #{idx}] {dev:<12} | 포트: {port:<20} | ⚡ 배터리: {level}% | 🌡️ 온도: {temp}°C")
        logger.info("=" * 82)

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

    def refresh_online_devices(self, force: bool = False) -> List[str]:
        """주기적(1, 11, 21...)으로만 USB/ADB 연결 상태를 스캔하여 단말기 목록 들쭉날쭉 변동을 원천 방지"""
        if not force:
            return self.all_devices

        online_devs = [d for d in get_online_adb_devices() if d not in self.exclude_device_ids]
        if not online_devs:
            return self.all_devices

        if self.specified_device_ids:
            return [d for d in self.specified_device_ids if d in online_devs]

        with self.lock:
            for d in online_devs:
                if d not in self.all_devices:
                    self.all_devices.append(d)
                    self.device_status[d] = {
                        "state": "IDLE",
                        "current_job": None,
                        "keyword": "-",
                        "allow_click": False,
                        "start_time": 0.0,
                        "last_duration": 0.0,
                        "last_result": "신규 연결",
                        "completed_tasks": 0,
                        "last_assigned_time": 0.0,
                        "idle_since": time.time()
                    }
                    logger.info(f"  [🔌 실시간 기기 감지] 신규 단말기 ({d})가 풀에 자동 추가되었습니다!")
            self.max_workers = len(self.all_devices)
        return online_devs

    def get_idle_devices(self, do_refresh: bool = False) -> List[str]:
        """가용 유휴 단말기 필터링 (24시간 단말기 성공 쿨다운 + 실패 쿨다운 + 배터리/과열 안전 검사)"""
        online_devs = self.refresh_online_devices(force=do_refresh)
        with self.lock:
            candidates = [d for d in self.all_devices if d in online_devs and d not in self.busy_devices]

        if not candidates:
            return []

        available = []
        now_ts = time.time()
        for dev in candidates:
            # 1. 24시간 디바이스 성공 쿨다운 검사 (1회성 검증 모드: 단말기 1대당 24시간 내 1회만 투입)
            last_done = self.cooldown_history.get(dev, 0.0)
            if last_done > 0:
                elapsed = now_ts - last_done
                if elapsed < self.device_cooldown_sec:
                    remain_sec = int(self.device_cooldown_sec - elapsed)
                    remain_h = round(remain_sec / 3600, 1)
                    with self.lock:
                        self.device_status[dev]["state"] = "COOLDOWN"
                        self.device_status[dev]["last_result"] = f"24h 쿨다운 ({remain_h}h 남음)"
                    continue

            # 2. 실패 / 클릭 실패 디바이스 쿨다운 검사 (연속 재시도 및 아이피만 변경한 중복 실행 원천 차단)
            last_fail = self.fail_cooldown_history.get(dev, 0.0)
            if last_fail > 0:
                elapsed_fail = now_ts - last_fail
                last_res = str(self.device_status[dev].get("last_result", ""))
                is_infra_fail = any(x in last_res for x in ["IP_COOLDOWN", "2차방어선", "TUNNEL_DOWN", "WIFI_DISCONNECTED", "터널", "완충"])
                cooldown_sec = 60.0 if is_infra_fail else self.device_fail_cooldown_sec
                if elapsed_fail < cooldown_sec:
                    remain_sec = int(cooldown_sec - elapsed_fail)
                    remain_h = round(remain_sec / 3600, 1)
                    remain_m = round(remain_sec / 60, 1)
                    time_str = f"{remain_h}h" if remain_sec >= 3600 else f"{remain_m}m"
                    with self.lock:
                        self.device_status[dev]["state"] = "FAIL_COOLDOWN"
                        self.device_status[dev]["last_result"] = f"인프라 완충 ({time_str} 남음)" if is_infra_fail else f"실패 쿨다운 ({time_str} 남음)"
                    continue

            # 3. 배터리 및 과열 상태 검사
            eval_res = self.power_manager.evaluate_device_power_state(dev)
            if not eval_res.get("is_available", True):
                with self.lock:
                    self.device_status[dev]["last_result"] = eval_res.get("status_text", "충전/쿨다운 대기")
                continue

            batt_info = eval_res.get("battery_info") or {}
            if batt_info:
                with self.lock:
                    idle_since = self.device_status[dev].get("idle_since", time.time())
                idle_dur = time.time() - idle_since
                BatteryTracker.log_idle_charge(
                    dev,
                    batt_info.get("level_precise", float(batt_info.get("level", 100))),
                    batt_info.get("temp", 25.0),
                    idle_dur
                )

            available.append(dev)

        # ⚖️ [공평한 작업 분배 - Fair-Share Round Robin]
        # 직전 투입 시각이 가장 오래된(또는 미투입된) 단말기를 최우선으로 정렬하여 균등 분배 보장
        with self.lock:
            available.sort(key=lambda d: (
                self.device_status[d].get("completed_tasks", 0),
                self.device_status[d].get("last_assigned_time", 0.0)
            ))
        return available

    def is_all_devices_completed(self) -> bool:
        """모든 등록 단말기가 금일 1회 성공 쿨다운(24h)에 진입했는지 검사"""
        now_ts = time.time()
        with self.lock:
            if not self.all_devices:
                return False
            # 작업 중인 단말기가 남아있으면 아직 미완료
            if len(self.busy_devices) > 0:
                return False
            for dev in self.all_devices:
                last_done = self.cooldown_history.get(dev, 0.0)
                if (now_ts - last_done) >= self.device_cooldown_sec:
                    return False
            return True

    def mark_busy(self, device_id: str, cycle_num: int, job_type: str, keyword: str, allow_click: bool):
        """단말기를 BUSY 상태로 전환 (슬립 해제, 화면 점등 및 대기 큐 후순위 이동)"""
        self.power_manager.wakeup_device(device_id)
        self.send_to_back(device_id)
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

    def mark_idle(
        self,
        device_id: str,
        cycle_num: int,
        status_str: str,
        duration: float,
        is_clicked: bool = False,
        allow_click: bool = False,
        error_reason: Optional[str] = None
    ):
        """
        단말기를 IDLE 또는 쿨다운 상태로 복구:
        - 클릭 성공: 24h COOLDOWN & 화면 절전 슬립
        - 클릭 실패 / 작업 실패: 대기열 최후순위(맨 뒤) 회전 이동 & 실패 쿨다운 부여 & 화면 절전 슬립
        """
        now_ts = time.time()
        is_click_success = (status_str == "SUCCESS") and (is_clicked if allow_click else True)
        is_click_fail = allow_click and (not is_clicked)

        with self.lock:
            self.busy_devices.discard(device_id)
            prev_completed = self.device_status[device_id].get("completed_tasks", 0)
            last_assigned = self.device_status[device_id].get("last_assigned_time", 0.0)

            if is_click_success:
                prev_completed += 1
                # 24시간 성공 디바이스 쿨다운 등록 & 영구 저장
                self.cooldown_history[device_id] = now_ts
                self._save_cooldown_history()
                self.fail_cooldown_history.pop(device_id, None)
                self._save_fail_cooldown_history()
                new_state = "COOLDOWN"
                last_res_str = f"주기 #{cycle_num} 성공 (24h 쿨다운 진입)"
            else:
                # 클릭 실패 또는 작업 실패: 대기 큐 맨 뒤로 이동 & 실패 쿨다운 부여
                self.fail_cooldown_history[device_id] = now_ts
                self._save_fail_cooldown_history()
                new_state = "FAIL_COOLDOWN"
                fail_h = round(self.device_fail_cooldown_sec / 3600, 1)
                fail_m = round(self.device_fail_cooldown_sec / 60, 1)
                time_str = f"{fail_h}h" if self.device_fail_cooldown_sec >= 3600 else f"{fail_m}m"
                if error_reason and ("IP_COOLDOWN" in error_reason):
                    last_res_str = f"주기 #{cycle_num} 2차방어선 차단({error_reason}) ➔ 큐 후순위 (60s 완충)"
                elif error_reason and any(k in error_reason for k in ["TUNNEL_DOWN", "WIFI_DISCONNECTED", "터널"]):
                    last_res_str = f"주기 #{cycle_num} 라우터/터널 불통({error_reason}) ➔ 큐 후순위 (60s 완충)"
                elif is_click_fail:
                    last_res_str = f"주기 #{cycle_num} 클릭실패(미노출/전환실패) ➔ 큐 후순위 ({time_str} 쿨다운)"
                elif error_reason:
                    last_res_str = f"주기 #{cycle_num} 실패({error_reason}) ➔ 큐 후순위 ({time_str} 쿨다운)"
                else:
                    last_res_str = f"주기 #{cycle_num} 실패 ➔ 큐 후순위 ({time_str} 쿨다운)"

            self.device_status[device_id] = {
                "state": new_state,
                "cycle": cycle_num,
                "job_type": "-",
                "keyword": "-",
                "allow_click": False,
                "start_time": 0.0,
                "idle_since": now_ts,
                "last_duration": duration,
                "last_result": last_res_str,
                "completed_tasks": prev_completed,
                "last_assigned_time": last_assigned
            }

        # 대기열 최후순위(맨 뒤)로 회전 이동하여 다른 대기 단말기들이 먼저 투입되도록 보장
        self.send_to_back(device_id)

        # 성공(24h 쿨다운) 또는 실패(실패 쿨다운) 단말기 모두 화면 OFF 절전 슬립 모드 전환
        if is_click_success:
            self.power_manager.put_to_sleep(device_id, reason="24H_DEVICE_COOLDOWN")
        else:
            self.power_manager.put_to_sleep(device_id, reason="FAIL_DEVICE_COOLDOWN")

    def print_status_board(self, cycle_num: int, idle_devices: List[str]):
        """실시간 워커 상태 현황판 콘솔 출력"""
        with self.lock:
            busy_cnt = len(self.busy_devices)
            idle_cnt = len(idle_devices)
            total_cnt = len(self.all_devices)

            logger.info("=" * 82)
            logger.info(f"⏱️  [스케줄러 주기 #{cycle_num}] 실시간 워커 현황판 (가용 유휴: {idle_cnt}대 / 작업 중: {busy_cnt}대 / 전체: {total_cnt}대)")
            try:
                from src.modules.ip_cooldown_tracker import ip_cooldown_tracker
                ip_summary = ip_cooldown_tracker.get_status_summary()
                cooling_cnt = ip_summary.get("currently_cooling", 0)
                total_ips = ip_summary.get("total_tracked", 0)
                logger.info(f"🛡️  [2차 방어선 IP 현황] 24h 쿨다운 격리 중인 공인 IP: {cooling_cnt}개 / 총 기록: {total_ips}개")
            except Exception:
                pass
            logger.info("-" * 82)
            for idx, dev in enumerate(self.all_devices, 1):
                st = self.device_status[dev]
                if dev in self.busy_devices:
                    elapsed = int(time.time() - st.get("start_time", time.time()))
                    mode_tag = "🛒클릭모드" if st.get("allow_click") else "⚡탐색모드"
                    kw = st.get("keyword", "-")
                    cyc = st.get("cycle", 1)
                    logger.info(f"  [워커 #{idx}] {dev:<12} | 🏃 BUSY (주기 #{cyc} | {mode_tag} | 키워드: '{kw}' | 경과: {elapsed}s)")
                elif st.get("state") == "COOLDOWN":
                    last_res = st.get("last_result", "24h 쿨다운")
                    last_dur = st.get("last_duration", 0.0)
                    dur_str = f"({last_dur}s)" if last_dur > 0 else ""
                    logger.info(f"  [워커 #{idx}] {dev:<12} | 💤 COOLDOWN ({last_res} {dur_str} | 🔋 절전 충전 중)")
                elif st.get("state") == "FAIL_COOLDOWN":
                    last_res = st.get("last_result", "실패 쿨다운")
                    last_dur = st.get("last_duration", 0.0)
                    dur_str = f"({last_dur}s)" if last_dur > 0 else ""
                    logger.info(f"  [워커 #{idx}] {dev:<12} | ⚠️ FAIL_COOLDOWN ({last_res} {dur_str} | 🔄 큐 후순위 & 🔋 절전)")
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
        """비상 종료 시 전 단말기 앱 및 WireGuard 터널 일괄 병렬 강제 종료 (최대 1~2초 완주)"""
        def _stop_dev(dev_id):
            try:
                subprocess.run(
                    ["adb", "-s", dev_id, "shell", "am force-stop com.nhn.android.search; am force-stop com.wireguard.android"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.5
                )
                logger.info(f"  [✓ {dev_id}] 네이버 앱 & WireGuard 터널 즉시 강제 종료 완료")
            except Exception as e:
                logger.warning(f"  [! {dev_id}] 종료 명령 오류: {e}")

        if not self.all_devices:
            return

        try:
            with ThreadPoolExecutor(max_workers=max(1, len(self.all_devices))) as pool:
                list(pool.map(_stop_dev, self.all_devices))
        except (RuntimeError, Exception):
            for dev_id in self.all_devices:
                _stop_dev(dev_id)
