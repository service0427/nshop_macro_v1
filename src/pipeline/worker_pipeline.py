# -*- coding: utf-8 -*-
"""
========================================================================================
N-Shop Automation Macro Worker Pipeline (src/pipeline/worker_pipeline.py)
[Single Source of Truth] 단말기 워커 생명주기 단일 실행 엔진
========================================================================================
1. NO_TASK 안전 대기 분기 (VPN 미연결 즉시 반환)
2. Zero-Reboot 무재부팅 신원 변조 (SSAID, ADID, GPS Mock, 권한 주입)
3. WireGuard VPN 터널 활성화 및 macvlan_ip Fail-Fast 완전 검증
4. NaverMacroCore Step 1~4 UI 매크로 순차 실행
5. 클린 Teardown: 네이버 앱 종료 -> 스냅샷 저장 -> WG 터널 안전 해제 -> 결과 반환
========================================================================================
"""

import os
import time
import random
import logging
import subprocess
from typing import Dict, Any, Optional

from src.config import NAVER_PKG, PROFILE_STORAGE_DIR
from src.modules.macro_core import NaverMacroCore
from src.modules.soft_reboot_mutator import SoftRebootMutator
from src.modules.wireguard_manager import WireGuardManager
from src.modules.battery_tracker import BatteryTracker

logger = logging.getLogger("WorkerPipeline")

