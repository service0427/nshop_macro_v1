#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
🛡️ N-SHOP ANTI-DETECTION GUARDIAN (안티 디텍션 전담 가디언)
========================================================================================
[모듈 목적]
네이버 앱(com.nhn.android.search) 및 탑재된 부정클릭/디바이스팜 탐지 SDK(AppsFlyer Protect360,
NELO, nClicks, NRC)가 단말기의 물리적 환경(작업실 Wi-Fi, 거치대 고정, VPN 터널링, GPS 위조)을
탐지하여 유효 클릭을 무효화(FDS 드롭)하는 것을 원천 방어하고 무력화하는 전담 모듈.

----------------------------------------------------------------------------------------
[수정 및 변경 이력 (Revision History)]
----------------------------------------------------------------------------------------
- 2026-09-05 (V1.0 - 초기 구축):
    1. [APK 바이트코드 역추적 기반 방어 설계]:
       - classes10.dex / classes2.dex 내 `isFromMockProvider`, `isMock` 탐지 로직 확인.
       - classes9.dex / classes8.dex 내 `getNetworkCapabilities`(TRANSPORT_VPN) 및
         `getNetworkInterfaces`(tun0) 탐지 로직 확인.
    2. [위치 권한(ACCESS_FINE_LOCATION) 영구 박탈]:
       - 안드로이드 10+ 보안 스펙상 위치 권한이 없으면 `WifiManager.getConnectionInfo()`가
         작업실 공유기(`Tech_5G`)의 실제 BSSID(MAC)를 읽지 못하고 더미 `02:00:00:00:00:00`을 반환함.
       - 이를 통해 9대 단말기가 동일 공간(작업실)에 모여 있다는 사실을 네이버 앱이 원천 알 수 없도록 차단.
       - 가짜 GPS 주입 시 발생하는 `isFromMockProvider=true` 트리거도 원천 차단.
    3. [시스템 전역 스캔 차단 Enforcer]:
       - `ble_scan_always_enabled = 0`
       - `wifi_scan_always_enabled = 0`
       - `nearby_scanning_enabled = 0`
       - 9대 전 단말기 강제 주입 및 세션별 상태 감사(Audit) 로직 내장.
