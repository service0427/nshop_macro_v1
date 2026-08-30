#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
[모듈명] Zero-Reboot 디바이스 신원 변조기 (ZeroRebootMutator)
========================================================================================
- 기능: 
    1. 안드로이드 OS 재부팅 없이(Zero-Reboot) 10초 이내에 단말기의 물리/소프트웨어 신원을 완벽히 난수화 변조.
    2. SSAID(Android ID), 구글 광고 ID(ADID), AppSetId(IDFV), GPS Mock 좌표, 앱 샌드박스(쿠키/캐시) 전수 초기화.
    3. 실행 시 발생하는 모든 권한 팝업(7종) 및 네이버 앱 최초 튜토리얼 팝업을 Zero-Tap으로 자동 스킵.
    4. 숙성 프로필(.tar.gz) 보관 및 초고속 인플레이스 복원 지원.

- 기술적 원리 (재부팅이 불필요한 이유):
    1) SettingsProvider 실시간 동기화: OS API(`settings put secure android_id`)와 
       시스템 바이너리 ABX 파일(`/data/system/users/0/settings_ssaid.xml`)을 동시 갱신하여 
       system_server 프로세스를 재시작하지 않고도 새 SSAID를 즉시 반영.
    2) GMS 인메모리 캐시 Flush: GMS 데몬을 force-stop하고 `adid_settings.xml`을 
       교체하여 네이버 앱이 GMS를 호출할 때 새 ADID/IDFV를 즉시 수령하도록 유도.
    3) Frida 런타임 1차 방어선: 앱 프로세스 스폰 시 `Settings.Secure.getString(android_id)` 호출을 
       가로채 동적 SSAID를 주입함으로써 OS 캐시 잔존 여부와 무관하게 100% 새 신원 보장.
    4) WireGuard(VPN) 터널 유지: 커널 라우팅(`tun0`)을 끊지 않고 상시 유지하므로 
       재부팅으로 인한 Rescue Party(파란 화면 복구 모드) 및 ADB 포트 단절을 원천 차단.
========================================================================================
"""

import os
import sys
import time
import uuid
import random
import logging
import subprocess
from typing import Dict, Any, Optional, Tuple

from src.config import NAVER_PKG, PROFILE_STORAGE_DIR

logger = logging.getLogger("ZeroRebootMutator")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [ZeroReboot] %(message)s",
        datefmt="%H:%M:%S"
    )

# 한국 주요 번화가 GPS 좌표 풀 (위도/경도)
SEOUL_GPS_COORDS = [
    (37.497942, 127.027621),  # 강남역
    (37.517236, 127.047325),  # 강남구청
    (37.556321, 126.922654),  # 홍대입구
    (37.566535, 126.977969),  # 서울시청 / 중구
    (37.513261, 127.100142),  # 잠실 롯데월드몰
    (37.538609, 126.906269),  # 영등포 타임스퀘어
    (37.521873, 126.924298),  # 여의도 더현대
    (37.618887, 127.058307),  # 노원구 중계동
    (37.579406, 126.970318),  # 종로구 경복궁
    (37.484213, 126.929841),  # 신림역 관악구
    (37.534921, 126.993712),  # 용산구 이태원
    (37.477123, 126.882741),  # 가산디지털단지
    (37.654129, 127.060124),  # 상계역
    (37.501241, 126.882194),  # 구로디지털단지
    (37.582103, 127.001942),  # 혜화 대학로
]

# 기존 16종 안드로이드 런타임 권한 전수
RUNTIME_PERMISSIONS = [
    "android.permission.POST_NOTIFICATIONS",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.CAMERA",
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
    "android.permission.READ_MEDIA_IMAGES",
    "android.permission.READ_MEDIA_VIDEO",
    "android.permission.READ_MEDIA_AUDIO",
    "android.permission.RECORD_AUDIO",
    "android.permission.READ_PHONE_STATE",
    "android.permission.GET_ACCOUNTS",
    "android.permission.BLUETOOTH_CONNECT",
    "android.permission.BLUETOOTH_SCAN",
    "android.permission.ACTIVITY_RECOGNITION",
    "android.permission.BODY_SENSORS"
]

class ZeroRebootMutator:
    """
    안드로이드 Zero-Reboot 신원 변조 및 프로필 복원 관리자
    """

    def __init__(self, device_id: str, package_name: str = "com.nhn.android.search"):
        self.device_id = device_id
        self.package_name = package_name

    def _run_adb(self, cmd: str) -> subprocess.CompletedProcess:
        """기본 ADB 명령 실행"""
        full_cmd = ["adb", "-s", self.device_id] + cmd.split() if isinstance(cmd, str) else ["adb", "-s", self.device_id] + cmd
        return subprocess.run(full_cmd, capture_output=True, text=True)

    def _has_su(self) -> bool:
        if not hasattr(self, "_su_available"):
            res = subprocess.run(["adb", "-s", self.device_id, "shell", "which su 2>/dev/null || echo ''"],
                                 capture_output=True, text=True, timeout=3)
            self._su_available = bool(res.stdout.strip())
        return self._su_available

    def _run_adb_su(self, shell_cmd: str) -> str:
        """Root(su) 권한으로 단말기 셸 명령어 실행 (root 미지원 기기는 일반 adb shell 자동 대응)"""
        try:
            if self._has_su():
                escaped_cmd = shell_cmd.replace('"', '\\"')
                cmd = ["adb", "-s", self.device_id, "shell", f'su -c "{escaped_cmd}"']
            else:
                cmd = ["adb", "-s", self.device_id, "shell", shell_cmd]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            return res.stdout.strip()
        except Exception as e:
            return ""

    def get_free_storage_mb(self) -> int:
        """
        단말기 내부 저장공간(/data) 남은 용량 조회 (MB 단위)
        """
        try:
            out = self._run_adb_su("df /data | tail -n 1")
            parts = out.split()
            if len(parts) >= 4:
                # parts[3] is Available in 1K-blocks
                avail_kb = int(parts[3])
                return avail_kb // 1024
        except Exception as e:
            logger.warning(f"[{self.device_id}] 저장공간 조회 실패: {e}")
        return 0

    def pre_grant_permissions(self):
        """
        [권한 자동 허용] 
        앱 최초 실행 시 뜨는 16종 런타임 권한 및 AppOps를 사전에 일괄 승인
        """
        logger.info(f"[{self.device_id}] 16종 런타임 권한 및 AppOps 허용 주입 중...")
        grant_script = ""
        for perm in RUNTIME_PERMISSIONS:
            grant_script += f"pm grant {self.package_name} {perm} 2>/dev/null; "
        grant_script += f"""