class DeviceWorkerPipeline:
    """단일 단말기에 대한 4단계 풀 라이프사이클 오케스트레이터"""

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.mutator = SoftRebootMutator(device_id)
        self.wg = WireGuardManager(device_id)
        self.macro = NaverMacroCore(device_id)

    def execute_task(self, task_info: Dict[str, Any], router_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        단일 작업 실행 메인 메서드
        """
        t_start = time.time()
        batt_start_info = BatteryTracker.get_battery_info(self.device_id)
        job_type = task_info.get("job_type", "WARM_AND_SCOUT")
        keyword = task_info.get("keyword")
        target_mid = str(task_info.get("mid") or task_info.get("target_code") or "0")
        allow_click = bool(task_info.get("allow_click", False))
        profile_obj = task_info.get("profile") or {}
        snapshot_path = profile_obj.get("snapshot_path") if isinstance(profile_obj, dict) else None

        # -------------------------------------------------------------
        # 0. NO_TASK 분기: 작업이 없는 단말기는 VPN을 끄고 0.5초 즉시 안전 대기
        # -------------------------------------------------------------
        batt_now = BatteryTracker.get_battery_info(self.device_id).get("level_precise")
        if job_type == "NO_TASK" or not keyword:
            logger.info(f"[{self.device_id}] [⏸️ NO_TASK] 배정된 작업 없음 -> WireGuard 터널 완전 종료 및 안전 대기")
            self.wg.deactivate_tunnel()
            return {
                "device_id": self.device_id,
                "status": "SUCCESS",
                "target_code": None,
                "keyword": None,
                "is_searched": False,
                "is_clicked": False,
                "is_exposed": False,
                "exposure_rank": None,
                "execution_sec": 0.5,
                "free_storage_mb": self.mutator.get_free_storage_mb(),
                "battery_level": round(batt_now, 2) if batt_now is not None else None,
                "snapshot_path": None,
                "error_reason": None,
                "public_ip": "NO_VPN"
            }

        client_ip = task_info.get("ip")
        priv_key = task_info.get("private_key")
        server_pubkey = router_info.get("server_public_key")
        endpoint = router_info.get("endpoint")
        expected_ip = router_info.get("macvlan_ip")

        logger.info(f"[{self.device_id}] 🚀 작업 시작 -> 유형: {job_type}, 키워드: '{keyword}', mid: {target_mid}, 클릭허용: {allow_click}")

        # -------------------------------------------------------------
        # 1. 초고속 소프트 재부팅 신원 변조 (CLICK_TARGET 시 RESTORE, WARM_AND_SCOUT 시 FRESH)
        # -------------------------------------------------------------
        profile_ssaid = profile_obj.get("ssaid") if isinstance(profile_obj, dict) else None
        profile_adid = profile_obj.get("adid") if isinstance(profile_obj, dict) else None
        profile_idfv = profile_obj.get("idfv") if isinstance(profile_obj, dict) else None

        mode = "FRESH"
        if job_type == "CLICK_TARGET" or snapshot_path:
            if snapshot_path and self.mutator.profile_exists_on_device(snapshot_path):
                mode = "RESTORE"
            elif self.mutator.profile_exists_on_device(f"{PROFILE_STORAGE_DIR}/pf_{self.device_id}_latest.tar.gz"):
                snapshot_path = f"{PROFILE_STORAGE_DIR}/pf_{self.device_id}_latest.tar.gz"
                mode = "RESTORE"

        mut_res = self.mutator.mutate_identity(
            mode=mode,
            profile_tar=snapshot_path,
            ssaid=profile_ssaid,
            adid=profile_adid,
            idfv=profile_idfv
        )
        logger.info(f"[{self.device_id}] [✓] 소프트 리셋 신원 변조 완료 ({mode} 모드 | SSAID: {mut_res.get('ssaid')})")

        # -------------------------------------------------------------
        # 1-1. 소프트 리셋 직후 시스템 프로세스 & Wi-Fi 베이스망 무결성 안정화 (버퍼링 방지)
        # -------------------------------------------------------------
        self.wg.ensure_wifi_base_healthy()
        time.sleep(1.0)  # Zygote 재시작 후 I/O 버퍼링 완화를 위한 1초 안정화 웜업 대기

        # -------------------------------------------------------------
        # 2. WireGuard 터널 활성화 및 macvlan_ip Fail-Fast 완전 검증
        # -------------------------------------------------------------
        public_ip = "UNKNOWN"
        if not (client_ip and priv_key and server_pubkey and endpoint):
            logger.error(f"[{self.device_id}] ❌ [FAIL-FAST] 필수 WireGuard 정보 누락 (IP:{client_ip}, Endpoint:{endpoint})! 매크로 진입을 즉시 차단합니다.")
            batt_fast = BatteryTracker.get_battery_info(self.device_id).get("level_precise")
            return {
                "device_id": self.device_id,
                "status": "FAILED",
                "target_code": target_mid if target_mid != "0" else None,
                "keyword": keyword,
                "is_searched": False,
                "is_clicked": False,
                "is_exposed": False,
                "exposure_rank": None,
                "execution_sec": round(time.time() - t_start, 1),
                "free_storage_mb": self.mutator.get_free_storage_mb(),
                "battery_level": round(batt_fast, 2) if batt_fast is not None else None,
                "snapshot_path": None,
                "error_reason": "MISSING_WIREGUARD_CONFIG",
                "public_ip": "MISSING_CONFIG"
            }

        wg_res = self.wg.activate_and_verify(
            client_ip, priv_key, server_pubkey, endpoint,
            expected_public_ip=expected_ip,
            max_timeout_sec=8.0
        )
        public_ip = wg_res.get("public_ip", "UNKNOWN")
        logger.info(f"[{self.device_id}] WireGuard 상태: {wg_res.get('status')} (IP: {public_ip} | Expected: {expected_ip})")
        if wg_res.get("status") != "SUCCESS":
            err_reason = wg_res.get("error_reason", "WIREGUARD_INTERNET_UNREACHABLE")
            logger.error(f"[{self.device_id}] ❌ [FAIL-FAST] WireGuard 연결/IP일치 검증 실패 ({err_reason})! 매크로 실행을 중단하고 실패 반환 처리합니다.")
            self.wg.deactivate_tunnel()
            batt_fast = BatteryTracker.get_battery_info(self.device_id).get("level_precise")
            return {
                "device_id": self.device_id,
                "status": "FAILED",
                "target_code": target_mid if target_mid != "0" else None,
                "keyword": keyword,
                "is_searched": False,
                "is_clicked": False,
                "is_exposed": False,
                "exposure_rank": None,
                "execution_sec": round(time.time() - t_start, 1),
                "free_storage_mb": self.mutator.get_free_storage_mb(),
                "battery_level": round(batt_fast, 2) if batt_fast is not None else None,
                "snapshot_path": None,
                "error_reason": err_reason,
                "public_ip": public_ip
            }

        # -------------------------------------------------------------
        # 3. NaverMacroCore Step 1~4 UI 매크로 실행
        # -------------------------------------------------------------
        is_searched = False
        is_exposed = False
        exposure_rank = None
        is_clicked = False
        error_reason = None

        try:
            # Step 1: 클린 홈 화면 기동 및 웜업
            home_ok = self.macro.launch_clean_home()
            if not home_ok:
                logger.error(f"[{self.device_id}] [❌ Step 1 실패] 클린 홈 화면 기동 실패")
                error_reason = "HOME_LAUNCH_FAILED"
            else:
                # Step 2: 검색창 진입 & ADBKeyboard 실시간 입력 & ENTER (TOP버튼 초고속 원점복귀)
                self.macro.enter_search_mode()
                is_searched = self.macro.execute_search(keyword)

                if is_searched and target_mid and target_mid != "0":
                    # [공통] 타겟 상품 카드가 실제 단말기 화면(340 <= Y <= 2260)에 보일 때까지 정밀 스크롤 안착 및 크롭 캡처
                    target_coords = self.macro.navigate_and_focus_target_card(target_mid, max_scroll_passes=12, keyword=keyword)
                    is_exposed = bool(target_coords is not None)
                    exposure_rank = 1 if is_exposed else None

                    if target_coords:
                        if allow_click:
                            # 1. [클릭 작업: allow_click=True] 타겟 상품 안전 클릭 & 상세페이지 30초 실체류 완주 (상세페이지 _click.png 스샷 저장)
                            is_clicked = self.macro.click_target_product_and_verify(target_coords, target_mid, timeout_sec=30.0, keyword=keyword)
                            if is_clicked:
                                # Step 4: 상세페이지 30초 체류 및 4~7회 랜덤 자연스러운 탐색 스크롤
                                self.macro.browse_product_detail_page(target_dwell_sec=30.0, min_scrolls=4, max_scrolls=7)
                            else:
                                logger.warning(f"[{self.device_id}] [!] 30초 내 상세페이지 진입 미확인 -> Step 4 상세 스크롤 생략 및 세션 반납")
                        else:
                            # 2. [단순 노출 작업: allow_click=False] 타겟 상품 화면 실노출 안착 확인 -> 자연스러운 시선 체류 후 종료 (클릭 안함)
                            logger.info(f"[{self.device_id}] [🎯 실노출 안착 및 영역 크롭 완료] 타겟 MID({target_mid}) 화면 중앙 포커싱 확인 -> 2초 시선 체류 후 클린 종료")
                            time.sleep(random.uniform(1.5, 2.5))
                    else:
                        logger.info(f"[{self.device_id}] [⚡ 미노출 종료] 타겟 MID({target_mid}) 검색 결과 미노출 확인 ➔ 추가 동작 없이 세션 종료")

        except Exception as e:
            logger.error(f"[{self.device_id}] 매크로 실행 중 예외 발생: {e}", exc_info=True)
            error_reason = f"EXCEPTION: {str(e)}"

        # -------------------------------------------------------------
        # 4. 클린 Teardown: 네이버 앱 종료 -> 스냅샷 저장 -> WG 터널 해제
        # -------------------------------------------------------------
        # A. 네이버 앱 프로세스 강제 종료
        subprocess.run(["adb", "-s", self.device_id, "shell", f"am force-stop {NAVER_PKG}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # B. 세션 쿠키(NNB, NAPP_DI) 추출
        session_ids = self.mutator.extract_session_identifiers()
        extracted_nnb = session_ids.get("nnb")
        extracted_napp_di = session_ids.get("napp_di")

        # C. 성공적인 검색/클릭 세션일 경우 프로필 스냅샷 저장
        final_snapshot = snapshot_path
        if is_searched:
            prof_name = profile_obj.get("profile_name") or f"pf_{self.device_id}_{int(time.time())}"
            final_snapshot = self.mutator.save_profile_snapshot(prof_name)
            # 최신 프로필 갱신 (다음 RESTORE 시 재사용)
            self.mutator.save_profile_snapshot(f"pf_{self.device_id}_latest")

        # D. WireGuard 터널 비활성화
        self.wg.deactivate_tunnel()

        exec_sec = round(time.time() - t_start, 1)
        final_status = "SUCCESS" if (is_searched and error_reason is None) else "FAILED"

        # E. 배터리 소모량 추적 및 기록 (정밀 소수점)
        batt_end_info = BatteryTracker.get_battery_info(self.device_id)
        current_batt = batt_end_info.get("level", 100)
        current_batt_precise = batt_end_info.get("level_precise", float(current_batt))
        start_batt_precise = batt_start_info.get("level_precise", current_batt_precise)
        charge_mah = batt_end_info.get("charge_mah")

        BatteryTracker.log_task_cycle(
            device_id=self.device_id,
            job_type="CLICK" if allow_click else "EXPLORE",
            keyword=keyword or "-",
            batt_start=start_batt_precise,
            temp_start=batt_start_info.get("temp", 25.0),
            batt_end=current_batt_precise,
            temp_end=batt_end_info.get("temp", 25.0),
            duration_sec=exec_sec,
            status=final_status,
            charge_mah_end=charge_mah
        )

        logger.info(f"[{self.device_id}] 🏁 작업 완료 -> 상태: {final_status}, 노출: {is_exposed} (순위: {exposure_rank}), 클릭: {is_clicked}, 소요: {exec_sec}s | NNB: {extracted_nnb}, NAPP_DI: {extracted_napp_di} | 배터리: {current_batt}% ({current_batt_precise:.2f}%)")

        return {
            "device_id": self.device_id,
            "status": final_status,
            "target_code": target_mid if target_mid != "0" else None,
            "keyword": keyword,
            "is_searched": is_searched,
            "is_clicked": is_clicked,
            "is_exposed": is_exposed,
            "exposure_rank": exposure_rank,
            "execution_sec": exec_sec,
            "free_storage_mb": self.mutator.get_free_storage_mb(),
            "snapshot_path": final_snapshot,
            "ssaid": mut_res.get("ssaid"),
            "adid": mut_res.get("adid"),
            "nnb": extracted_nnb,
            "napp_di": extracted_napp_di,
            "gps_lat": mut_res.get("gps_lat"),
            "gps_lng": mut_res.get("gps_lng"),
            "latitude": mut_res.get("gps_lat"),
            "longitude": mut_res.get("gps_lng"),
            "battery_level": round(current_batt_precise, 2),
            "error_reason": error_reason,
            "public_ip": public_ip
        }