========================================================================================
"""

import logging
import subprocess
from textwrap import dedent
from typing import Dict, Any, List, Optional

logger = logging.getLogger("AntiDetectionGuardian")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [AntiDetection] %(message)s",
        datefmt="%H:%M:%S"
    )

# --------------------------------------------------------------------------------------
# 1. 안전 승인 런타임 권한 (쇼핑 탐색 및 일반 동작에 필수적인 안전 권한 목록)
# --------------------------------------------------------------------------------------
SAFE_RUNTIME_PERMISSIONS: List[str] = [
    "android.permission.POST_NOTIFICATIONS",
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
    "android.permission.READ_MEDIA_IMAGES",
    "android.permission.READ_MEDIA_VIDEO",
    "android.permission.READ_MEDIA_AUDIO",
    "android.permission.CAMERA",
    "android.permission.RECORD_AUDIO",
    "android.permission.READ_PHONE_STATE",
    "android.permission.GET_ACCOUNTS",
    "android.permission.ACTIVITY_RECOGNITION",
]

# --------------------------------------------------------------------------------------
# 2. 절대 부여 금지 위험 권한 (FDS 탐지 및 작업실 지문 유출 유발 권한 목록)
# --------------------------------------------------------------------------------------
REVOKED_DANGEROUS_PERMISSIONS: List[str] = [
    # ⚠️ [위치 권한 영구 회수 사유]:
    # 안드로이드 10+에서 위치 권한 부여 시 WifiManager가 작업실 공유기(Tech_5G)의 실제 BSSID를
    # 읽어와 gfp_access_points.json에 기록하고 서버로 전송함. 회수 시 02:00:00:00:00:00 더미만 반환됨.
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    # ⚠️ [블루투스/주변기기 스캔 차단 사유]:
    # 주변 비콘 및 블루투스 기기 MAC 주소 유출 방지
    "android.permission.BLUETOOTH_SCAN",
    "android.permission.BLUETOOTH_CONNECT",
    "android.permission.BLUETOOTH_ADVERTISE",
    # ⚠️ [생체 센서 권한 차단 사유]:
    # 거치대 고정 시 무진동(0 진폭)을 네이버 앱이 읽지 못하도록 차단
    "android.permission.BODY_SENSORS",
]


class AntiDetectionGuardian:
    """
    네이버 FDS 무효클릭 필터 회피 및 단말기 지문 유출 방지 전담 가디언
    """

    def __init__(self, device_id: str, package_name: str = "com.nhn.android.search"):
        self.device_id = device_id
        self.package_name = package_name

    def _run_adb_su(self, shell_cmd: str, timeout_sec: int = 10) -> str:
        """단말기 셸 su 명령어 실행"""
        try:
            cmd = ["adb", "-s", self.device_id, "shell", "su"]
            res = subprocess.run(cmd, input=shell_cmd, capture_output=True, text=True, timeout=timeout_sec)
            return res.stdout.strip()
        except Exception as e:
            logger.warning(f"[{self.device_id}] ADB su 명령 실패: {e}")
            return ""

    def enforce_device_scan_guards(self) -> bool:
        """
        [시스템 전역 스캔 차단 (OS Level)]
        - Wi-Fi 찾기(wifi_scan_always_enabled) = 0
        - 블루투스 찾기(ble_scan_always_enabled) = 0
        - 주변 기기 찾기(nearby_scanning_enabled) = 0
        단말기 설정에서 백그라운드 무선 환경 스캔을 시스템 전역에서 100% 차단합니다.
        """
        guard_script = dedent("""
            settings put global wifi_scan_always_enabled 0 2>/dev/null || true
            settings put global ble_scan_always_enabled 0 2>/dev/null || true
            settings put system nearby_scanning_enabled 0 2>/dev/null || true
            settings put system nearby_scanning_permission_allowed 0 2>/dev/null || true
        """).strip()
        self._run_adb_su(guard_script)
        logger.info(f"[{self.device_id}] 🛡️ [단말기 스캔 가드] Wi-Fi/BLE/Nearby 백그라운드 탐색 100% 차단(0) 적용 완료")
        return True

    def sanitize_target_app_permissions(self) -> bool:
        """
        [네이버 앱 권한 정제 및 위험 권한 영구 회수]
        1. 안전 권한(SAFE_RUNTIME_PERMISSIONS)만 선별 승인 (`pm grant`)
        2. 위험 권한(REVOKED_DANGEROUS_PERMISSIONS)은 강제 회수 (`pm revoke`)
        3. AppOps 레벨에서 FINE_LOCATION, COARSE_LOCATION, MOCK_LOCATION을 'ignore'로 강제 잠금
        """
        commands: List[str] = ["# 1. 안전 권한 선별 부여"]
        for perm in SAFE_RUNTIME_PERMISSIONS:
            commands.append(f"pm grant {self.package_name} {perm} 2>/dev/null || true")

        commands.append("# 2. 위험 권한(위치, BLE스캔, 센서) 강제 회수 (BSSID 유출 방어)")
        for perm in REVOKED_DANGEROUS_PERMISSIONS:
            commands.append(f"pm revoke {self.package_name} {perm} 2>/dev/null || true")

        appops_script = dedent(f"""
            # 3. AppOps 레벨 위험 권한 ignore 차단 (작업실 BSSID 및 Mock GPS 유출 원천 차단)
            cmd appops set {self.package_name} POST_NOTIFICATION allow 2>/dev/null || true
            cmd appops set {self.package_name} FINE_LOCATION ignore 2>/dev/null || true
            cmd appops set {self.package_name} COARSE_LOCATION ignore 2>/dev/null || true
            cmd appops set {self.package_name} MOCK_LOCATION ignore 2>/dev/null || true
            cmd appops set {self.package_name} BODY_SENSORS ignore 2>/dev/null || true
        """).strip()
        commands.append(appops_script)

        full_script = "\n".join(commands)
        self._run_adb_su(full_script)
        logger.info(f"[{self.device_id}] 🛡️ [권한 정제 완료] 위치 권한(FINE/COARSE) 회수 및 AppOps ignore 적용 -> BSSID 유출 방어")
        return True

    def mask_adb_debugging(self, enable: bool = False) -> bool:
        """
        [USB 디버깅 플래그 마스킹]
        네이버 앱이 `Settings.Global.getInt('adb_enabled')`를 읽어 자동화 기기임을 탐지하는 것을 방어.
        작업 실행 직전 0으로 마스킹하고, 세션 종료 후 필요 시 복원.
        """
        val = 1 if enable else 0
        self._run_adb_su(f"settings put global adb_enabled {val} 2>/dev/null || true")
        return True

    def check_su_hiding_status(self) -> Dict[str, Any]:
        """
        [SU 및 Magisk 은닉 상태 정밀 검사]
        네이버 앱(FDS/Protect360/NELO)이 /product/bin/su, /system/bin/su 등을 탐지하지 못하도록
        Magisk DenyList가 활성화되어 있고 패키지가 등록되어 있는지 검사.
        - 미루팅 단말기: safe=True (은닉 불필요)
        - 루팅 단말기:
            1) magisk --denylist status == 'Denylist is enforced'
            2) magisk --denylist ls 내 target package 존재
            둘 다 만족 시 safe=True, 미충족 시 safe=False.
        """
        has_su_out = self._run_adb_su("which su 2>/dev/null || ls /product/bin/su /system/bin/su 2>/dev/null")
        if not has_su_out:
            return {
                "device_id": self.device_id,
                "is_rooted": False,
                "is_su_hidden": True,
                "denylist_enforced": False,
                "package_in_denylist": False,
                "reason": "NON_ROOTED_DEVICE"
            }

        # Rooted device -> Check Magisk DenyList
        denylist_status = self._run_adb_su("magisk --denylist status 2>&1").strip()
        is_enforced = "enforced" in denylist_status.lower() and "not enforced" not in denylist_status.lower()

        denylist_ls = self._run_adb_su("magisk --denylist ls 2>/dev/null").strip()
        pkg_in_list = self.package_name in denylist_ls

        is_safe = is_enforced and pkg_in_list
        reason = "SAFE" if is_safe else ("DENYLIST_NOT_ENFORCED" if not is_enforced else "PACKAGE_NOT_IN_DENYLIST")

        res = {
            "device_id": self.device_id,
            "is_rooted": True,
            "is_su_hidden": is_safe,
            "denylist_enforced": is_enforced,
            "package_in_denylist": pkg_in_list,
            "reason": reason
        }

        if is_safe:
            logger.info(f"[{self.device_id}] 🛡️ [SU 은닉 검사 통과] Magisk DenyList 활성화 및 {self.package_name} 격리 완료")
        else:
            logger.warning(f"[{self.device_id}] ⚠️ [SU 은닉 검사 실패] 사유: {reason} (enforced={is_enforced}, in_list={pkg_in_list})")

        return res

    def enforce_magisk_root_hide(self) -> bool:
        """
        [Magisk DenyList 강제 활성화 및 타겟 앱 격리 등록]
        ※ 주의: 초기화 도구(03_device_init.sh) 또는 수동 점검 전용.
        매크로 구동 중(worker_pipeline)에는 Fail-Fast 정책상 자가 수정을 수행하지 않음.
        """
        hide_script = dedent(f"""
            magisk --denylist enable
            magisk --denylist add {self.package_name} 2>/dev/null || true
            magisk --denylist add {self.package_name} {self.package_name}:channel 2>/dev/null || true
            magisk --denylist add {self.package_name} {self.package_name}:core 2>/dev/null || true
            magisk --denylist add com.google.android.gms 2>/dev/null || true
            magisk --denylist add com.google.android.gms com.google.android.gms.unstable 2>/dev/null || true
        """).strip()
        self._run_adb_su(hide_script)
        logger.info(f"[{self.device_id}] 🛡️ [Magisk DenyList] {self.package_name} / GMS 격리 등록 적용 완료")
        return True

    def enforce_wifi_location_guard(
        self,
        custom_ap_list: List[Dict[str, Any]],
        custom_lat: Optional[float] = None,
        custom_lng: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        [API 할당 무선 환경 및 지리적 위치 주입]
        WifiLocationGuard를 호출하여 API에서 수신한 AP 및 GPS 데이터를 주입하고 불변 파일시스템으로 잠금.
        """
        from src.modules.mutator.wifi_location_guard import WifiLocationGuard
        guard = WifiLocationGuard(self.device_id, self.package_name)
        return guard.inject_and_lock(custom_ap_list=custom_ap_list, custom_lat=custom_lat, custom_lng=custom_lng)

    def audit_anti_detection_status(self) -> Dict[str, Any]:
        """
        [안티 디텍션 무결성 종합 감사 (Audit)]
        단말기 현재 상태를 실측하여 위험 요소 잔존 여부를 딕셔너리로 반환.
        """
        w_scan = self._run_adb_su("settings get global wifi_scan_always_enabled").strip()
        b_scan = self._run_adb_su("settings get global ble_scan_always_enabled").strip()
        n_scan = self._run_adb_su("settings get system nearby_scanning_enabled").strip()
        
        perm_dump = self._run_adb_su(f"dumpsys package {self.package_name} | grep -E 'ACCESS_FINE_LOCATION|ACCESS_COARSE_LOCATION'")
        has_fine = "ACCESS_FINE_LOCATION: granted=true" in perm_dump
        has_coarse = "ACCESS_COARSE_LOCATION: granted=true" in perm_dump

        from src.modules.mutator.wifi_location_guard import WifiLocationGuard
        w_guard = WifiLocationGuard(self.device_id, self.package_name)
        guard_stat = w_guard.verify_guard_status()
        su_stat = self.check_su_hiding_status()

        is_safe = (
            w_scan == "0" and b_scan == "0" and n_scan == "0"
            and (not has_fine) and (not has_coarse)
            and guard_stat["is_fully_guarded"]
            and su_stat["is_su_hidden"]
        )

        audit_res = {
            "device_id": self.device_id,
            "wifi_scan_always_enabled": w_scan,
            "ble_scan_always_enabled": b_scan,
            "nearby_scanning_enabled": n_scan,
            "fine_location_granted": has_fine,
            "coarse_location_granted": has_coarse,
            "office_leak_detected": guard_stat["office_leak_detected"],
            "is_immutable_locked": guard_stat["is_immutable_locked"],
            "ap_count": guard_stat["ap_count"],
            "connected_ssid": guard_stat["connected_ssid"],
            "su_hiding_status": su_stat,
            "is_fully_sanitized": is_safe
        }

        if is_safe:
            logger.info(
                f"[{self.device_id}] ✅ [안티 디텍션 감사 통과] SU 은닉 | 위치 권한 회수 | 스캔 차단(0) | "
                f"거점 AP {guard_stat['ap_count']}개 주입 및 불변 잠금 완료"
            )
        else:
            logger.warning(f"[{self.device_id}] ⚠️ [안티 디텍션 감사 경고] 일부 설정 미흡: {audit_res}")

        return audit_res

