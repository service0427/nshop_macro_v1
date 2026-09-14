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
from src.config import DEVICE_COOLDOWN_SEC, DEVICE_FAIL_COOLDOWN_SEC, DISPATCH_INTERVAL_SEC, MAX_DISPATCH_BATCH

logger = logging.getLogger("DaemonScheduler")


class DynamicDaemonScheduler:
    """동적 가용 단말기 풀 및 30분 시차 순차 롤링 디스패처 (24h 디바이스 격리)"""

    def __init__(
        self,
        device_ids: Optional[List[str]] = None,
        exclude_device_ids: Optional[List[str]] = None,
        max_workers: int = 0,
        loop_interval_sec: float = 30.0,
        stagger_sec: float = 1.0,
        max_loops: int = 0,
        max_tasks: int = 0,
        until_time: Optional[str] = None,
        device_cooldown_sec: float = DEVICE_COOLDOWN_SEC,
        device_fail_cooldown_sec: float = DEVICE_FAIL_COOLDOWN_SEC,
        dispatch_interval_sec: float = DISPATCH_INTERVAL_SEC,
        batch_size: int = MAX_DISPATCH_BATCH,
        max_ip_retries: int = 5
    ):
        self.device_pool = DevicePool(
            device_ids=device_ids,
            exclude_device_ids=exclude_device_ids,
            max_workers=max_workers,
            device_cooldown_sec=device_cooldown_sec,
            device_fail_cooldown_sec=device_fail_cooldown_sec
        )
        self.max_workers = self.device_pool.max_workers
        self.loop_interval_sec = loop_interval_sec
        self.stagger_sec = stagger_sec
        self.max_loops = max_loops
        self.max_tasks = max_tasks
        self.until_time = until_time
        self.dispatch_interval_sec = dispatch_interval_sec
        self.batch_size = batch_size
        self.last_dispatch_time: float = 0.0
        self.slot_ip_retry_count: int = 0
        self.max_slot_ip_retries: int = max_ip_retries
        self.last_conflict_alloc_id: str = ""

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

    @staticmethod
    def _is_detailad_task(task_info: Dict[str, Any]) -> bool:
        """할당된 태스크가 '디테일애드' 벤치마크 상품인지 data.md 기준으로 엄격히 검증"""
        DETAILAD_MIDS = {
            "91246992080", "91229936175", "91230953977", "91246920570", "91246933437",
            "91246946583", "91246954360", "91246999969", "91247010626", "91247019083"
        }
        DATA_MD_PRODUCT_IDS = {
            "13685424932", "13686442734", "13702409252", "13702422117", "13702435265",
            "13702443042", "13702480762", "13702488651", "13702499308", "13702507765"
        }
        store_name = str(task_info.get("store_name", "")).strip()
        keyword = str(task_info.get("keyword", "")).strip()
        mid = str(task_info.get("mid") or task_info.get("target_code") or "").strip()
        product_title = str(task_info.get("product_title", "")).strip()

        if "디테일애드" in store_name or "디테일애드" in keyword or "디테일애드" in product_title:
            return True
        if mid in DETAILAD_MIDS or any(pid in mid for pid in DATA_MD_PRODUCT_IDS):
            return True
        return False

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
        logger.info(" [✓ 비상 종료 완료] 모든 프로세스 및 세션이 안전하게 정리되었습니다.\n")

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
            is_clicked = bool(res.get("is_clicked", False))
            is_exposed = bool(res.get("is_exposed", False))
            allow_click = bool(task_info.get("allow_click", False))
            error_reason = res.get("error_reason")

            self.device_pool.mark_idle(
                device_id=device_id,
                cycle_num=cycle_id,
                status_str=status_str,
                duration=dur,
                is_clicked=is_clicked,
                allow_click=allow_click,
                error_reason=error_reason
            )
            is_click_success = (status_str == "SUCCESS") and (is_clicked if allow_click else True)
            interval_m = round(self.dispatch_interval_sec / 60, 1)

            is_infra_or_ip_fail = (
                (error_reason and any(k in error_reason for k in ["IP_COOLDOWN", "TUNNEL_DOWN", "WIFI_DISCONNECTED"]))
                or not res.get("is_searched", False)
            )

            if is_click_success:
                # 🎯 [성공 기준 쿨타임] 성공 시에만 60분 스토어 쿨타임 시작 & 슬롯 IP 재시도 카운트 초기화
                self.last_dispatch_time = time.time()
                self.slot_ip_retry_count = 0
                logger.info(
                    f"[주기 #{cycle_id} | {device_id}] [💤 24H 쿨다운 진입 & 🎉 성공 쿨타임 시작] "
                    f"유효타 클릭 성공 ({dur}초 소요) ➔ 단말기 24시간 휴식 & 다음 타임까지 {interval_m}분 스토어 쿨다운 시작"
                )
            elif is_infra_or_ip_fail:
                # 🛑 [미사용 IP / 터널 불통 ➔ 미사용 IP/라우터 재호출 (최대 5회)]
                with self.active_alloc_lock:
                    if self.last_conflict_alloc_id != alloc_id:
                        self.last_conflict_alloc_id = alloc_id
                        self.slot_ip_retry_count += 1
                if self.slot_ip_retry_count < self.max_slot_ip_retries:
                    self.last_dispatch_time = 0.0
                    logger.warning(
                        f"[주기 #{cycle_id} | {device_id}] [🛑 미사용/인프라 재시도: {error_reason or '검색전단 중단'}] "
                        f"➔ IP/스토어 미소모 확인! 클린 IP/정상 라우터 재호출 시도 ({self.slot_ip_retry_count}/{self.max_slot_ip_retries}회) "
                        f"(다음 주기에 가용 단말기 즉시 투입)"
                    )
                else:
                    # 5회 요청에도 나오지 않으면 그 타임은 지나간다
                    self.last_dispatch_time = time.time()
                    self.slot_ip_retry_count = 0
                    logger.warning(
                        f"[주기 #{cycle_id} | {device_id}] [⏭️ 5회 연속 미사용/불통 차단] "
                        f"➔ 5회 요청에도 정상 IP/라우터가 배정되지 않음! 이번 타임 슬롯을 통과합니다 (다음 {interval_m}분 쿨다운 대기 진입)"
                    )
            else:
                # ⚠️ [실제 검색 시도 후 미노출이거나 기타 오류인 경우: 재호출 없이 해당 타임 슬롯 종료 및 쿨타임 진행]
                self.last_dispatch_time = time.time()
                self.slot_ip_retry_count = 0
                fail_cause = "클릭 미완수(미노출/전환실패)" if (allow_click and not is_clicked) else (error_reason or "작업 실패")
                fail_h = round(self.device_pool.device_fail_cooldown_sec / 3600, 1)
                fail_m = round(self.device_pool.device_fail_cooldown_sec / 60, 1)
                time_str = f"{fail_h}시간" if self.device_pool.device_fail_cooldown_sec >= 3600 else f"{fail_m}분"
                logger.warning(
                    f"[주기 #{cycle_id} | {device_id}] [⚠️ {fail_cause}] "
                    f"➔ 이번 타임 슬롯 종료 (재호출 없음, 다음 {interval_m}분 쿨다운 대기) & 단말기 {time_str} 후순위 회전"
                )

    def run_cycle(self):
        """10초마다 1회 실행되는 주기적 디스패치 루프"""
        self.current_cycle += 1
        current_cycle = self.current_cycle

        # 1. 유휴 단말기 확인 (1, 11, 21, 31... 회차에만 ADB 실시간 스캔을 수행하여 풀 흔들림 방지)
        do_refresh = (current_cycle % 10 == 1)
        idle_devs = self.device_pool.get_idle_devices(do_refresh=do_refresh)

        # 0. 100주기마다 1회 서버 DB 우선 프로필 동기화 및 pm clear 딥클린 (비차단 안전 실행)
        if current_cycle > 0 and current_cycle % 100 == 0 and idle_devs:
            for dev in list(idle_devs):
                try:
                    from src.modules.soft_reboot_mutator import SoftRebootMutator
                    mut = SoftRebootMutator(dev)
                    sync_res = mut.sync_profiles_with_server()
                    if sync_res.get("cleaned_count", 0) > 0:
                        logger.info(f"[{dev}] 🧹 [DB 싱크] 서버 기준 불필요 파일 {sync_res['cleaned_count']}개 자동 정리 완료: {sync_res['cleaned_files']}")
                    mut.execute_pm_clear_maintenance()
                    logger.info(f"[{dev}] 🧼 [100주기 정기 유지보수] pm clear 딥클린 및 캐시 누적 초기화 완료")
                except Exception as e:
                    logger.warning(f"[{dev}] 100주기 정기 유지보수 중 예외 발생: {e}")

        self.device_pool.print_status_board(current_cycle, idle_devs)

        # 0. 현재 작업 중인 단말기가 있으면 완료까지 대기 (동시 실행 방지)
        if len(self.device_pool.busy_devices) >= self.batch_size:
            logger.info(f"[*] ⏸️  현재 작업 중인 단말기({list(self.device_pool.busy_devices)})가 있습니다. 작업 완료를 대기합니다...\n")
            return

        # 1. 가용 유휴 단말기 검사
        if not idle_devs:
            logger.info(f"[*] ⏸️  가용 유휴 단말기가 없습니다 (모든 단말기 작업 중 또는 24h 쿨다운 대기). {self.loop_interval_sec}초 후 재확인합니다.\n")
            return

        # 2. 롤링 인터벌 검사 (성공 기준 쿨타임 경과 여부)
        if self.last_dispatch_time > 0 and self.dispatch_interval_sec > 0:
            elapsed_since = time.time() - self.last_dispatch_time
            if elapsed_since < self.dispatch_interval_sec:
                remain_sec = int(self.dispatch_interval_sec - elapsed_since)
                remain_m = round(remain_sec / 60, 1)
                logger.info(f"[*] ⏱️  [롤링 대기] 다음 단말기 투입까지 {remain_m}분({remain_sec}초) 남음 (가용 대기 단말기: {len(idle_devs)}대)\n")
                return
            else:
                # 쿨타임 만료 ➔ 새로운 슬롯 시작! IP 재시도 카운트 초기화
                self.slot_ip_retry_count = 0

        # 3. 롤링 주기마다 1대씩(batch_size)만 선택하여 중앙 API에 할당 요청
        target_devs = idle_devs[:self.batch_size]
        interval_m_desc = round(self.dispatch_interval_sec / 60, 1)
        logger.info(f"[*] 📡 {interval_m_desc}분 롤링 타겟 단말기 {len(target_devs)}대 즉시 할당 요청 중 (단말기: {target_devs} / 가용 대기: {len(idle_devs)}대)...")
        alloc_res = self.client.allocate_tasks(target_devs)
        if not alloc_res:
            if getattr(self.client, "last_wait_info", None):
                info = self.client.last_wait_info
                sub_disp = f"/{info.get('sub_code')}" if info.get("sub_code") else ""
                logger.info(f"[*] ⏸️  서버 작업 대기 중: [{info.get('code')}{sub_disp}] {info.get('message')} (다음 {self.loop_interval_sec}초 주기에 재확인)\n")
            else:
                logger.warning("[*] ⏸️  서버 응답 없음 (None). 다음 주기에 재요청합니다.\n")
            return

        alloc_id = alloc_res.get("alloc_id")
        tasks = alloc_res.get("tasks", [])
        router_obj = alloc_res.get("router") or {}
        routers_map = alloc_res.get("routers") or {}

        if not tasks:
            logger.info("[*] ⏸️  서버에 가용 대기 작업이 없습니다 (빈 응답). 다음 주기에 재요청합니다.\n")
            return

        # [🛡️ 디테일애드 필수 포함 재검수 가드 (사용자 절대 철칙)]
        # "키워드 요청햇을때 '디테일애드' 상품이 없으면 중지해라. 모니터링 가능한 스토어는 디테일애드뿐이므로 타업체만 있으면 무의미"
        valid_tasks = [t for t in tasks if t.get("job_type") != "NO_TASK" and t.get("keyword") and t.get("ip")]
        has_detailad = any(self._is_detailad_task(t) for t in valid_tasks)
        if valid_tasks and not has_detailad:
            logger.error(f"[주기 #{current_cycle}] 🚨 [디테일애드 누락 긴급 차단] 할당된 {len(valid_tasks)}개 유효 작업 중 '디테일애드' 검증 상품이 1건도 없습니다!")
            logger.error(f"  - 수신된 스토어 목록: {[t.get('store_name') for t in valid_tasks]}")
            logger.error(f"  - 수신된 키워드 목록: {[t.get('keyword') for t in valid_tasks]}")
            logger.error(f"  - 타업체 단독 실행 방지 원칙에 따라 세션을 즉시 전원 CANCELLED 반납하고 해당 슬롯을 안전 종료합니다.")
            if alloc_id:
                cancel_payload = [{
                    "device_id": t.get("device_id"),
                    "status": "FAILED",
                    "error_reason": "MISSING_DETAILAD_ANCHOR_STORE",
                    "is_searched": False,
                    "is_clicked": False,
                    "is_exposed": False,
                    "execution_sec": 0.1
                } for t in tasks]
                self.client.release_tasks(alloc_id, cancel_payload)
            self.last_dispatch_time = time.time()
            return

        if valid_tasks and has_detailad:
            detailad_task = next(t for t in valid_tasks if self._is_detailad_task(t))
            logger.info(
                f"[주기 #{current_cycle}] [✓ 디테일애드 검증 통과] 1:N 배정 내 디테일애드 기준 상품 확인 완료! "
                f"(타겟: '{detailad_task.get('product_title')}', 키워드: '{detailad_task.get('keyword')}', 전체 유효작업: {len(valid_tasks)}개)"
            )

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

            # NO_TASK이거나 IP/키워드가 없는 경우: 즉시 안전 반납 및 IDLE 유지
            if not keyword or not client_ip or job_type == "NO_TASK":
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

        if dispatched_count > 0:
            logger.info(f"[*] 🚀 [단말기 투입 완료] 단말기 {dispatched_count}대 투입 완료 (작업 실행 및 결과 판정 대기 중...)\n")

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
        logger.info(f"    - 디바이스 성공 쿨타임: {round(self.device_pool.device_cooldown_sec / 3600, 1)}시간 (단말기당 24시간 내 1회만 투입)")
        logger.info(f"    - 디바이스 실패 쿨타임: {round(self.device_pool.device_fail_cooldown_sec / 3600, 1)}시간 (실패/클릭미완수 시 큐 최후순위 회전 및 격리)")
        logger.info(f"    - 순차 롤링 정책: {round(self.dispatch_interval_sec / 60, 1)}분마다 1대씩 순차 투입 (배치 크기: {self.batch_size}대)")
        if self.until_time:
            logger.info(f"    - 자동 종료 목표 시각: {self.until_time}")
        logger.info("==========================================================================")

        while self.controller.running:
            if self.until_time:
                now_hm = time.strftime("%H:%M")
                if now_hm >= self.until_time:
                    logger.info(f"\n[✓] ⏰ 지정된 자동 종료 시각({self.until_time}) 도달 (현재: {now_hm}). 잔여 워커 완료를 대기합니다...")
                    break

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

            # 모든 등록 단말기 1회 클릭 성공(24h 쿨다운) 완료 시 스케줄러 자동 종료
            if self.device_pool.is_all_devices_completed():
                logger.info(f"\n[🎉 전 단말기 목표 완수] 총 {len(self.device_pool.all_devices)}대 모든 단말기의 금일 1회 유효타 완료! 스케줄러를 정상 종료합니다...")
                break

            # 10초 대기 (1초 단위 종료 시그널 감지)
            for _ in range(int(self.loop_interval_sec)):
                if not self.controller.running:
                    break
                time.sleep(1.0)

        # 잔여 실행 중 워커 대기
        self.executor.shutdown(wait=True)
        self.controller.release_lock()
        try:
            atexit.unregister(self.emergency_cleanup)
        except Exception:
            pass

        is_all_done = self.device_pool.is_all_devices_completed()
        is_time_up = bool(self.until_time and time.strftime("%H:%M") >= self.until_time)
        if is_all_done or is_time_up:
            logger.info("[✓] 목표 달성/시간 도달로 PM2 자동 재시작 방지를 위해 nshop-macro-daemon 중지 명령을 전송합니다.")
            os.system("pm2 stop nshop-macro-daemon &")

        logger.info("==========================================================================")
        logger.info(f" 🏁 스케줄러 지정 작업 완료 요약")
        with self.device_pool.lock:
            logger.info(f"    - 총 완료 작업: {self.stats['total_tasks']}건 (성공: {self.stats['total_success']}건)")
            logger.info(f"    - 노출: {self.stats['total_exposed']}건 / 클릭: {self.stats['total_clicked']}건")
        logger.info("==========================================================================")
