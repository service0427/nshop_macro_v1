# -*- coding: utf-8 -*-
"""
========================================================================================
[모듈명] 24/7 동적 디스패처 & 워커 스케줄러 (DynamicDaemonScheduler)
(src/scheduler/daemon_scheduler.py)
========================================================================================
- 기능:
    1. 10초 주기 유휴 단말기 풀 감지
    2. 중앙 관제 서버(aaa4.kr) 실시간 작업 일괄 할당 수신
    3. NO_TASK 및 IP 미할당 세션 즉시 안전 반납
    4. 단말기간 5초 시차(Stagger) 병렬 디스패치 및 ThreadPool 워커 구동
    5. 작업 완료/실패 실시간 서버 반납 및 통계 집계
    6. Ctrl+C 비상 시 잔여 세션 CANCELLED 안전 일괄 반납
========================================================================================
"""

import os
import sys
import time
import atexit
import logging
import threading
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

from src.modules.task_api_client import TaskApiClient
from src.pipeline.worker_pipeline import DeviceWorkerPipeline
from src.scheduler.device_pool import DevicePool
from src.scheduler.daemon_controller import DaemonController
from src.modules.battery_tracker import BatteryTracker

logger = logging.getLogger("DaemonScheduler")


class DynamicDaemonScheduler:
    """동적 가용 단말기 풀 및 10초 주기 연속 디스패처"""

    def __init__(
        self,
        device_ids: Optional[List[str]] = None,
        max_workers: int = 5,
        loop_interval_sec: float = 10.0,
        stagger_sec: float = 5.0,
        max_loops: int = 0,
        max_tasks: int = 0
    ):
        self.device_pool = DevicePool(device_ids=device_ids, max_workers=max_workers)
        self.max_workers = self.device_pool.max_workers
        self.loop_interval_sec = loop_interval_sec
        self.stagger_sec = stagger_sec
        self.max_loops = max_loops
        self.max_tasks = max_tasks

        self.client = TaskApiClient()
        self.controller = DaemonController(
            on_emergency_exit=self.emergency_cleanup
        )

        self.active_alloc_sessions: Dict[str, Dict[str, Any]] = {}
        self.active_alloc_lock = threading.Lock()

        # OS 비정상 종료/예외 시 프로세스 퇴장 훅 등록
        atexit.register(self.emergency_cleanup)

        self.stats = {
            "total_tasks": 0,
            "total_success": 0,
            "total_exposed": 0,
            "total_clicked": 0
        }
        self.current_cycle = 0
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)

    def print_current_status(self):
        """현재 워커 상태 출력 요청 콜백"""
        idle_devs = self.device_pool.get_idle_devices()
        self.device_pool.print_status_board(self.current_cycle, idle_devs)

    def emergency_cleanup(self):
        """비상 종료 시 전 단말기 강제 종료 및 잔여 세션 CANCELLED 반납"""
        logger.warning("\n" + "=" * 82)
        logger.warning(" [🛑 비상 종료 감지] 전 단말기 앱 강제 종료 및 잔여 세션 안전 반납 수행 중...")
        logger.warning("=" * 82)

        # 1. 단말기 앱 및 VPN 일괄 종료
        self.device_pool.emergency_cleanup_all()

        # 2. 진행 중이던 미반납 세션들 일괄 CANCELLED 반납
        with self.active_alloc_lock:
            for alloc_id, sess_info in list(self.active_alloc_sessions.items()):
                cancel_results = []
                for t in sess_info.get("tasks", []):
                    dev_id = t.get("device_id")
                    batt = BatteryTracker.get_battery_info(dev_id).get("level_precise") if dev_id else None
                    cancel_results.append({
                        "device_id": dev_id,
                        "status": "CANCELLED",
                        "target_code": t.get("mid"),
                        "keyword": t.get("keyword"),
                        "is_searched": False,
                        "is_clicked": False,
                        "is_exposed": False,
                        "exposure_rank": None,
                        "execution_sec": 0.1,
                        "battery_level": round(batt, 2) if batt is not None else None,
                        "error_reason": "USER_INTERRUPTED_CTRL_C"
                    })
                if cancel_results:
                    logger.info(f"[*] 세션 [{alloc_id}] 잔여 작업 {len(cancel_results)}건 CANCELLED 안전 반납 전송...")
                    self.client.release_tasks(alloc_id, cancel_results)
            self.active_alloc_sessions.clear()

        self.controller.release_lock()
        logger.info(" [✓ 비상 종료 완료] 모든 프로세스 및 세션이 안전하게 정리되었습니다. 종료합니다.\n")
        os._exit(0)

    def _worker_wrapper(self, device_id: str, task_info: dict, router_info: dict, alloc_id: str, cycle_id: int):
        """백그라운드 스레드에서 파이프라인 실행 후 세션 반납 및 상태 복구"""
        t_worker_start = time.time()
        res = {"device_id": device_id, "status": "FAILED"}
        try:
            pipeline = DeviceWorkerPipeline(device_id)
            res = pipeline.execute_task(task_info, router_info)

            # 서버에 결과 반환
            if alloc_id:
                self.client.release_tasks(alloc_id, [res])
                with self.active_alloc_lock:
                    if alloc_id in self.active_alloc_sessions:
                        self.active_alloc_sessions[alloc_id]["tasks"] = [
                            t for t in self.active_alloc_sessions[alloc_id]["tasks"] if t.get("device_id") != device_id
                        ]
                        if not self.active_alloc_sessions[alloc_id]["tasks"]:
                            del self.active_alloc_sessions[alloc_id]

            # 통계 집계
            with self.device_pool.lock:
                self.stats["total_tasks"] += 1
                if res.get("status") == "SUCCESS":
                    self.stats["total_success"] += 1
                if res.get("is_exposed"):
                    self.stats["total_exposed"] += 1
                if res.get("is_clicked"):
                    self.stats["total_clicked"] += 1

        except Exception as e:
            logger.error(f"[주기 #{cycle_id} | {device_id}] 워커 스레드 예외 발생: {e}", exc_info=True)
            if alloc_id:
                batt_err = BatteryTracker.get_battery_info(device_id).get("level_precise")
                self.client.release_tasks(alloc_id, [{
                    "device_id": device_id,
                    "status": "FAILED",
                    "battery_level": round(batt_err, 2) if batt_err is not None else None,
                    "error_reason": f"EXCEPTION: {str(e)}"
                }])
        finally:
            dur = round(time.time() - t_worker_start, 1)
            status_str = res.get("status", "FAILED")
            self.device_pool.mark_idle(device_id, cycle_id, status_str, dur)
            logger.info(f"[주기 #{cycle_id} | {device_id}] [🔄 IDLE 전환] 작업 완료 ({dur}초 소요) ➔ 다음 10초 스케줄러에서 즉시 재할당 대기")

    def run_cycle(self):
        """10초마다 1회 실행되는 주기적 디스패치 루프"""
        self.current_cycle += 1
        current_cycle = self.current_cycle

        # 1. 유휴 단말기 확인
        idle_devs = self.device_pool.get_idle_devices()

        # 0. 100주기마다 1회 서버 DB 우선 프로필 동기화 및 단말기 불필요 파일 정리
        if current_cycle % 100 == 1 and idle_devs:
            for dev in idle_devs:
                try:
                    from src.modules.soft_reboot_mutator import SoftRebootMutator
                    mut = SoftRebootMutator(dev)
                    sync_res = mut.sync_profiles_with_server()
                    if sync_res.get("cleaned_count", 0) > 0:
                        logger.info(f"[{dev}] 🧹 [DB 싱크] 서버 기준 불필요 파일 {sync_res['cleaned_count']}개 자동 정리 완료: {sync_res['cleaned_files']}")
                except Exception:
                    pass

        self.device_pool.print_status_board(current_cycle, idle_devs)

        if not idle_devs:
            logger.info(f"[*] ⏸️  [PASS] 모든 디바이스가 현재 작업 중입니다 ({len(self.device_pool.all_devices)}/{len(self.device_pool.all_devices)}대). {self.loop_interval_sec}초 후 재확인합니다.\n")
            return

        # 2. 서버에 유휴 단말기 일괄 할당 요청
        logger.info(f"[*] 📡 이번 주기 요청 대상 (유휴 {len(idle_devs)}대: {idle_devs}) 작업 할당 요청 중...")
        alloc_res = self.client.allocate_tasks(idle_devs)
        if not alloc_res:
            logger.warning("[*] ⏸️  서버 응답 없음 (None). 다음 주기에 재요청합니다.\n")
            return

        alloc_id = alloc_res.get("alloc_id")
        tasks = alloc_res.get("tasks", [])
        router_obj = alloc_res.get("router") or {}
        routers_map = alloc_res.get("routers") or {}

        if not tasks:
            logger.info("[*] ⏸️  서버에 가용 대기 작업이 없습니다 (빈 응답). 다음 주기에 재요청합니다.\n")
            return

        # 3. 비상 정리를 위해 활성 세션 등록
        with self.active_alloc_lock:
            self.active_alloc_sessions[alloc_id] = {
                "tasks": list(tasks),
                "devices": list(idle_devs)
            }

        # 4. 수신된 작업들을 각 단말기 스레드로 투입 (시차 5초 적용)
        dispatched_count = 0
        for task_info in tasks:
            dev_id = task_info.get("device_id")
            if not dev_id or dev_id not in idle_devs:
                continue

            job_type = task_info.get("job_type") or task_info.get("type", "SEARCH_EXPOSURE")
            router_code = task_info.get("router_code")
            router_info = router_obj if router_obj else routers_map.get(router_code, {})
            keyword = task_info.get("keyword")
            client_ip = task_info.get("ip")
            allow_click = task_info.get("allow_click", False)

            # NO_TASK이거나 IP가 없는 경우: 즉시 안전 반납 및 IDLE 유지
            if not keyword or not client_ip:
                logger.info(f"[주기 #{current_cycle} | {dev_id}] [⏸️ NO_TASK / IP 미할당] -> 안전 반납 후 다음 10초 루프에서 즉시 재할당 대기")
                if alloc_id:
                    self.client.release_tasks(alloc_id, [{
                        "device_id": dev_id,
                        "status": "SUCCESS",
                        "is_searched": False,
                        "execution_sec": 0.1,
                        "public_ip": "NO_TASK"
                    }])
                self.device_pool.device_status[dev_id]["last_result"] = f"주기 #{current_cycle} NO_TASK"
                continue

            # 유효 작업인 경우: BUSY 전환 후 스레드풀 투입 (5초 시차 적용)
            self.device_pool.mark_busy(dev_id, current_cycle, job_type, keyword, allow_click)

            if dispatched_count > 0 and self.stagger_sec > 0:
                logger.info(f"[*] ⏱️  다음 단말기({dev_id}) {self.stagger_sec}초 간격 시차 투입 대기...")
                time.sleep(self.stagger_sec)

            job_desc = "🛒클릭" if allow_click else "⚡탐색"
            logger.info(f"[주기 #{current_cycle} | {dev_id}] 🚀 워커 투입 -> [{job_desc}] 키워드: '{keyword}', 유형: {job_type}")
            self.executor.submit(self._worker_wrapper, dev_id, task_info, router_info, alloc_id, current_cycle)
            dispatched_count += 1

    def start(self):
        """스케줄러 메인 루프 가동 (24/7 무인 자동 디스패치)"""
        self.controller.acquire_lock()
        self.controller.setup_signal_handlers()

        all_devs = self.device_pool.all_devices
        logger.info("==========================================================================")
        logger.info(f" 🚀 NShop Macro 24/7 동적 스케줄러 데몬 가동")
        logger.info(f"    - 활성 워커 슬롯: {len(all_devs)}개 (단말기: {all_devs})")
        logger.info(f"    - 스케줄러 폴링 간격: {self.loop_interval_sec}초 | 단말기 간 시차: {self.stagger_sec}초")
        if self.max_loops > 0:
            logger.info(f"    - 최대 루프(주기) 제한: {self.max_loops}회")
        if self.max_tasks > 0:
            logger.info(f"    - 최대 작업(건수) 제한: {self.max_tasks}건")
        logger.info("==========================================================================")

        while self.controller.running:
            try:
                self.run_cycle()
            except Exception as e:
                logger.error(f"[!] 스케줄러 주기 실행 중 예외 발생: {e}", exc_info=True)

            # 루프 제한 또는 작업 수 제한 도달 여부 검사
            if self.max_loops > 0 and self.current_cycle >= self.max_loops:
                logger.info(f"\n[✓] 지정된 최대 루프 ({self.max_loops}회) 실행 완료. 잔여 워커 완료를 대기합니다...")
                break

            if self.max_tasks > 0:
                with self.device_pool.lock:
                    if self.stats["total_tasks"] >= self.max_tasks:
                        logger.info(f"\n[✓] 지정된 최대 작업 수 ({self.max_tasks}건) 처리 완료. 잔여 워커 완료를 대기합니다...")
                        break

            # 10초 대기 (1초 단위 종료 시그널 감지)
            for _ in range(int(self.loop_interval_sec)):
                if not self.controller.running:
                    break
                time.sleep(1.0)

        # 잔여 실행 중 워커 대기
        self.executor.shutdown(wait=True)
        self.controller.release_lock()

        logger.info("==========================================================================")
        logger.info(f" 🏁 스케줄러 지정 작업 완료 요약")
        with self.device_pool.lock:
            logger.info(f"    - 총 완료 작업: {self.stats['total_tasks']}건 (성공: {self.stats['total_success']}건)")
            logger.info(f"    - 노출: {self.stats['total_exposed']}건 / 클릭: {self.stats['total_clicked']}건")
        logger.info("==========================================================================")
