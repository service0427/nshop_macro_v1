#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
[모듈명] 초고속 소프트 재부팅 신원 변조기 (SoftRebootMutator) - Facade Orchestrator
========================================================================================
- 기능:
    1. 10초 초고속 Zygote 소프트 리셋(`ctl.restart zygote`)으로 system_server 캐시를 완전 플러시.
    2. SSAID, ADID, NAPP_DI, NNB 전수를 100% 새로운 디바이스 신원으로 난수화.
    3. [🛡️ Rescue Party 영구 무력화]: 연속 재부팅 시 안전모드(Safe Mode)나 복구 화면으로 빠지는 현상을 원천 차단.
    4. [🛡️ 안티 디텍션 가디언 연동]: 네이버 앱 위치 권한 영구 회수(BSSID 은닉) 및 안전 권한 선별 승인.
    5. 숙성 프로필(app_xwhale, app_webview, databases, shared_prefs, files) 스냅샷 저장 및 고속 복원 지원.

----------------------------------------------------------------------------------------
[수정 및 변경 이력 (Revision History)]
----------------------------------------------------------------------------------------
- 2026-09-05:
    * [FDS 무효클릭 방어 패치] 리셋 후 위치 권한(FINE_LOCATION, COARSE_LOCATION) 승인 코드 전면 제거.
    * [BSSID 및 Mock Location 차단] 네이버 앱의 BSSID 수집 및 isFromMockProvider 감지를
      방지하기 위해 AntiDetectionGuardian을 통한 권한 정제(pm revoke + appops ignore) 일원화.
    * 시스템 전역 무선 스캔 차단(0) 동기화.
