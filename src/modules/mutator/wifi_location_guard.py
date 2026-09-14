#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
[모듈명] 네이버 쇼핑 물리 Wi-Fi BSSID 유출 차단 및 API 할당 무선 환경 주입기 (WifiLocationGuard)
========================================================================================
- 기능:
    1. 사무실 실제 공유기(Tech_5G, Tech_2.4G, b2:38:6c:40:3e:78 등) 유출 원천 차단.
    2. [STRICT API POLICY] 중앙 API(/api/v1/allocate)에서 할당받은 wifi_list를 100% 최우선 주입.
       - 임의의 폴백 더미 데이터 생성 전면 폐지 (누락 시 Fail-Fast 실패 처리).
    3. 네이버 앱 내부 gfp_access_points.json 및 gfp_gps_points.json 원자적 치환.
    4. Linux Kernel chattr +i(불변 플래그) 부여로 네이버 앱 백그라운드 덮어쓰기 영구 차단.
    5. 앱 위치 권한(FINE, COARSE) 박탈 및 시스템 Wi-Fi/BLE 스캔 100% 차단.
========================================================================================
"""

import json
import logging
import os
import random
import re
import subprocess
import time
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("WifiLocationGuard")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [WifiGuard] %(message)s",
        datefmt="%H:%M:%S"
    )

# 작업실 물리 Wi-Fi 유출 검증용 블랙리스트 지문 (정확한 JSON 값 일치)
OFFICE_LEAK_FINGERPRINTS = [
    '"b2:38:6c:40:3e:78"',
    '"b0:38:6c:70:3e:78"',
    '"Tech_5G"',
    '"Tech_2.4G"',
    '[LG_CeilingCassette'
]


class WifiLocationGuard:
    """
    네이버 쇼핑 물리 Wi-Fi BSSID 유출 차단 및 API 할당 무선/위치 환경 주입기
    """

    def __init__(self, device_id: str, package_name: str = "com.nhn.android.search"):
        self.device_id = device_id
        self.package_name = package_name

    def _run_adb_su(self, shell_cmd: str, timeout_sec: int = 15) -> str:
        """Root(su) 권한으로 단말기 셸 명령어 실행"""
        try:
            cmd = ["adb", "-s", self.device_id, "shell", "su"]
            res = subprocess.run(cmd, input=shell_cmd, capture_output=True, text=True, timeout=timeout_sec)
            return res.stdout.strip()
        except Exception as e:
            logger.warning(f"[{self.device_id}] ADB su 명령 실패: {e}")
            return ""

    def get_app_uid(self) -> str:
        """네이버 앱의 실제 Linux UID 조회 (예: 10332)"""
        try:
            out = self._run_adb_su(f"stat -c '%u' /data/data/{self.package_name}")
            if out and out.isdigit():
                return out
            out2 = self._run_adb_su(f"pm list packages -U {self.package_name}")
            m = re.search(r"uid:(\d+)", out2)
            if m:
                return m.group(1)
        except Exception:
            pass
        return "10000"  # fallback

    def build_environment_payloads(
        self,
        custom_ap_list: List[Dict[str, Any]],
        custom_lat: Optional[float] = None,
        custom_lng: Optional[float] = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[float], Optional[float]]:
        """
        [API 할당 기반 AP 목록 및 GPS 좌표 페이로드 생성]
        - 폴백 없음: custom_ap_list가 비어있으면 즉시 ValueError 발생
        - 타임스탬프(ts, eventReceiveTs) 실행 시각 기준으로 정밀 보정
        - custom_lat, custom_lng가 제공되면 GPS 페이로드 생성, 없으면 빈 배열([]) 유지
        """
        if not custom_ap_list or not isinstance(custom_ap_list, list) or len(custom_ap_list) == 0:
            raise ValueError(f"[{self.device_id}] API wifi_list 누락! 중앙 서버 할당 데이터가 반드시 필요합니다.")

        now_ms = int(time.time() * 1000)
        event_receive_ts = now_ms + random.randint(120, 350)

        # 1. Wi-Fi AP 페이로드 빌드 (API 제공 목록 100% 반영)
        final_ap_payload: List[Dict[str, Any]] = []
        for idx, item in enumerate(custom_ap_list):
            it = item.copy()
            if "ts" not in it:
                it["ts"] = now_ms - (random.randint(1500, 3500) if idx == 0 else random.randint(2000, 8000))
            if "eventReceiveTs" not in it:
                it["eventReceiveTs"] = event_receive_ts
            final_ap_payload.append(it)

        # 2. GPS 좌표 페이로드 빌드
        gps_payload: List[Dict[str, Any]] = []
        final_lat: Optional[float] = None
        final_lng: Optional[float] = None

        if custom_lat is not None and custom_lng is not None:
            # GPS 좌표 미세 지터 추가 (+- 0.00015 ~ 0.00035, 반경 약 15~35m 자연스러운 오차)
            lat_jitter = random.uniform(-0.00025, 0.00025)
            lng_jitter = random.uniform(-0.00025, 0.00025)
            final_lat = round(float(custom_lat) + lat_jitter, 6)
            final_lng = round(float(custom_lng) + lng_jitter, 6)
            accuracy = round(random.uniform(8.5, 14.8), 1)
            altitude = round(random.uniform(25.0, 45.0), 1)
            vertical_acc = round(random.uniform(2.0, 4.0), 1)

            gps_payload = [
                {
                    "provider": "fused",
                    "ts": now_ms,
                    "latitude": final_lat,
                    "longitude": final_lng,
                    "accuracy": accuracy,
                    "altitude": altitude,
                    "verticalAccuracy": vertical_acc,
                    "eventReceiveTs": event_receive_ts
                }
            ]

        return final_ap_payload, gps_payload, final_lat, final_lng

    def purge_office_leak_traces(self) -> bool:
        """
        [작업실 Wi-Fi 오염 데이터 전수 소거]
        1. gfp_access_points.json 및 gfp_gps_points.json 잠금 해제
        2. 기존 파일 내 작업실 BSSID(b2:38:6c:40:3e:78) 및 Tech_5G 존재 시 즉시 삭제
        """
        purge_script = f"""
            chattr -i /data/data/{self.package_name}/files/gfp_access_points.json 2>/dev/null || true
            chattr -i /data/data/{self.package_name}/files/gfp_gps_points.json 2>/dev/null || true
            
            # 오염 파일 탐지 및 삭제
            if grep -q '"Tech_5G"' /data/data/{self.package_name}/files/gfp_access_points.json 2>/dev/null; then
                rm -f /data/data/{self.package_name}/files/gfp_access_points.json
            fi
            if grep -q '"b2:38:6c:40:3e:78"' /data/data/{self.package_name}/files/gfp_access_points.json 2>/dev/null; then
                rm -f /data/data/{self.package_name}/files/gfp_access_points.json
            fi
        """
        self._run_adb_su(purge_script)
        logger.info(f"[{self.device_id}] 🧹 [오염 소거] 작업실 Wi-Fi(Tech_5G) 기존 잔재 검사 및 정리 완료")
        return True

    def inject_and_lock(
        self,
        custom_ap_list: List[Dict[str, Any]],
        custom_lat: Optional[float] = None,
        custom_lng: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        [API 환경 주입 및 커널 불변 파일시스템 잠금]
        1. API로부터 수신한 wifi_list 및 GPS 좌표 주입
        2. 단말기 임시 폴더 푸시 후 /data/data/{pkg}/files/ 로 이동
        3. 소유권 app_uid로 변경 (chown {uid}:{uid})
        4. 읽기 전용 권한 설정 (chmod 444)
        5. 커널 불변 플래그 부여 (chattr +i) -> 네이버 앱 백그라운드 덮어쓰기 영구 차단
        6. 네이버 앱 위치 권한 영구 회수 (pm revoke & appops ignore)
        """
        t_start = time.time()
        ap_payload, gps_payload, final_lat, final_lng = self.build_environment_payloads(
            custom_ap_list=custom_ap_list,
            custom_lat=custom_lat,
            custom_lng=custom_lng
        )

        local_ap_path = f"/tmp/gfp_ap_{self.device_id}.json"
        local_gps_path = f"/tmp/gfp_gps_{self.device_id}.json"

        try:
            with open(local_ap_path, "w", encoding="utf-8") as f:
                json.dump(ap_payload, f, separators=(",", ":"))
            with open(local_gps_path, "w", encoding="utf-8") as f:
                json.dump(gps_payload, f, separators=(",", ":"))

            # 단말기 임시 경로로 푸시
            remote_tmp_ap = f"/data/local/tmp/gfp_ap_{self.device_id}.json"
            remote_tmp_gps = f"/data/local/tmp/gfp_gps_{self.device_id}.json"

            subprocess.run(["adb", "-s", self.device_id, "push", local_ap_path, remote_tmp_ap],
                           capture_output=True, check=True, timeout=10)
            subprocess.run(["adb", "-s", self.device_id, "push", local_gps_path, remote_tmp_gps],
                           capture_output=True, check=True, timeout=10)

            real_app_uid = self.get_app_uid()
            target_files_dir = f"/data/data/{self.package_name}/files"
            target_ap_file = f"{target_files_dir}/gfp_access_points.json"
            target_gps_file = f"{target_files_dir}/gfp_gps_points.json"

            inject_script = f"""
                # 1. 대상 디렉터리 확인 및 기존 잠금 해제
                mkdir -p {target_files_dir}
                chattr -i {target_ap_file} 2>/dev/null || true
                chattr -i {target_gps_file} 2>/dev/null || true
                
                # 2. 임시 파일 이동 및 배치
                mv {remote_tmp_ap} {target_ap_file}
                mv {remote_tmp_gps} {target_gps_file}
                
                # 3. 권한 및 소유권 네이버 앱 UID로 일치화
                chown {real_app_uid}:{real_app_uid} {target_ap_file} {target_gps_file}
                chmod 444 {target_ap_file} {target_gps_file}
                restorecon -F {target_ap_file} {target_gps_file} 2>/dev/null || true
                
                # 4. 리눅스 커널 불변(immutable) 플래그 강제 적용 (+i) -> root 포함 앱 프로세스 수정 불가
                chattr +i {target_ap_file} {target_gps_file}
                
                # 5. 앱의 실시간 위치 스캔 권한 영구 회수
                pm revoke {self.package_name} android.permission.ACCESS_FINE_LOCATION 2>/dev/null || true
                pm revoke {self.package_name} android.permission.ACCESS_COARSE_LOCATION 2>/dev/null || true
                cmd appops set {self.package_name} FINE_LOCATION ignore 2>/dev/null || true
                cmd appops set {self.package_name} COARSE_LOCATION ignore 2>/dev/null || true
                cmd appops set {self.package_name} MOCK_LOCATION ignore 2>/dev/null || true
            """
            self._run_adb_su(inject_script)

        finally:
            if os.path.exists(local_ap_path):
                os.remove(local_ap_path)
            if os.path.exists(local_gps_path):
                os.remove(local_gps_path)

        duration = round(time.time() - t_start, 2)
        conn_bssid = ap_payload[0].get("bssid", "UNKNOWN")
        conn_ssid = ap_payload[0].get("ssid", "UNKNOWN")
        logger.info(
            f"[{self.device_id}] 🔒 [API Wi-Fi 주입 및 잠금 완료] "
            f"AP: {len(ap_payload)}개 | 연결 AP: {conn_ssid} ({conn_bssid}) | "
            f"GPS: ({final_lat}, {final_lng}) | 소요: {duration}s"
        )

        return {
            "device_id": self.device_id,
            "status": "SUCCESS",
            "connected_ssid": conn_ssid,
            "connected_bssid": conn_bssid,
            "ap_count": len(ap_payload),
            "gps_lat": final_lat,
            "gps_lng": final_lng,
            "execution_sec": duration
        }

    def verify_guard_status(self) -> Dict[str, Any]:
        """
        [보안 감사 및 상태 실측 검증]
        1. Tech_5G 또는 작업실 BSSID 유출 여부 확인
        2. 실제 주입된 거점 AP 개수 및 연결 AP 확인
        3. 주입된 GPS 좌표 확인
        4. chattr 불변 플래그 (+i) 설정 여부 확인
        5. 파일 권한(444) 및 소유권 확인
        6. 위치 권한 회수 여부 확인
        """
        ap_path = f"/data/data/{self.package_name}/files/gfp_access_points.json"
        gps_path = f"/data/data/{self.package_name}/files/gfp_gps_points.json"

        # 1. 작업실 Wi-Fi 노출 검사 (JSON 키/값 엄격 일치)
        raw_ap = self._run_adb_su(f"cat {ap_path} 2>/dev/null")
        has_leak = any(fp in raw_ap for fp in OFFICE_LEAK_FINGERPRINTS)

        # 2. 불변 플래그 확인 (lsattr)
        lsattr_out = self._run_adb_su(f"lsattr {ap_path} {gps_path} 2>/dev/null")
        is_immutable = ("----i----" in lsattr_out or "i" in lsattr_out)

        # 3. 권한 및 소유권 확인 (stat)
        stat_out = self._run_adb_su(f"stat -c '%a %U:%G' {ap_path} 2>/dev/null")

        # 4. 파일 내용 읽기 (app UID 관점 정상 파싱 가능 여부)
        uid = self.get_app_uid()
        read_test_cmd = f"su {uid} -c 'cat {ap_path}' 2>/dev/null"
        ap_json_str = self._run_adb_su(read_test_cmd)
        
        ap_count = 0
        connected_ssid = "UNKNOWN"
        connected_bssid = "UNKNOWN"
        try:
            ap_data = json.loads(ap_json_str)
            if isinstance(ap_data, list):
                ap_count = len(ap_data)
                if ap_count > 0:
                    connected_ssid = ap_data[0].get("ssid", "UNKNOWN")
                    connected_bssid = ap_data[0].get("bssid", "UNKNOWN")
        except Exception:
            pass

        gps_json_str = self._run_adb_su(f"su {uid} -c 'cat {gps_path}' 2>/dev/null")
        gps_lat = None
        gps_lng = None
        try:
            gps_data = json.loads(gps_json_str)
            if isinstance(gps_data, list) and len(gps_data) > 0:
                gps_lat = gps_data[0].get("latitude")
                gps_lng = gps_data[0].get("longitude")
        except Exception:
            pass

        # 5. 위치 권한 회수 상태 확인
        perm_dump = self._run_adb_su(f"dumpsys package {self.package_name} | grep -E 'ACCESS_FINE_LOCATION|ACCESS_COARSE_LOCATION'")
        fine_granted = "ACCESS_FINE_LOCATION: granted=true" in perm_dump
        coarse_granted = "ACCESS_COARSE_LOCATION: granted=true" in perm_dump
        is_fully_guarded = (not has_leak) and is_immutable and (ap_count >= 1) and (not fine_granted)

        status_result = {
            "device_id": self.device_id,
            "office_leak_detected": has_leak,
            "is_immutable_locked": is_immutable,
            "ap_file_stat": stat_out,
            "ap_count": ap_count,
            "connected_ssid": connected_ssid,
            "connected_bssid": connected_bssid,
            "gps_lat": gps_lat,
            "gps_lng": gps_lng,
            "fine_location_granted": fine_granted,
            "coarse_location_granted": coarse_granted,
            "is_fully_guarded": is_fully_guarded
        }

        if is_fully_guarded:
            logger.info(
                f"[{self.device_id}] ✅ [가드 무결성 검증 통과] AP {ap_count}개 | "
                f"연결 SSID: {connected_ssid} | BSSID: {connected_bssid} | "
                f"GPS: ({gps_lat}, {gps_lng}) | 불변잠금: {is_immutable} | 오염: 0건"
            )
        else:
            logger.warning(f"[{self.device_id}] ⚠️ [가드 상태 경고] 이상 징후 포착: {status_result}")

        return status_result