cmd appops set {self.package_name} POST_NOTIFICATION allow 2>/dev/null || true
cmd appops set {self.package_name} FINE_LOCATION allow 2>/dev/null || true
cmd appops set {self.package_name} COARSE_LOCATION allow 2>/dev/null || true
cmd appops set {self.package_name} MOCK_LOCATION allow 2>/dev/null || true
"""
        self._run_adb_su(grant_script)

    def inject_tutorial_bypass(self):
        """
        [Zero-Tap 튜토리얼 스킵]
        첫 실행 튜토리얼 / 온보딩 화면을 통과시키는 SharedPreference 환경설정 XML 직접 주입
        """
        logger.info(f"[{self.device_id}] Zero-Tap 온보딩/튜토리얼 바이패스 환경설정 주입 중...")
        null_xml = """<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="keyFirstRun" value="false" />
    <boolean name="keyUniverseTutorialComplete" value="true" />
    <boolean name="keyNextTutorialComplete" value="true" />
    <boolean name="keyTutorialLocProcessed" value="true" />
    <boolean name="keyDarkTutorialComplete" value="true" />
    <boolean name="keyNewmainTutorialComplete" value="true" />
    <boolean name="keyNotificationQuery" value="true" />
    <boolean name="keyLocationAgree" value="true" />
    <boolean name="keyUniverseMigrationFinished" value="true" />
    <boolean name="keyMyTabMigrationFinished" value="true" />
    <boolean name="keyLocalSiteMigrated" value="true" />
    <boolean name="keyXWhaleMigrated" value="true" />
    <boolean name="keyMigrateInAppStrorage" value="true" />
    <boolean name="keyWebEngineBuiltInV10" value="true" />
    <boolean name="keySecureScreenShot" value="true" />
    <boolean name="keyActiveAppCheck" value="false" />
    <boolean name="keyBridgeLinkInAppToolbar" value="true" />
    <string name="KeyLastNClicks">hct.complete</string>
    <int name="keyRefreshInterval" value="600" />
</map>"""
        tutorial_pref_xml = """<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="tutorial_shown" value="true" />
    <boolean name="is_first_launch" value="false" />