========================================================================================
"""

import os
import time
import uuid
import random
import logging
import subprocess
from textwrap import dedent
from typing import Dict, Any, Optional, Tuple, List

from src.config import NAVER_PKG, PRIMARY_SERVER_URL
from src.modules.mutator.os_environment import (
    OSEnvironmentController,
    SEOUL_GPS_COORDS,
    RUNTIME_PERMISSIONS
)
from src.modules.mutator.zygote_reset import ZygoteResetEngine
from src.modules.mutator.payload_generator import PayloadGenerator
from src.modules.mutator.profile_manager import ProfileStorageManager
from src.modules.mutator.wifi_location_guard import WifiLocationGuard


logger = logging.getLogger("SoftRebootMutator")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [SoftReboot] %(message)s",
        datefmt="%H:%M:%S"
    )


class SoftRebootMutator:
    """
    안드로이드 초고속 소프트 재부팅 기반 신원 변조 및 프로필 관리자 (오케스트레이터)
    """

    def __init__(self, device_id: str, package_name: str = NAVER_PKG):
        self.device_id = device_id
        self.package_name = package_name

        # 서브 도메인 컨트롤러 구성
        self.os_env = OSEnvironmentController(device_id, package_name)
        self.zygote = ZygoteResetEngine(device_id)
        self.profiles = ProfileStorageManager(device_id, package_name)

    # -------------------------------------------------------------------------
    # 🛡️ Low-level OS / 환경 위임 메서드 (하위 호환성 100% 보장)
    # -------------------------------------------------------------------------
    def _run_adb_su(self, shell_cmd: str, timeout: int = 25) -> str:
        return self.os_env.run_adb_su(shell_cmd, timeout=timeout)

    def disable_rescue_party(self):
        self.os_env.disable_rescue_party()

    def pre_grant_permissions(self):
        self.os_env.pre_grant_permissions()

    def get_app_uid(self) -> str:
        return self.os_env.get_app_uid()

    def spoof_gps_location(self, lat: Optional[float] = None, lng: Optional[float] = None) -> Tuple[float, float]:
        return self.os_env.spoof_gps_location(lat, lng)

    def trigger_soft_reboot_and_wait(self, max_wait_sec: int = 35) -> bool:
        return self.zygote.trigger_soft_reboot_and_wait(max_wait_sec=max_wait_sec)

    def get_free_storage_mb(self) -> int:
        return self.os_env.get_free_storage_mb()

    def get_file_size_kb(self, remote_path: str) -> Optional[float]:
        return self.os_env.get_file_size_kb(remote_path)

    # -------------------------------------------------------------------------
    # 📂 프로필 저장소 위임 메서드 (하위 호환성 100% 보장)
    # -------------------------------------------------------------------------
    @staticmethod
    def get_profile_group_dir(profile_name_or_id: Any) -> str:
        return ProfileStorageManager.get_profile_group_dir(profile_name_or_id)

    def get_profile_tar_path(self, profile_name_or_id: Any) -> str:
        return self.profiles.get_profile_tar_path(profile_name_or_id)

    def profile_exists_on_device(self, profile_tar: str) -> bool:
        return self.profiles.profile_exists_on_device(profile_tar)

    def resolve_profile_path(self, profile_name_or_id: Any) -> Optional[str]:
        return self.profiles.resolve_profile_path(profile_name_or_id)

    def save_profile_snapshot(self, profile_name: str) -> Tuple[Optional[str], Optional[float]]:
        return self.profiles.save_profile_snapshot(profile_name)

    def sync_profiles_with_server(self, server_host: str = PRIMARY_SERVER_URL) -> Dict[str, Any]:
        return self.profiles.sync_profiles_with_server(server_host)

    def extract_session_identifiers(self) -> Dict[str, Optional[str]]:
        return self.profiles.extract_session_identifiers()

    # -------------------------------------------------------------------------
    # 🚀 신원 변조 메인 파이프라인
    # -------------------------------------------------------------------------
    def mutate_identity(
        self,
        mode: str = "FRESH",
        profile_tar: Optional[str] = None,
        ssaid: Optional[str] = None,
        adid: Optional[str] = None,
        idfv: Optional[str] = None,
        install_ts: Optional[int] = None,
        update_ts: Optional[int] = None,
        installer_pkg: str = "com.android.vending",
        app_version: str = "12.23.1",
        app_version_code: int = 12230102,
        mock_lat: Optional[float] = None,
        mock_lng: Optional[float] = None,
        reset_method: str = "PM_CLEAR",
        custom_bssid: Optional[str] = None,
        custom_wifi_list: Optional[List[Dict[str, Any]]] = None,
        custom_serial: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        [소프트 재부팅 기반 신원 변조 메인 파이프라인]
        :param reset_method: "PM_CLEAR" (완전 초기화 및 100% 클린 샌드박스) | "SELECTIVE" (캐시 재사용)
        """
        t_start = time.time()
        logger.info("==========================================================================")
        logger.info(f" 🚀 [{self.device_id}] 초고속 소프트 재부팅 신원 변조 시작 (Mode: {mode} | Reset: {reset_method})")
        logger.info("==========================================================================")

        # 1. 안전모드(Rescue Party) 무력화 가드 적용
        self.disable_rescue_party()

        # 2. 고유 식별자 난수 생성
        target_ssaid = ssaid if ssaid else f"{random.getrandbits(64):016x}"
        target_adid = adid if adid else str(uuid.uuid4())
        target_idfv = idfv if idfv else str(uuid.uuid4())

        # 3. 앱 설치 타임스탬프 (30~365일 전) 및 최근 업데이트 타임스탬프 산출 (v3.1 Standard)
        now_ms = int(time.time() * 1000)
        if install_ts and int(install_ts) > 0:
            target_install_ts = int(install_ts)
        else:
            days_ago = random.randint(30, 365)
            target_install_ts = now_ms - (days_ago * 86400 * 1000) + random.randint(0, 86400000)

        if update_ts and int(update_ts) > 0:
            target_update_ts = int(update_ts)
        else:
            update_days_ago = random.randint(3, 25)
            target_update_ts = now_ms - (update_days_ago * 86400 * 1000) + random.randint(0, 86400000)
            if target_update_ts < target_install_ts:
                target_update_ts = target_install_ts + random.randint(86400000, 86400000 * 10)

        # 4. 앱 및 GMS 서비스 종료
        self._run_adb_su(f"am force-stop {self.package_name}; am force-stop com.google.android.gms")

        # 5. 샌드박스 초기화 또는 프로필 복원 준비
        target_profile_path = profile_tar
        is_restore = (mode == "RESTORE" and target_profile_path and self.profile_exists_on_device(target_profile_path))

        # 6. 고유 광고 식별자(NAS_USER_ID) 및 가상 하드웨어 시리얼 결정
        if custom_serial:
            target_serial = custom_serial
        elif is_restore and target_profile_path:
            # 숙성 프로필 복원 모드: 프로필 고유 결정론적 UUID 및 시리얼 유지 (동일 프로필은 재방문 시 동일 식별자 보존)
            import hashlib
            prof_basename = os.path.basename(target_profile_path).replace(".tar.gz", "")
            target_nas_user_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{self.device_id}_{prof_basename}"))
            h = hashlib.sha256(f"{self.device_id}_{prof_basename}".encode()).hexdigest()
            pfx = "R3CR" if int(h[0], 16) % 2 == 0 else "R5CR"
            btc = ['7', '8', '9', 'A', 'B', 'C'][int(h[1], 16) % 6]
            charset = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"
            sfx = "".join(charset[int(h[2+i*2:4+i*2], 16) % len(charset)] for i in range(6))
            target_serial = f"{pfx}{btc}{sfx}"
        else:
            # 신규 생성 모드: 100% 새로운 랜덤 UUID 및 가상 시리얼 발급
            target_nas_user_id = str(uuid.uuid4())
            target_serial = self.os_env.generate_fake_serial()

        logger.info(f"[{self.device_id}] [1/3] 원자적 신원/환경 데이터 주입 중... (SSAID: {target_ssaid} | Serial: {target_serial} | InstallTS: {target_install_ts})")
        self._push_environment_payloads(target_ssaid, target_adid, target_nas_user_id, target_install_ts, target_update_ts, app_version, app_version_code)

        # 7. [배치 1] 리셋 전 샌드박스 정리 및 시스템 신원(SSAID ABX 패치, OS 패키지 타임스탬프, ADID, 하드웨어 가상화) 주입
        self._apply_pre_reset_sandbox(target_ssaid, reset_method, is_restore, target_install_ts, target_update_ts, target_serial=target_serial)

        # 8. 초고속 Zygote 소프트 리셋 (10~18초 소요, system_server 캐시 완전 갱신 ➔ NAPP_DI 신규 발급)
        logger.info(f"[{self.device_id}] [2/3] Zygote 소프트 리셋 실행 (NAPP_DI 갱신 보장)...")
        self.trigger_soft_reboot_and_wait()

        # 9. [배치 2] 부팅 완료 후 런타임 권한, GPS 스푸핑 및 프로필/튜토리얼 복원
        logger.info(f"[{self.device_id}] [3/3] 런타임 권한 승인, GPS 스푸핑 및 프로필/튜토리얼 Zero-Tap 주입...")
        final_lat, final_lng = self._apply_post_reset_restore(
            is_restore, target_profile_path, mock_lat, mock_lng,
            custom_bssid=custom_bssid, custom_wifi_list=custom_wifi_list
        )

        # 실제 앱에 최종 반영된 NAS_USER_ID 추출 (자가 치유 및 복원 반영 확인)
        final_nas = self._run_adb_su(
            f"sed -n 's/.*com.naver.ads.NAS_USER_ID\">\\(.*\\)<\\/string>.*/\\1/p' /data/data/{self.package_name}/shared_prefs/com.naver.ads.flags.xml 2>/dev/null"
        ).strip()
        if final_nas:
            target_nas_user_id = final_nas

        duration = round(time.time() - t_start, 2)
        logger.info("==========================================================================")
        logger.info(f" [✓] 초고속 소프트 리셋 신원 변조 완료! (소요 시간: {duration}초 | Serial: {target_serial})")
        logger.info("==========================================================================")

        return {
            "device_id": self.device_id,
            "status": "SUCCESS",
            "mode": mode,
            "reset_method": reset_method,
            "ssaid": target_ssaid,
            "adid": target_adid,
            "idfv": target_idfv,
            "nas_user_id": target_nas_user_id,
            "serialno": target_serial,
            "install_ts": target_install_ts,
            "update_ts": target_update_ts,
            "installer_pkg": installer_pkg,
            "app_version": app_version,
            "app_version_code": app_version_code,
            "gps_lat": final_lat,
            "gps_lng": final_lng,
            "execution_sec": duration,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    def _push_environment_payloads(
        self,
        target_ssaid: str,
        target_adid: str,
        target_nas_user_id: str,
        target_install_ts: int,
        target_update_ts: int,
        app_version: str,
        app_version_code: int
    ):
        """임시 XML 및 바이너리 생성 및 단말기 /data/local/tmp 푸시"""
        t_ad = f"/tmp/adid_{self.device_id}.xml"
        t_nu = f"/tmp/null_{self.device_id}.xml"
        t_tu = f"/tmp/tut_{self.device_id}.xml"
        t_nl = f"/tmp/nlog_{self.device_id}.xml"
        t_nas = f"/tmp/nas_{self.device_id}.xml"
        t_nt = f"/tmp/ntrack_{self.device_id}.xml"
        t_pi_lut = f"/tmp/pi_lut_{self.device_id}.dat"
        t_pi_inst = f"/tmp/pi_inst_{self.device_id}.dat"

        with open(t_ad, "w", encoding="utf-8") as f:
            f.write(PayloadGenerator.generate_adid_payload(target_adid))
        with open(t_nu, "w", encoding="utf-8") as f:
            f.write(PayloadGenerator.generate_null_prefs_payload(target_install_ts, target_update_ts, app_version, app_version_code))
        with open(t_tu, "w", encoding="utf-8") as f:
            f.write(PayloadGenerator.generate_tutorial_payload())
        with open(t_nl, "w", encoding="utf-8") as f:
            f.write(PayloadGenerator.generate_nlog_pref_payload(target_install_ts, app_version))
        with open(t_nas, "w", encoding="utf-8") as f:
            f.write(PayloadGenerator.generate_ads_flags_payload(target_nas_user_id))
        with open(t_nt, "w", encoding="utf-8") as f:
            f.write(PayloadGenerator.generate_ntracker_payload(target_install_ts, app_version))

        pi_lut, pi_inst = PayloadGenerator.generate_profileinstaller_payloads(target_update_ts)
        with open(t_pi_lut, "wb") as f:
            f.write(pi_lut)
        with open(t_pi_inst, "wb") as f:
            f.write(pi_inst)

        try:
            for src, dst in [
                (t_ad, f"/data/local/tmp/adid_{self.device_id}.xml"),
                (t_nu, f"/data/local/tmp/null_{self.device_id}.xml"),
                (t_tu, f"/data/local/tmp/tut_{self.device_id}.xml"),
                (t_nl, f"/data/local/tmp/nlog_{self.device_id}.xml"),
                (t_nas, f"/data/local/tmp/nas_{self.device_id}.xml"),
                (t_nt, f"/data/local/tmp/ntrack_{self.device_id}.xml"),
                (t_pi_lut, f"/data/local/tmp/pi_lut_{self.device_id}.dat"),
                (t_pi_inst, f"/data/local/tmp/pi_inst_{self.device_id}.dat"),
            ]:
                subprocess.run(["adb", "-s", self.device_id, "push", src, dst], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception as push_err:
            logger.warning(f"[{self.device_id}] [!] adb push 중 예외 발생: {push_err}")
        finally:
            for tmp_f in [t_ad, t_nu, t_tu, t_nl, t_nas, t_nt, t_pi_lut, t_pi_inst]:
                if os.path.exists(tmp_f):
                    os.remove(tmp_f)

    def _apply_pre_reset_sandbox(
        self,
        target_ssaid: str,
        reset_method: str,
        is_restore: bool,
        target_install_ts: Optional[int] = None,
        target_update_ts: Optional[int] = None,
        target_serial: Optional[str] = None
    ):
        """소프트 리셋 전 패키지 정리 및 시스템 식별자/패키지 타임스탬프 ABX 주입 및 하드웨어 가상화"""
        if reset_method == "PM_CLEAR" and not is_restore:
            cleanup_cmd = f"pm clear {self.package_name}"
        else:
            cleanup_cmd = dedent(f"""\
                am force-stop {self.package_name} 2>/dev/null || true
                rm -rf /data/data/{self.package_name}/app_webview/*
                rm -rf /data/data/{self.package_name}/app_xwhale/*
                rm -rf /data/data/{self.package_name}/cache/*
                rm -rf /data/data/{self.package_name}/code_cache/*
                rm -rf /data/data/{self.package_name}/databases/*
                rm -rf /data/data/{self.package_name}/files/*
                rm -rf /data/data/{self.package_name}/no_backup/*
                rm -rf /data/data/{self.package_name}/shared_prefs/*
            """).strip()

        # 1. 안드로이드 13 ABX 바이너리 SSAID 인플레이스 교체 (NAPP_DI = MD5(SSAID) 신규 발급 보장)
        self.os_env.mutate_system_ssaid(target_ssaid)

        # 2. 안드로이드 13 ABX 바이너리 OS 패키지 설치/업데이트 일자 원천 인플레이스 교체 (reboot 시 OS 네이티브 반영)
        if target_install_ts and target_update_ts:
            self.os_env.mutate_system_package_timestamps(target_install_ts, target_update_ts)

        # 3. 공장초기화 수준의 하드웨어 지문 가상화 & 고유 식별자 은닉 (ro.serialno, ap_serial, /efs, /sys, ARP)
        self.os_env.mutate_hardware_identifiers(target_serial)

        pre_reset_cmd = dedent(f"""\
            # 1. 안전모드 차단 가드
            setprop persist.sys.enable_rescue false
            setprop persist.sys.disable_rescue true
            setprop sys.rescue_boot_count 0
            setprop sys.rescue_level 0
            settings put global rescue_party_disabled 1 2>/dev/null || true
            settings put global enable_rescue_party false 2>/dev/null || true
            rm -rf /data/system/users/0/rescue_party* /data/system/rescue* /data/system/dropbox/* 2>/dev/null || true

            # 2. 패키지 프로세스/데이터 정리
            {cleanup_cmd}

            # 3. GMS ADID 주입
            mkdir -p /data/data/com.google.android.gms/shared_prefs
            cp /data/local/tmp/adid_{self.device_id}.xml /data/data/com.google.android.gms/shared_prefs/adid_settings.xml
            chown -R $(stat -c %u:%g /data/data/com.google.android.gms) /data/data/com.google.android.gms/shared_prefs 2>/dev/null || true
            chmod 660 /data/data/com.google.android.gms/shared_prefs/adid_settings.xml 2>/dev/null || true
            rm -rf /data/data/com.google.android.gms/files/appset/shared/* 2>/dev/null || true
        """).strip()
        self._run_adb_su(pre_reset_cmd)

    def _apply_post_reset_restore(
        self,
        is_restore: bool,
        target_profile_path: Optional[str],
        mock_lat: Optional[float],
        mock_lng: Optional[float],
        custom_bssid: Optional[str] = None,
        custom_wifi_list: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[float, float]:
        """부팅 완료 후 권한, GPS, 프로필 복원 및 권한 동기화"""
        if mock_lat is not None and mock_lng is not None:
            final_lat = round(float(mock_lat), 6)
            final_lng = round(float(mock_lng), 6)
        else:
            base_lat, base_lng = random.choice(SEOUL_GPS_COORDS)
            lat_jitter = random.uniform(-0.00025, 0.00025)
            lng_jitter = random.uniform(-0.00025, 0.00025)
            final_lat = round(base_lat + lat_jitter, 6)
            final_lng = round(base_lng + lng_jitter, 6)

        real_app_uid = self.get_app_uid()

        # 🛡️ [안티 디텍션 가디언 권한 정제 적용]
        # 1) 시스템 전역 스캔(Wi-Fi, BLE, Nearby) 100% 차단(0)
        # 2) 네이버 앱 위치 권한(FINE/COARSE) 영구 박탈 및 ignore 처리 -> 작업실 공유기 BSSID 유출 방어
        # 3) 모의 위치(MOCK_LOCATION) 원천 차단 -> classes10.dex isFromMockProvider 탐지 방어
        self.os_env.guardian.enforce_device_scan_guards()
        self.os_env.guardian.sanitize_target_app_permissions()

        post_reset_cmd = dedent(f"""\
            # 프로필 복원 및 튜토리얼/온보딩 스킵 주입
            mkdir -p /data/data/{self.package_name}/shared_prefs
            mkdir -p /data/data/{self.package_name}/databases
            mkdir -p /data/data/{self.package_name}/files
            if [ "{is_restore}" = "True" ] && [ -f "{target_profile_path}" ]; then
                tar -xzf {target_profile_path} -C /data/data/{self.package_name} 2>/dev/null || true
                # [자가 치유 & 숙성 프로필 무결성 보장]
                # 1. 과거 golden_shared_prefs 오염값(3ae032d6...)이 있거나 flags.xml이 없으면 프로필 고유 결정론적 UUID로 즉시 치유
                if [ ! -f /data/data/{self.package_name}/shared_prefs/com.naver.ads.flags.xml ] || grep -q "3ae032d6-391c-4ef9-8572-e0ebd0de6407" /data/data/{self.package_name}/shared_prefs/com.naver.ads.flags.xml 2>/dev/null; then
                    cp /data/local/tmp/nas_{self.device_id}.xml /data/data/{self.package_name}/shared_prefs/com.naver.ads.flags.xml
                fi
                # 2. 레거시 덤프 Nelo_prefs.xml(과거 테스트 단말의 고정 AdlogId/DeviceID/NNB 잔재) 제거
                rm -f /data/data/{self.package_name}/shared_prefs/Nelo_prefs.xml 2>/dev/null || true
                # 3. NTracker 및 ProfileInstaller의 하드웨어 원본 설치/업데이트 시각 누출 강제 치유
                cp /data/local/tmp/ntrack_{self.device_id}.xml /data/data/{self.package_name}/shared_prefs/NTracker_SharedPreference.xml
                cp /data/local/tmp/pi_lut_{self.device_id}.dat /data/data/{self.package_name}/files/profileinstaller_profileWrittenFor_lastUpdateTime.dat
                cp /data/local/tmp/pi_inst_{self.device_id}.dat /data/data/{self.package_name}/files/profileInstalled
            else
                cp /data/local/tmp/null_{self.device_id}.xml /data/data/{self.package_name}/shared_prefs/null.xml
                cp /data/local/tmp/tut_{self.device_id}.xml /data/data/{self.package_name}/shared_prefs/tutorial_pref.xml
                cp /data/local/tmp/null_{self.device_id}.xml /data/data/{self.package_name}/shared_prefs/{self.package_name}_preferences.xml
                cp /data/local/tmp/nlog_{self.device_id}.xml /data/data/{self.package_name}/shared_prefs/nlog_pref.xml
                cp /data/local/tmp/nas_{self.device_id}.xml /data/data/{self.package_name}/shared_prefs/com.naver.ads.flags.xml
                cp /data/local/tmp/ntrack_{self.device_id}.xml /data/data/{self.package_name}/shared_prefs/NTracker_SharedPreference.xml
                cp /data/local/tmp/pi_lut_{self.device_id}.dat /data/data/{self.package_name}/files/profileinstaller_profileWrittenFor_lastUpdateTime.dat
                cp /data/local/tmp/pi_inst_{self.device_id}.dat /data/data/{self.package_name}/files/profileInstalled
            fi

            chown -R {real_app_uid}:{real_app_uid} /data/data/{self.package_name} 2>/dev/null || true
            chmod -R 775 /data/data/{self.package_name} 2>/dev/null || true
            restorecon -F -R /data/data/{self.package_name} 2>/dev/null || true

            # 임시 파일 정리
            rm -f /data/local/tmp/adid_{self.device_id}.xml /data/local/tmp/null_{self.device_id}.xml /data/local/tmp/tut_{self.device_id}.xml /data/local/tmp/nlog_{self.device_id}.xml /data/local/tmp/nas_{self.device_id}.xml /data/local/tmp/ntrack_{self.device_id}.xml /data/local/tmp/pi_lut_{self.device_id}.dat /data/local/tmp/pi_inst_{self.device_id}.dat
        """).strip()
        self._run_adb_su(post_reset_cmd, timeout=30)

        # 📡 [현실적 무선 환경 및 프로필 앵커링 거점 AP / GPS 주입 + 커널 불변(+i) 잠금]
        prof_name = os.path.basename(target_profile_path).replace(".tar.gz", "") if target_profile_path else None
        if custom_wifi_list and isinstance(custom_wifi_list, list) and len(custom_wifi_list) > 0:
            wifi_guard = WifiLocationGuard(self.device_id, self.package_name)
            wifi_res = wifi_guard.inject_and_lock(
                custom_ap_list=custom_wifi_list,
                custom_lat=mock_lat,
                custom_lng=mock_lng
            )
            final_lat = wifi_res.get("gps_lat", final_lat)
            final_lng = wifi_res.get("gps_lng", final_lng)

        # 🔒 하드웨어 파일 및 네트워크 ARP 누출 방어 잠금 사후 강화
        hw_lock_cmd = dedent("""\
            chattr -i /efs/FactoryApp/serial_no 2>/dev/null || true
            chmod 700 /efs/FactoryApp/serial_no 2>/dev/null || true
            chattr +i /efs/FactoryApp/serial_no 2>/dev/null || true
            chmod 600 /sys/devices/soc0/serial_number 2>/dev/null || true
            chmod 600 /proc/net/arp 2>/dev/null || true
            chmod 600 /proc/net/route 2>/dev/null || true
        """).strip()
        self._run_adb_su(hw_lock_cmd, timeout=5)

        return final_lat, final_lng

    def execute_pm_clear_maintenance(self) -> Dict[str, Any]:
        """[100주기 정기 유지보수] pm clear를 통한 딥클린 및 캐시 비대화 방지 초기화"""
        logger.info(f"[{self.device_id}] 🧼 [100주기 정기 유지보수] pm clear 딥클린 및 캐시 누적 초기화 실행...")
        self._run_adb_su(f"pm clear {self.package_name}")
        return {"device_id": self.device_id, "status": "SUCCESS", "action": "PM_CLEAR_MAINTENANCE"}
