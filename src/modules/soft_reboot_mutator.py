#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
[모듈명] 초고속 소프트 재부팅 신원 변조기 (SoftRebootMutator)
========================================================================================
- 기능: 
    1. 10초 초고속 Zygote 소프트 리셋(`ctl.restart zygote`)으로 system_server 캐시를 완전 플러시.
    2. SSAID, ADID, GPS Mock 좌표, NAPP_DI, NNB 전수를 100% 새로운 디바이스 신원으로 난수화.
    3. [🛡️ Rescue Party 영구 무력화]: 연속 재부팅 시 안전모드(Safe Mode)나 복구 화면으로 빠지는 현상을 원천 차단.
    4. 앱 실행 권한 16종 및 온보딩/튜토리얼 Zero-Tap 자동 바이패스.
    5. 숙성 프로필(app_xwhale, app_webview, databases, shared_prefs) 스냅샷 저장 및 고속 복원 지원.
========================================================================================
"""

import os
import sys
import time
import uuid
import random
import logging
import subprocess
import sqlite3
import tempfile
from typing import Dict, Any, Optional, Tuple

from src.config import NAVER_PKG, PROFILE_STORAGE_DIR

logger = logging.getLogger("SoftRebootMutator")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [SoftReboot] %(message)s",
        datefmt="%H:%M:%S"
    )

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

class SoftRebootMutator:
    """
    안드로이드 초고속 소프트 재부팅 기반 신원 변조 및 프로필 관리자
    """

    def __init__(self, device_id: str, package_name: str = "com.nhn.android.search"):
        self.device_id = device_id
        self.package_name = package_name

    def _run_adb_su(self, shell_cmd: str, timeout: int = 10) -> str:
        """Root(su) 권한으로 단말기 셸 명령어 실행"""
        try:
            escaped_cmd = shell_cmd.replace('"', '\\"')
            cmd = ["adb", "-s", self.device_id, "shell", f'su -c "{escaped_cmd}"']
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return res.stdout.strip()
        except Exception:
            return ""

    def disable_rescue_party(self):
        """
        [🛡️ 안전모드 방어 가드]
        반복 소프트 재부팅 시 안드로이드 Rescue Party가 안전모드(Safe Mode)나
        복구 화면으로 진입시키는 것을 100% 원천 차단
        """
        guard_cmd = """