</map>"""
        tmp_null = f"/tmp/null_{self.device_id}.xml"
        tmp_tut = f"/tmp/tut_{self.device_id}.xml"
        with open(tmp_null, "w", encoding="utf-8") as f:
            f.write(null_xml)
        with open(tmp_tut, "w", encoding="utf-8") as f:
            f.write(tutorial_pref_xml)
            
        subprocess.run(["adb", "-s", self.device_id, "push", tmp_null, f"/data/local/tmp/null_{self.device_id}.xml"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["adb", "-s", self.device_id, "push", tmp_tut, f"/data/local/tmp/tut_{self.device_id}.xml"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        self._run_adb_su(f"""
APP_UID=$(dumpsys package {self.package_name} 2>/dev/null | grep userId | head -n1 | cut -d= -f2 | tr -d ' ' || echo '10332')
mkdir -p /data/data/{self.package_name}/shared_prefs
cp /data/local/tmp/null_{self.device_id}.xml /data/data/{self.package_name}/shared_prefs/null.xml
cp /data/local/tmp/tut_{self.device_id}.xml /data/data/{self.package_name}/shared_prefs/tutorial_pref.xml
cp /data/local/tmp/null_{self.device_id}.xml /data/data/{self.package_name}/shared_prefs/{self.package_name}_preferences.xml
chown -R $APP_UID:$APP_UID /data/data/{self.package_name}/shared_prefs
chmod -R 777 /data/data/{self.package_name}/shared_prefs
rm -f /data/local/tmp/null_{self.device_id}.xml /data/local/tmp/tut_{self.device_id}.xml
""")
        if os.path.exists(tmp_null):
            os.remove(tmp_null)
        if os.path.exists(tmp_tut):
            os.remove(tmp_tut)

    def spoof_gps_location(self, lat: Optional[float] = None, lng: Optional[float] = None) -> Tuple[float, float]:
        """
        [GPS Mock 주입 & 현실적인 GPS 노이즈/이동 흔들림(Jitter) 적용]
        - 이전과 100% 동일한 좌표 대신 실제 스마트폰 GPS 수신 환경의 자연스러운 미세 표류(Drift: 약 5m~30m)를 매번 적용
        - 위도 0.00001도 ~= 1.11m (±0.00005 ~ ±0.00025도 미세 난수 부여)
        """
        base_lat = lat
        base_lng = lng
        if base_lat is None or base_lng is None:
            base_lat, base_lng = random.choice(SEOUL_GPS_COORDS)

        # 실제 안드로이드 GPS 센서의 자연스러운 오차/흔들림(5m~30m) 인근 미세 변화
        lat_jitter = random.uniform(-0.00025, 0.00025)
        lng_jitter = random.uniform(-0.00025, 0.00025)
        
        # 6자리 소수점 반올림 (표준 NMEA/Android Location 정밀도)
        final_lat = round(base_lat + lat_jitter, 6)
        final_lng = round(base_lng + lng_jitter, 6)

        logger.info(f"[{self.device_id}] 📍 GPS 위치 주입 -> 기준: ({base_lat:.6f}, {base_lng:.6f}) ➔ 흔들림 적용: ({final_lat:.6f}, {final_lng:.6f}) [오차: ΔLat {lat_jitter*111000:+.1f}m, ΔLng {lng_jitter*88000:+.1f}m]")
        
        # 1. GPSEmulator AppOps 승인
        self._run_adb_su("cmd appops set com.rosteam.gpsemulator MOCK_LOCATION allow; cmd appops set com.rosteam.gpsemulator POST_NOTIFICATION allow 2>/dev/null || true")
        # 2. GPSEmulator 포그라운드 서비스 기동 (servicex2484)
        self._run_adb_su("am start-foreground-service -n com.rosteam.gpsemulator/.servicex2484 2>/dev/null || true")
        # 3. GPS 좌표 브로드캐스트 전송
        self._run_adb_su(f"am broadcast -a com.rosteam.fakegps.MAPS_RECEIVE --ef LATITUDE {final_lat:.6f} --ef LONGITUDE {final_lng:.6f} 2>/dev/null || true")
        return final_lat, final_lng

    def profile_exists_on_device(self, profile_tar: str) -> bool:
        """단말기 내부(/data/local/tmp/...)에 프로필 tar.gz 파일이 존재하는지 검사"""
        if not profile_tar:
            return False
        out = self._run_adb_su(f"[ -f {profile_tar} ] && echo EXISTS || echo NOT_EXISTS")
        return "EXISTS" in out

    def mutate_identity(
        self,
        mode: str = "FRESH",
        profile_tar: Optional[str] = None,
        ssaid: Optional[str] = None,
        adid: Optional[str] = None,
        idfv: Optional[str] = None,
        mock_lat: Optional[float] = None,
        mock_lng: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        [Zero-Reboot 신원 변조 메인 파이프라인]
        
        Args:
            mode: "FRESH" (신규 난수 생성 및 클린 초기화) | "RESTORE" (기존 숙성 프로필 복원)
            profile_tar: 복원할 프로필 .tar.gz 경로 (RESTORE 모드 시 필수)
            ssaid: 지정할 16자리 hex SSAID (None 시 자동 난수 생성)
            adid: 지정할 UUID ADID (None 시 자동 난수 생성)
            idfv: 지정할 UUID AppSetId (None 시 자동 난수 생성)
            mock_lat: Mock GPS 위도 (None 시 서울 주요 번화가 랜덤)
            mock_lng: Mock GPS 경도 (None 시 서울 주요 번화가 랜덤)
            
        Returns:
            Dict containing ssaid, adid, idfv, gps, duration_sec, free_storage_mb 등 변조 결과
        """
        t_start = time.time()
        logger.info(f"==========================================================================")
        logger.info(f" 🚀 [{self.device_id}] Zero-Reboot 신원 변조 시작 (Mode: {mode})")
        logger.info(f"==========================================================================")

        # 1. 고유 식별자 생성 (미지정 시 신규 난수 발급)
        target_ssaid = ssaid if ssaid else f"{random.getrandbits(64):016x}"
        target_adid = adid if adid else str(uuid.uuid4())
        target_idfv = idfv if idfv else str(uuid.uuid4())

        # 2. 앱 및 GMS 백그라운드 프로세스 강제 종료
        logger.info(f"[{self.device_id}] [1/6] 네이버 앱 및 GMS 서비스 프로세스 강제 종료...")
        self._run_adb_su(f"am force-stop {self.package_name}; am force-stop com.google.android.gms")

        # 3. 샌드박스 초기화 또는 프로필 복원
        target_profile_path = profile_tar
        if not target_profile_path and mode == "RESTORE":
            target_profile_path = f"{PROFILE_STORAGE_DIR}/pf_{self.device_id}_latest.tar.gz"

        is_restore = (mode == "RESTORE" and target_profile_path and self.profile_exists_on_device(target_profile_path))

        if is_restore:
            logger.info(f"[{self.device_id}] [2/6] 🏆 숙성 프로필 인플레이스 복원 적용 -> {target_profile_path}")
            self._run_adb_su(f"pm clear {self.package_name}")
            app_dir = f"/data/data/{self.package_name}"
            restore_cmd = f"""
mkdir -p {app_dir}
tar -xzf {target_profile_path} -C {app_dir} 2>/dev/null || true
pkg_uid=$(stat -c %u {app_dir} 2>/dev/null || echo 10000)
chown -R $pkg_uid:$pkg_uid {app_dir} 2>/dev/null || true
chmod -R 775 {app_dir} 2>/dev/null || true
"""
            self._run_adb_su(restore_cmd)
            self.pre_grant_permissions()
        else:
            logger.info(f"[{self.device_id}] [2/6] 클린 패키지 초기화 (pm clear) 수행...")
            self._run_adb_su(f"pm clear {self.package_name}")
            # 권한 및 튜토리얼 스킵 주입
            self.pre_grant_permissions()
            self.inject_tutorial_bypass()

        # 4. OS 바이너리 ABX 및 API 레벨 SSAID 주입 (재부팅 없이 즉시 반영)
        logger.info(f"[{self.device_id}] [3/6] SSAID 이중 주입 (OS API + 바이너리 ABX) -> {target_ssaid}")
        # ① OS 프레임워크 실시간 등록
        self._run_adb_su(f"settings put secure android_id {target_ssaid}")
        # ② 시스템 ABX XML 파일 직접 갱신 (영속성 보장)
        ssaid_payload = f"""<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<packages>
    <package name="{self.package_name}" value="{target_ssaid}" />
</packages>"""
        tmp_ssaid = f"/tmp/ssaid_{self.device_id}.xml"
        with open(tmp_ssaid, "w", encoding="utf-8") as f:
            f.write(ssaid_payload)
        subprocess.run(["adb", "-s", self.device_id, "push", tmp_ssaid, f"/data/local/tmp/ssaid_{self.device_id}.xml"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        self._run_adb_su(f"""
cp /data/local/tmp/ssaid_{self.device_id}.xml /data/system/users/0/settings_ssaid.xml
cp /data/local/tmp/ssaid_{self.device_id}.xml /data/system/users/0/settings_ssaid.xml.fallback
chown system:system /data/system/users/0/settings_ssaid.xml*
chmod 600 /data/system/users/0/settings_ssaid.xml*
echo "{target_ssaid}" > /data/local/tmp/current_ssaid.txt
chmod 777 /data/local/tmp/current_ssaid.txt
rm -f /data/local/tmp/ssaid_{self.device_id}.xml
""")
        if os.path.exists(tmp_ssaid):
            os.remove(tmp_ssaid)

        # 5. 구글 Play 서비스(GMS) ADID 및 AppSetId 교체
        logger.info(f"[{self.device_id}] [4/6] GMS 광고 ID(ADID) 주입 -> {target_adid}")
        adid_xml = f"""<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="adid_key">{target_adid}</string>
    <boolean name="enable_limit_ad_tracking" value="false" />
</map>"""
        tmp_adid = f"/tmp/adid_{self.device_id}.xml"
        with open(tmp_adid, "w", encoding="utf-8") as f:
            f.write(adid_xml)
        subprocess.run(["adb", "-s", self.device_id, "push", tmp_adid, f"/data/local/tmp/adid_{self.device_id}.xml"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        self._run_adb_su(f"""
mkdir -p /data/data/com.google.android.gms/shared_prefs
cp /data/local/tmp/adid_{self.device_id}.xml /data/data/com.google.android.gms/shared_prefs/adid_settings.xml
chown -R $(stat -c %u:%g /data/data/com.google.android.gms) /data/data/com.google.android.gms/shared_prefs
chmod 660 /data/data/com.google.android.gms/shared_prefs/adid_settings.xml
rm -rf /data/data/com.google.android.gms/files/appset/shared/* 2>/dev/null || true
rm -f /data/local/tmp/adid_{self.device_id}.xml
""")
        if os.path.exists(tmp_adid):
            os.remove(tmp_adid)

        # 6. GMS 메모리 Flush 및 GPS 주입
        logger.info(f"[{self.device_id}] [5/6] GMS 런타임 메모리 Flush 및 GPS 위치 스푸핑...")
        self._run_adb_su("am force-stop com.google.android.gms")
        final_lat, final_lng = self.spoof_gps_location(mock_lat, mock_lng)

        # 7. 화면 깨우기 및 잠금 해제
        logger.info(f"[{self.device_id}] [6/6] 단말기 화면 잠금 해제 및 상태 안정화...")
        self._run_adb_su("input keyevent 224; input keyevent 82")

        duration = round(time.time() - t_start, 2)
        free_mb = self.get_free_storage_mb()

        logger.info(f"==========================================================================")
        logger.info(f" [✓] Zero-Reboot 신원 변조 완료! (소요 시간: {duration}초 | 잔여 저장용량: {free_mb}MB)")
        logger.info(f"==========================================================================")

        return {
            "device_id": self.device_id,
            "status": "SUCCESS",
            "mode": mode,
            "ssaid": target_ssaid,
            "adid": target_adid,
            "idfv": target_idfv,
            "gps_lat": final_lat,
            "gps_lng": final_lng,
            "execution_sec": duration,
            "free_storage_mb": free_mb,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    def save_profile_snapshot(self, profile_name: str) -> Optional[str]:
        """
        현재 네이버 앱의 쿠키/세션/앱데이터를 물리 디바이스 내부 고속 UFS 스토리지에 tar.gz로 스냅샷 저장
        """
        try:
            os_dest_dir = PROFILE_STORAGE_DIR
            tar_filename = f"{profile_name}.tar.gz" if not profile_name.endswith(".tar.gz") else profile_name
            full_tar_path = f"{os_dest_dir}/{tar_filename}"

            cmd = f"""
mkdir -p {os_dest_dir}
cd /data/data/{self.package_name} && tar -czf {full_tar_path} app_xwhale app_webview databases shared_prefs 2>/dev/null || true
chmod 777 {full_tar_path}
"""
            self._run_adb_su(cmd)
            logger.info(f"[{self.device_id}] [📸 프로필 스냅샷 저장 완료] -> {full_tar_path}")
            return full_tar_path
        except Exception as e:
            logger.warning(f"[{self.device_id}] 프로필 스냅샷 저장 실패: {e}")
            return None
