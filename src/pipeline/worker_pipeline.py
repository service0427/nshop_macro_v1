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

----------------------------------------------------------------------------------------
[수정 및 변경 이력 (Revision History)]
----------------------------------------------------------------------------------------
- 2026-09-05:
    * [코드 가독성 개선 및 복잡도 축소] 8단계에 달하던 if-else 중첩 계단(Arrow Anti-pattern)을
      `_run_ui_macro` Guard Clause(Early Exit) 패턴으로 전면 리팩토링.
    * 실패 시 조기 반환(Fail-Fast)하여 코드 depth를 2단계로 평탄화.
========================================================================================
"""

import os
import time
import random
import logging
import subprocess
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

from src.config import NAVER_PKG, PROFILE_STORAGE_DIR
from src.modules.macro_core import NaverMacroCore
from src.modules.soft_reboot_mutator import SoftRebootMutator
from src.modules.wireguard_manager import WireGuardManager
from src.modules.battery_tracker import BatteryTracker
from src.modules.anti_detection_guardian import AntiDetectionGuardian

logger = logging.getLogger("WorkerPipeline")

class DeviceWorkerPipeline:
    """단일 단말기에 대한 4단계 풀 라이프사이클 오케스트레이터"""

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.mutator = SoftRebootMutator(device_id)
        self.wg = WireGuardManager(device_id)
        self.macro = NaverMacroCore(device_id)
        self.guardian = AntiDetectionGuardian(device_id)

    def _run_ui_macro(
        self,
        keyword: str,
        target_mid: Optional[str],
        allow_click: bool
    ) -> Tuple[bool, bool, Optional[int], bool, Optional[str]]:
        """
        Step 1~4 UI 매크로 순차 실행 (Guard Clause 패턴 적용으로 중첩 들여쓰기 전면 제거)
        반환값: (is_searched, is_exposed, exposure_rank, is_clicked, error_reason)
        """
        from src.config import SEARCH_MODE

        # -------------------------------------------------------------
        # [Day 1: Intent 직접 진입 모드] vs [Day 0: 메인 홈 타이핑 모드]
        # -------------------------------------------------------------
        if SEARCH_MODE == "INTENT_DIRECT":
            logger.info(f"[{self.device_id}] 🎯 [SEARCH_MODE: INTENT_DIRECT] 메인 홈/입력창 건너뛰고 Intent 다이렉트 검색 실행")
            if not self.macro.execute_intent_search(keyword):
                logger.error(f"[{self.device_id}] [❌ Intent 검색 실패] 검색 결과 로딩 최종 실패 ➔ 작업 중단")
                return False, False, None, False, "SEARCH_RESULTS_NOT_LOADED"
            is_searched = True
        else:
            # Step 1: 클린 홈 화면 기동 및 웜업
            if not self.macro.launch_clean_home():
                logger.error(f"[{self.device_id}] [❌ Step 1 실패] 클린 홈 화면 기동 실패")
                return False, False, None, False, "HOME_LAUNCH_FAILED"

            # Step 2-1: 검색창 진입 & ADBKeyboard 실시간 입력 준비
            if not self.macro.enter_search_mode():
                logger.warning(f"[{self.device_id}] [⚠️ Step 2-1 알림] UI 검색창 진입 지연 감지 -> Step 2-2에서 Intent 자동 복구 연계")

            # Step 2-2: 검색어 입력 및 엔터 실행 (실패 시 Intent 다이렉트 검색 Fallback 100% 보장)
            if not self.macro.execute_search(keyword):
                logger.error(f"[{self.device_id}] [❌ Step 2-2 실패] 검색 결과 로딩 최종 실패 ➔ 작업 중단")
                return False, False, None, False, "SEARCH_RESULTS_NOT_LOADED"
            is_searched = True

        # Step 2-3: 타겟 상품 카드 탐색 및 화면 중앙 포커싱
        target_coords = None
        is_exposed = False
        exposure_rank = None

        if target_mid and target_mid != "0":
            target_coords = self.macro.navigate_and_focus_target_card(
                target_mid, max_scroll_passes=16, keyword=keyword
            )
            is_exposed = bool(target_coords is not None)
            exposure_rank = 1 if is_exposed else None

        if not target_coords:
            logger.info(f"[{self.device_id}] [⚡ 미노출 종료] 타겟 MID({target_mid}) 검색 결과 미노출 확인 ➔ 추가 동작 없이 세션 종료")
            return True, is_exposed, exposure_rank, False, None

        # Step 3: 단순 노출 모드 (allow_click=False) 분기
        if not allow_click:
            logger.info(f"[{self.device_id}] [🎯 실노출 안착 & click_before 저장 완료] 타겟 MID({target_mid}) 화면 중앙 포커싱 확인 -> 2초 시선 체류 후 클린 종료 (click_after 없음)")
            time.sleep(random.uniform(1.5, 2.5))
            return True, is_exposed, exposure_rank, False, None

        # Step 4: 클릭 작업 (allow_click=True) 및 상세페이지 체류/탐색
        is_clicked = self.macro.click_target_product_and_verify(
            target_coords, target_mid, timeout_sec=30.0, keyword=keyword
        )
        if not is_clicked:
            logger.warning(f"[{self.device_id}] [!] 30초 내 상세페이지 진입 미확인 -> Step 4 상세 스크롤 생략 및 세션 반납")
            return True, is_exposed, exposure_rank, False, None

        # 상세페이지 완전 로딩 후 25~45초 랜덤 휴먼 체류 및 고도화 탐색 스크롤
        dwell_sec = round(random.uniform(25.0, 45.0), 1)
        scroll_cnt = random.randint(4, 7)
        self.macro.browse_product_detail_page(
            target_dwell_sec=dwell_sec,
            min_scrolls=4,
            max_scrolls=scroll_cnt,
            load_timeout_sec=30.0
        )
        return True, is_exposed, exposure_rank, True, None

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
        # 1. 초고속 소프트 재부팅 신원 변조 (profile_id > 0 이고 로컬 파일 존재 시 RESTORE, 그 외 FRESH)
        # -------------------------------------------------------------
        prof_name = profile_obj.get("profile_name") if isinstance(profile_obj, dict) else None
        profile_id = profile_obj.get("profile_id", 0) if isinstance(profile_obj, dict) else 0
        profile_ssaid = profile_obj.get("ssaid") if isinstance(profile_obj, dict) else None
        profile_adid = profile_obj.get("adid") if isinstance(profile_obj, dict) else None
        profile_idfv = profile_obj.get("idfv") if isinstance(profile_obj, dict) else None
        install_ts = profile_obj.get("install_ts") if isinstance(profile_obj, dict) else None
        update_ts = profile_obj.get("update_ts") if isinstance(profile_obj, dict) else None
        installer_pkg = profile_obj.get("installer_pkg", "com.android.vending") if isinstance(profile_obj, dict) else "com.android.vending"
        app_version = profile_obj.get("app_version", "12.23.1") if isinstance(profile_obj, dict) else "12.23.1"
        app_version_code = profile_obj.get("app_version_code", 12230102) if isinstance(profile_obj, dict) else 12230102

        # [🕶️ 시크릿 1회성 모드 판별]
        # 프로필이 'pf_0000000000'이거나 profile_id가 0인 미생성 모드일 경우 백업을 하지 않는 1회성 시크릿 모드로 처리
        is_secret_mode = bool(
            not prof_name or
            prof_name == "pf_0000000000" or
            str(prof_name).startswith("pf_0000000000") or
            (profile_id == 0 and (prof_name is None or prof_name == "pf_0000000000"))
        )

        target_profile_tar = None if is_secret_mode else (self.mutator.resolve_profile_path(prof_name) if prof_name else None)

        mode = "FRESH"
        reset_method = "PM_CLEAR"
        if not is_secret_mode:
            if profile_id > 0 and target_profile_tar and self.mutator.profile_exists_on_device(target_profile_tar):
                mode = "RESTORE"
                reset_method = "PM_CLEAR"
            elif target_profile_tar and self.mutator.profile_exists_on_device(target_profile_tar):
                mode = "RESTORE"
                reset_method = "PM_CLEAR"

        custom_bssid = task_info.get("bssid") or profile_obj.get("bssid")
        custom_wifi_list = task_info.get("wifi_list") or profile_obj.get("wifi_list")
        custom_lat = (
            task_info.get("gps_lat") or profile_obj.get("gps_lat") or
            task_info.get("lat") or profile_obj.get("lat") or
            task_info.get("latitude") or profile_obj.get("latitude")
        )
        custom_lng = (
            task_info.get("gps_lng") or profile_obj.get("gps_lng") or
            task_info.get("lng") or profile_obj.get("lng") or
            task_info.get("longitude") or profile_obj.get("longitude")
        )

        # -------------------------------------------------------------
        # [🚨 STRICT API POLICY] API wifi_list 누락 시 즉시 Fail-Fast 차단 (폴백 불허)
        # -------------------------------------------------------------
        if not custom_wifi_list or not isinstance(custom_wifi_list, list) or len(custom_wifi_list) == 0:
            logger.error(f"[{self.device_id}] ❌ [FAIL-FAST] API 할당 데이터에 필수 'wifi_list' 누락! 작업을 즉시 실패 처리합니다.")
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
                "error_reason": "MISSING_API_WIFI_CONFIG",
                "public_ip": "NO_WIFI_CONFIG"
            }

        # -------------------------------------------------------------
        # [🚨 STRICT ROOT HIDING POLICY] SU 노출 단말기 즉시 Fail-Fast 차단 (자가수정/루프 절대 금지)
        # -------------------------------------------------------------
        su_status = self.guardian.check_su_hiding_status()
        if not su_status.get("is_su_hidden", False):
            logger.error(
                f"[{self.device_id}] ❌ [FAIL-FAST] SU 은닉 미적용 단말기 감지 (사유: {su_status.get('reason')})! "
                "자가수정 시도 없이 작업을 즉시 실패 처리하고 배제합니다."
            )
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
                "error_reason": "SU_DETECTED_UNSAFE_DEVICE",
                "public_ip": "UNSAFE_SU_DEVICE"
            }

        mut_res = self.mutator.mutate_identity(
            mode=mode,
            profile_tar=target_profile_tar if mode == "RESTORE" else None,
            ssaid=profile_ssaid,
            adid=profile_adid,
            idfv=profile_idfv,
            install_ts=install_ts,
            update_ts=update_ts,
            installer_pkg=installer_pkg,
            app_version=app_version,
            app_version_code=app_version_code,
            mock_lat=custom_lat,
            mock_lng=custom_lng,
            reset_method=reset_method,
            custom_bssid=custom_bssid,
            custom_wifi_list=custom_wifi_list
        )
        logger.info(f"[{self.device_id}] [✓] 소프트 리셋 신원 변조 완료 ({mode} 모드 | 프로필: {prof_name} | SSAID: {mut_res.get('ssaid')} | InstallTS: {mut_res.get('install_ts')})")

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
            max_timeout_sec=12.0
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
        # [🛡️ 2차 방어선] 실측 공인 IP(Egress IP) 24시간 쿨다운 엄격 검증
        # -------------------------------------------------------------
        from src.modules.ip_cooldown_tracker import ip_cooldown_tracker
        is_cooling, remain_sec, prev_info = ip_cooldown_tracker.is_ip_cooling(public_ip)
        if is_cooling:
            remain_m = round(remain_sec / 60, 1)
            remain_h = round(remain_sec / 3600, 2)
            logger.error(f"[{self.device_id}] 🛑 [2차 방어선 차단] 공인 IP ({public_ip}) 24시간 쿨다운 진행 중! (잔여: {remain_h}시간 / {remain_m}분 | 직전 작업: {prev_info.get('mid')}) ➔ 네이버 FDS 중복 감지 방지를 위해 즉시 안전 거부(Fail-Fast)")
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
                "error_reason": "IP_COOLDOWN_CONFLICT",
                "public_ip": public_ip
            }

        # -------------------------------------------------------------
        # 3. NaverMacroCore Step 1~4 UI 매크로 실행 (Guard Clause 일원화)
        # -------------------------------------------------------------
        # WireGuard 터널 활성화 직후 커널 DNS 및 라우팅 완전 안정화 버퍼
        time.sleep(1.0)

        try:
            is_searched, is_exposed, exposure_rank, is_clicked, error_reason = self._run_ui_macro(
                keyword=keyword,
                target_mid=target_mid,
                allow_click=allow_click
            )
        except Exception as e:
            logger.error(f"[{self.device_id}] 매크로 실행 중 예외 발생: {e}", exc_info=True)
            is_searched, is_exposed, exposure_rank, is_clicked = False, False, None, False
            error_reason = f"EXCEPTION: {str(e)}"

        # -------------------------------------------------------------
        # 4. 클린 Teardown: 네트워크 비콘 Flush 버퍼(2.5초) -> 네이버 앱 종료 -> 스냅샷 저장 -> WG 터널 해제
        # -------------------------------------------------------------
        # A. 세션 종료 전 Back 키 1회 전송(웹뷰 pagehide/onPause 트리거) 및 비콘 Flush 완충 대기 후 앱 강제 종료
        try:
            subprocess.run(["adb", "-s", self.device_id, "shell", "input keyevent 4"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        except Exception:
            pass
        time.sleep(2.5)
        subprocess.run(["adb", "-s", self.device_id, "shell", f"am force-stop {NAVER_PKG}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # B. 세션 쿠키(NNB, NAPP_DI) 추출
        session_ids = self.mutator.extract_session_identifiers()
        extracted_nnb = session_ids.get("nnb")
        extracted_napp_di = session_ids.get("napp_di")

        # C. 작업 종료 후 프로필 스냅샷 백업 (pf_0000000000 포함 전수 백업 및 히스토리 보관)
        prof_name = profile_obj.get("profile_name") if isinstance(profile_obj, dict) else None
        if not prof_name:
            prof_name = "pf_0000000000"

        final_snapshot, snapshot_size_kb = self.mutator.save_profile_snapshot(prof_name)

        # D-1. 프로필 지문 감사 레코드 로컬 파일 기록 (동일 값 잔존 여부 전수 대조용)
        try:
            import json
            audit_log_path = "/home/tech/nshop_macro_v1/logs/profile_audit_records.jsonl"
            os.makedirs(os.path.dirname(audit_log_path), exist_ok=True)
            audit_entry = {
                "timestamp": datetime.now().isoformat(),
                "device_id": self.device_id,
                "profile_name": prof_name,
                "job_type": job_type,
                "keyword": keyword,
                "target_mid": target_mid,
                "serialno": mut_res.get("serialno") if isinstance(mut_res, dict) else None,
                "ssaid": mut_res.get("ssaid") if isinstance(mut_res, dict) else None,
                "adid": mut_res.get("adid") if isinstance(mut_res, dict) else None,
                "nnb": extracted_nnb,
                "napp_di": extracted_napp_di,
                "install_ts": mut_res.get("install_ts") if isinstance(mut_res, dict) else None,
                "update_ts": mut_res.get("update_ts") if isinstance(mut_res, dict) else None,
                "snapshot_path": final_snapshot,
                "snapshot_size_kb": snapshot_size_kb,
                "is_searched": is_searched,
                "is_exposed": is_exposed,
                "is_clicked": is_clicked
            }
            with open(audit_log_path, "a", encoding="utf-8") as af:
                af.write(json.dumps(audit_entry, ensure_ascii=False) + "\n")
        except Exception as audit_err:
            logger.warning(f"[{self.device_id}] 감사 로그 기록 실패: {audit_err}")

        # D-2. 검색 세션 액션별 개별 노출 덤프 로컬 파일 기록 (logs/raw_impressions/YYYY-MM-DD/raw_impressions_...)
        try:
            self.macro.save_raw_impressions_action_dump(
                keyword=keyword,
                target_mid=target_mid,
                alloc_id=task_info.get("alloc_id"),
                status="SUCCESS" if (is_searched and error_reason is None) else "FAILED",
                is_searched=is_searched,
                is_exposed=is_exposed,
                is_clicked=is_clicked,
                error_reason=error_reason
            )
        except Exception as sum_err:
            logger.warning(f"[{self.device_id}] 액션별 개별 노출 덤프 기록 실패: {sum_err}")

        # E. WireGuard 터널 비활성화
        self.wg.deactivate_tunnel()

        # [🛡️ 2차 방어선] 스토어 상품 클릭 성공 시에만 공인 IP 24시간 쿨다운 영구 등록
        # (스토어를 클릭하지 않은 단순 검색/미노출 IP는 스토어 유효타 쿼터를 소모하지 않았으므로 살아있는 IP로 재사용 허용)
        if is_clicked:
            from src.modules.ip_cooldown_tracker import ip_cooldown_tracker
            ip_cooldown_tracker.record_ip_usage(
                public_ip=public_ip,
                mid=target_mid if target_mid != "0" else None,
                device_id=self.device_id,
                store=task_info.get("product_title") or keyword,
                is_clicked=True,
                note=f"CLICK_SUCCESS_alloc_{task_info.get('alloc_id')}"
            )
        else:
            logger.info(f"[{self.device_id}] ℹ️  스토어 미클릭 세션 (미노출/종료) ➔ 공인 IP ({public_ip}) 24시간 쿨다운 미부여 (미사용 상태 유지 및 즉시 재사용 허용)")

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

        logger.info(f"[{self.device_id}] 🏁 작업 완료 -> 상태: {final_status}, 노출: {is_exposed} (순위: {exposure_rank}), 클릭: {is_clicked}, 소요: {exec_sec}s | NNB: {extracted_nnb}, NAPP_DI: {extracted_napp_di} | 프로필: {snapshot_size_kb}KB | 배터리: {current_batt}% ({current_batt_precise:.2f}%)")

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
            "snapshot_size": snapshot_size_kb,
            "ssaid": mut_res.get("ssaid"),
            "adid": mut_res.get("adid"),
            "nnb": extracted_nnb,
            "napp_di": extracted_napp_di,
            "install_ts": mut_res.get("install_ts"),
            "update_ts": mut_res.get("update_ts"),
            "installer_pkg": mut_res.get("installer_pkg", installer_pkg),
            "app_version": mut_res.get("app_version", app_version),
            "app_version_code": mut_res.get("app_version_code", app_version_code),
            "gps_lat": mut_res.get("gps_lat"),
            "gps_lng": mut_res.get("gps_lng"),
            "latitude": mut_res.get("gps_lat"),
            "longitude": mut_res.get("gps_lng"),
            "battery_level": round(current_batt_precise, 2),
            "error_reason": error_reason,
            "public_ip": public_ip
        }