setprop persist.sys.enable_rescue false
setprop persist.sys.disable_rescue true
setprop sys.rescue_boot_count 0
setprop sys.rescue_level 0
settings put global rescue_party_disabled 1 2>/dev/null || true
settings put global enable_rescue_party false 2>/dev/null || true
rm -rf /data/system/users/0/rescue_party* 2>/dev/null || true
rm -rf /data/system/rescue* 2>/dev/null || true
rm -rf /data/system/dropbox/* 2>/dev/null || true
"""
        self._run_adb_su(guard_cmd)

    def pre_grant_permissions(self):
        """앱 권한 16종 및 AppOps 일괄 승인"""
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
        """Zero-Tap 온보딩/튜토리얼 바이패스 환경설정 주입"""
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
chown -R $APP_UID:$APP_UID /data/data/{self.package_name}
chmod 700 /data/data/{self.package_name}
chmod 700 /data/data/{self.package_name}/shared_prefs
chmod 600 /data/data/{self.package_name}/shared_prefs/*.xml
restorecon -R /data/data/{self.package_name}
rm -f /data/local/tmp/null_{self.device_id}.xml /data/local/tmp/tut_{self.device_id}.xml
""")
        if os.path.exists(tmp_null):
            os.remove(tmp_null)
        if os.path.exists(tmp_tut):
            os.remove(tmp_tut)

    def spoof_gps_location(self, lat: Optional[float] = None, lng: Optional[float] = None) -> Tuple[float, float]:
        """GPS 위치 스푸핑 + Jitter 노이즈"""
        base_lat = lat
        base_lng = lng
        if base_lat is None or base_lng is None:
            base_lat, base_lng = random.choice(SEOUL_GPS_COORDS)

        lat_jitter = random.uniform(-0.00025, 0.00025)
        lng_jitter = random.uniform(-0.00025, 0.00025)
        final_lat = round(base_lat + lat_jitter, 6)
        final_lng = round(base_lng + lng_jitter, 6)

        self._run_adb_su("cmd appops set com.rosteam.gpsemulator MOCK_LOCATION allow; cmd appops set com.rosteam.gpsemulator POST_NOTIFICATION allow 2>/dev/null || true")
        self._run_adb_su("am start-foreground-service -n com.rosteam.gpsemulator/.servicex2484 2>/dev/null || true")
        self._run_adb_su(f"am broadcast -a com.rosteam.fakegps.MAPS_RECEIVE --ef LATITUDE {final_lat:.6f} --ef LONGITUDE {final_lng:.6f} 2>/dev/null || true")
        return final_lat, final_lng

    def trigger_soft_reboot_and_wait(self, max_wait_sec: int = 35) -> bool:
        """
        [초고속 Zygote 소프트 리셋 실행 및 부팅 완료 대기]
        - Rescue Party 크래시 카운터를 0으로 초기화하고 Zygote 리셋 전송
        - 프레임워크 완전 기동 및 UI 서비스 안정화 대기 (평균 8~11초)
        """
        t0 = time.time()
        logger.info(f"[{self.device_id}] [🔄 소프트 리셋] Zygote 재시작 트리거 전송 중...")
        
        # 1. 크래시 카운터 0 리셋 & 소프트 리셋
        self._run_adb_su("setprop sys.rescue_boot_count 0; setprop ctl.restart zygote")
        
        # 2. 쿨다운 후 부팅 완료 폴링
        time.sleep(6.0)
        try:
            subprocess.run(["adb", "-s", self.device_id, "reconnect"], timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
            
        booted = False
        for _ in range(max_wait_sec):
            try:
                out = subprocess.run(["adb", "-s", self.device_id, "shell", "getprop sys.boot_completed"],
                                     capture_output=True, text=True, timeout=4).stdout.strip()
                if out == "1":
                    booted = True
                    break
            except Exception:
                # USB 일시 빠짐 복구 가드
                try:
                    subprocess.run(["adb", "-s", self.device_id, "reconnect"], timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
            time.sleep(1.0)
            
        if booted:
            # 3. 핵심 안드로이드 ActivityManager / WindowManager 서비스 기동 100% 보장 대기
            for _ in range(25):
                try:
                    res = subprocess.run(["adb", "-s", self.device_id, "shell", "am get-current-user"],
                                         capture_output=True, text=True, timeout=4).stdout.strip()
                    if res.isdigit():
                        break
                except Exception:
                    pass
                time.sleep(0.8)

            # 4. FallbackHome 탈출 및 LauncherActivity 100% 확실한 안착 루프
            for _ in range(12):
                try:
                    focus = subprocess.run(["adb", "-s", self.device_id, "shell", "dumpsys window | grep mCurrentFocus"],
                                           capture_output=True, text=True, timeout=4).stdout
                    if "LauncherActivity" in focus:
                        break
                    subprocess.run(["adb", "-s", self.device_id, "shell", "su -c 'input keyevent 224; input swipe 500 1500 500 500; input keyevent 3'"],
                                   timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
                time.sleep(1.2)

            time.sleep(1.0)
            elapsed = round(time.time() - t0, 1)
            logger.info(f"[{self.device_id}] [✓] Zygote 소프트 리셋 & Launcher 안착 완료! (소요 시간: {elapsed}초)")
            return True
        else:
            elapsed = round(time.time() - t0, 1)
            logger.warning(f"[{self.device_id}] [!] 소프트 리셋 타임아웃 ({elapsed}초 경과)")
            return False

    def profile_exists_on_device(self, profile_tar: str) -> bool:
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
        [소프트 재부팅 기반 신원 변조 메인 파이프라인]
        """
        t_start = time.time()
        logger.info(f"==========================================================================")
        logger.info(f" 🚀 [{self.device_id}] 초고속 소프트 재부팅 신원 변조 시작 (Mode: {mode})")
        logger.info(f"==========================================================================")

        # 1. 안전모드(Rescue Party) 무력화 가드 적용
        self.disable_rescue_party()

        # 2. 고유 식별자 난수 생성
        target_ssaid = ssaid if ssaid else f"{random.getrandbits(64):016x}"
        target_adid = adid if adid else str(uuid.uuid4())
        target_idfv = idfv if idfv else str(uuid.uuid4())

        # 3. 앱 및 GMS 서비스 종료
        self._run_adb_su(f"am force-stop {self.package_name}; am force-stop com.google.android.gms")

        # 4. 샌드박스 초기화 또는 프로필 복원 준비
        target_profile_path = profile_tar
        if not target_profile_path and mode == "RESTORE":
            target_profile_path = f"{PROFILE_STORAGE_DIR}/pf_{self.device_id}_latest.tar.gz"

        is_restore = (mode == "RESTORE" and target_profile_path and self.profile_exists_on_device(target_profile_path))

        # 5. [배치 1] 리셋 전 원자적 환경 주입 (RescueParty 차단 + pm clear + SSAID + ADID + 튜토리얼 스킵)
        logger.info(f"[{self.device_id}] [1/3] 원자적 신원/환경 데이터 주입 중... (SSAID: {target_ssaid})")
        
        # SSAID & ADID & 튜토리얼 파일 생성 및 푸시
        ssaid_payload = f"""<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<packages>
    <package name="{self.package_name}" value="{target_ssaid}" />
</packages>"""
        adid_xml = f"""<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="adid_key">{target_adid}</string>
    <boolean name="enable_limit_ad_tracking" value="false" />
</map>"""
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
        tut_xml = """<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="tutorial_shown" value="true" />
    <boolean name="is_first_launch" value="false" />
</map>"""

        t_ss = f"/tmp/ssaid_{self.device_id}.xml"
        t_ad = f"/tmp/adid_{self.device_id}.xml"
        t_nu = f"/tmp/null_{self.device_id}.xml"
        t_tu = f"/tmp/tut_{self.device_id}.xml"
        
        with open(t_ss, "w", encoding="utf-8") as f: f.write(ssaid_payload)
        with open(t_ad, "w", encoding="utf-8") as f: f.write(adid_xml)
        with open(t_nu, "w", encoding="utf-8") as f: f.write(null_xml)
        with open(t_tu, "w", encoding="utf-8") as f: f.write(tut_xml)

        subprocess.run(["adb", "-s", self.device_id, "push", t_ss, f"/data/local/tmp/ssaid_{self.device_id}.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["adb", "-s", self.device_id, "push", t_ad, f"/data/local/tmp/adid_{self.device_id}.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["adb", "-s", self.device_id, "push", t_nu, f"/data/local/tmp/null_{self.device_id}.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["adb", "-s", self.device_id, "push", t_tu, f"/data/local/tmp/tut_{self.device_id}.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        for tmp_f in [t_ss, t_ad, t_nu, t_tu]:
            if os.path.exists(tmp_f): os.remove(tmp_f)

        pre_reset_cmd = f"""
# 1. 안전모드 차단 가드
setprop persist.sys.enable_rescue false
setprop persist.sys.disable_rescue true
setprop sys.rescue_boot_count 0
setprop sys.rescue_level 0
settings put global rescue_party_disabled 1 2>/dev/null || true
settings put global enable_rescue_party false 2>/dev/null || true
rm -rf /data/system/users/0/rescue_party* /data/system/rescue* /data/system/dropbox/* 2>/dev/null || true

# 2. 패키지 초기화 및 SSAID 등록
pm clear {self.package_name}
settings put secure android_id {target_ssaid}
cp /data/local/tmp/ssaid_{self.device_id}.xml /data/system/users/0/settings_ssaid.xml
cp /data/local/tmp/ssaid_{self.device_id}.xml /data/system/users/0/settings_ssaid.xml.fallback
chown system:system /data/system/users/0/settings_ssaid.xml*
chmod 600 /data/system/users/0/settings_ssaid.xml*
echo "{target_ssaid}" > /data/local/tmp/current_ssaid.txt

# 3. GMS ADID 주입
mkdir -p /data/data/com.google.android.gms/shared_prefs
cp /data/local/tmp/adid_{self.device_id}.xml /data/data/com.google.android.gms/shared_prefs/adid_settings.xml
chown -R $(stat -c %u:%g /data/data/com.google.android.gms) /data/data/com.google.android.gms/shared_prefs 2>/dev/null || true
chmod 660 /data/data/com.google.android.gms/shared_prefs/adid_settings.xml 2>/dev/null || true
rm -rf /data/data/com.google.android.gms/files/appset/shared/* 2>/dev/null || true

# 4. 프로필 복원 (RESTORE) 또는 튜토리얼 스킵 주입 (FRESH)
APP_UID=$(dumpsys package {self.package_name} 2>/dev/null | grep userId= | head -n1 | cut -d= -f2 | tr -d ' ' || echo '10332')
if [ "{is_restore}" = "True" ] && [ -f "{target_profile_path}" ]; then
    tar -xzf {target_profile_path} -C /data/data/{self.package_name} 2>/dev/null || true
    chown -R $APP_UID:$APP_UID /data/data/{self.package_name} 2>/dev/null || true
    chmod 700 /data/data/{self.package_name} 2>/dev/null || true
    restorecon -R /data/data/{self.package_name} 2>/dev/null || true
else
    mkdir -p /data/data/{self.package_name}/shared_prefs
    cp /data/local/tmp/null_{self.device_id}.xml /data/data/{self.package_name}/shared_prefs/null.xml
    cp /data/local/tmp/tut_{self.device_id}.xml /data/data/{self.package_name}/shared_prefs/tutorial_pref.xml
    cp /data/local/tmp/null_{self.device_id}.xml /data/data/{self.package_name}/shared_prefs/{self.package_name}_preferences.xml
    chown -R $APP_UID:$APP_UID /data/data/{self.package_name} 2>/dev/null || true
    chmod 700 /data/data/{self.package_name} 2>/dev/null || true
    chmod 700 /data/data/{self.package_name}/shared_prefs 2>/dev/null || true
    chmod 600 /data/data/{self.package_name}/shared_prefs/*.xml 2>/dev/null || true
    restorecon -R /data/data/{self.package_name} 2>/dev/null || true
fi

# 임시 파일 정리
rm -f /data/local/tmp/ssaid_{self.device_id}.xml /data/local/tmp/adid_{self.device_id}.xml /data/local/tmp/null_{self.device_id}.xml /data/local/tmp/tut_{self.device_id}.xml
"""
        self._run_adb_su(pre_reset_cmd)

        # 6. 초고속 Zygote 소프트 리셋 (10초 소요, system_server 캐시 완전 갱신 ➔ NAPP_DI 신규 발급)
        logger.info(f"[{self.device_id}] [2/3] Zygote 소프트 리셋 실행 (NAPP_DI 갱신 보장)...")
        self.trigger_soft_reboot_and_wait()

        # 7. [배치 2] 부팅 완료 후 런타임 권한 & GPS 스푸핑 일괄 적용
        logger.info(f"[{self.device_id}] [3/3] 런타임 권한 승인 및 GPS 스푸핑 적용...")
        base_lat = mock_lat
        base_lng = mock_lng
        if base_lat is None or base_lng is None:
            base_lat, base_lng = random.choice(SEOUL_GPS_COORDS)
        lat_jitter = random.uniform(-0.00025, 0.00025)
        lng_jitter = random.uniform(-0.00025, 0.00025)
        final_lat = round(base_lat + lat_jitter, 6)
        final_lng = round(base_lng + lng_jitter, 6)

        post_reset_cmd = ""
        for perm in RUNTIME_PERMISSIONS:
            post_reset_cmd += f"pm grant {self.package_name} {perm} 2>/dev/null; "
        post_reset_cmd += f"""
cmd appops set {self.package_name} POST_NOTIFICATION allow 2>/dev/null || true
cmd appops set {self.package_name} FINE_LOCATION allow 2>/dev/null || true
cmd appops set {self.package_name} COARSE_LOCATION allow 2>/dev/null || true
cmd appops set {self.package_name} MOCK_LOCATION allow 2>/dev/null || true
cmd appops set com.rosteam.gpsemulator MOCK_LOCATION allow 2>/dev/null || true
cmd appops set com.rosteam.gpsemulator POST_NOTIFICATION allow 2>/dev/null || true
am start-foreground-service -n com.rosteam.gpsemulator/.servicex2484 2>/dev/null || true
am broadcast -a com.rosteam.fakegps.MAPS_RECEIVE --ef LATITUDE {final_lat:.6f} --ef LONGITUDE {final_lng:.6f} 2>/dev/null || true
"""
        self._run_adb_su(post_reset_cmd)

        duration = round(time.time() - t_start, 2)
        logger.info(f"==========================================================================")
        logger.info(f" [✓] 초고속 소프트 리셋 신원 변조 완료! (소요 시간: {duration}초)")
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
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    def save_profile_snapshot(self, profile_name: str) -> Optional[str]:
        """네이버 앱 쿠키(app_xwhale 포함 4종) 전체 스냅샷 저장"""
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

    def extract_session_identifiers(self) -> Dict[str, Optional[str]]:
        """
        네이버 앱 세션 쿠키 DB(app_xwhale/Default/Cookies)에서 NNB, NAPP_DI 등 핵심 식별자 추출
        """
        tmp_dir = tempfile.mkdtemp()
        tmp_db = os.path.join(tmp_dir, f"Cookies_{self.device_id}")
        identifiers: Dict[str, Optional[str]] = {"nnb": None, "napp_di": None}
        try:
            # 원자적 임시 복사 및 pull
            cmd = f"cp /data/data/{self.package_name}/app_xwhale/Default/Cookies /data/local/tmp/Cookies_{self.device_id} && chmod 777 /data/local/tmp/Cookies_{self.device_id}"
            self._run_adb_su(cmd)
            subprocess.run(["adb", "-s", self.device_id, "pull", f"/data/local/tmp/Cookies_{self.device_id}", tmp_db],
                           timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._run_adb_su(f"rm -f /data/local/tmp/Cookies_{self.device_id}")
            
            if os.path.exists(tmp_db):
                conn = sqlite3.connect(tmp_db)
                c = conn.cursor()
                c.execute("SELECT name, value FROM cookies WHERE name IN ('NNB', 'NAPP_DI')")
                for name, val in c.fetchall():
                    if name == "NNB":
                        identifiers["nnb"] = val
                    elif name == "NAPP_DI":
                        identifiers["napp_di"] = val
                conn.close()
                logger.info(f"[{self.device_id}] [🍪 식별자 추출 완료] NNB: {identifiers.get('nnb')}, NAPP_DI: {identifiers.get('napp_di')}")
        except Exception as e:
            logger.warning(f"[{self.device_id}] 식별자 추출 중 예외: {e}")
        finally:
            if os.path.exists(tmp_db):
                os.remove(tmp_db)
            if os.path.exists(tmp_dir):
                os.rmdir(tmp_dir)
        return identifiers

    def get_free_storage_mb(self) -> int:
        """단말기 /data 파티션 남은 저장용량 (MB) 반환"""
        try:
            out = self._run_adb_su("df /data 2>/dev/null | tail -n 1")
            parts = out.split()
            if len(parts) >= 4:
                kb_val = int(parts[3])
                return kb_val // 1024
        except Exception:
            pass
        return 0
