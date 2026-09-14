#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[모듈명] OS 환경 및 디바이스 제어기 (OSEnvironmentController)
- 기능:
    1. Stdin 파이프 기반 Root(su) 안전 실행
    2. Rescue Party 무력화 (Safe Mode 방어 가드)
    3. 안티 디텍션 권한 정제 (위치 권한 영구 회수 및 안전 권한 선별 승인)
    4. 앱 UID 동적 계측
    5. GPS 스푸핑 및 Jitter 노이즈 제어
    6. 스토리지 용량 및 파일 크기 계측

----------------------------------------------------------------------------------------
[수정 및 변경 이력 (Revision History)]
----------------------------------------------------------------------------------------
- 2026-09-05:
    * [FDS 무효클릭 방어 패치] 네이버 앱의 위치 권한(ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION)
      주입을 전면 중단하고 영구 회수(pm revoke) 로직으로 전환.
    * [BSSID 유출 차단] 안드로이드 10+ 보안 규정상 위치 권한이 없으면 WifiManager가
      작업실 공유기(Tech_5G)의 실제 BSSID를 수집하지 못하고 더미 02:00:00:00:00:00을 반환함.
    * [Mock GPS 탐지 방어] classes10.dex의 isFromMockProvider 및 isMock 탐지 트리거 방어.
    * AntiDetectionGuardian 모듈과 연동하여 시스템 전역 스캔 차단(0) 동기화.
----------------------------------------------------------------------------------------
"""

import os
import re
import random
import struct
import logging
import subprocess
from textwrap import dedent
from typing import Optional, Tuple

from src.modules.anti_detection_guardian import (
    AntiDetectionGuardian,
    SAFE_RUNTIME_PERMISSIONS,
    REVOKED_DANGEROUS_PERMISSIONS
)

logger = logging.getLogger("SoftRebootMutator")

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

# 하위 호환성을 위한 런타임 권한 정의 (안전 권한으로만 구성)
RUNTIME_PERMISSIONS = SAFE_RUNTIME_PERMISSIONS


class OSEnvironmentController:
    """안드로이드 OS 레벨의 샌드박스, 권한, GPS, 스토리지 제어기"""

    def __init__(self, device_id: str, package_name: str = "com.nhn.android.search"):
        self.device_id = device_id
        self.package_name = package_name
        self.guardian = AntiDetectionGuardian(device_id, package_name)

    def run_adb_su(self, shell_cmd: str, timeout: int = 25) -> str:
        """Root(su) 권한으로 단말기 셸 명령어 실행 (stdin 파이프로 온전한 스크립트 실행)"""
        try:
            cmd = ["adb", "-s", self.device_id, "shell", "su"]
            res = subprocess.run(cmd, input=shell_cmd, capture_output=True, text=True, timeout=timeout)
            return res.stdout.strip()
        except Exception:
            return ""

    def disable_rescue_party(self):
        """
        [🛡️ 안전모드 방어 가드]
        반복 소프트 재부팅 시 안드로이드 Rescue Party가 안전모드(Safe Mode)나
        복구 화면으로 진입시키는 것을 100% 원천 차단
        """
        guard_cmd = dedent("""
            setprop persist.sys.enable_rescue false
            setprop persist.sys.disable_rescue true
            setprop sys.rescue_boot_count 0
            setprop sys.rescue_level 0
            settings put global rescue_party_disabled 1 2>/dev/null || true
            settings put global enable_rescue_party false 2>/dev/null || true
            rm -rf /data/system/users/0/rescue_party* 2>/dev/null || true
            rm -rf /data/system/rescue* 2>/dev/null || true
            rm -rf /data/system/dropbox/* 2>/dev/null || true
        """).strip()
        self.run_adb_su(guard_cmd)

    def pre_grant_permissions(self):
        """
        [안티 디텍션 가디언 기반 권한 정제 및 시스템 핑거프린트 다형성 주입]
        1. 시스템 전역 스캔 차단 (Wi-Fi, BLE, Nearby 스캔 = 0)
        2. 네이버 앱 위치 권한 영구 회수 (BSSID 및 isFromMockProvider 유출 원천 차단)
        3. 안전 권한(저장소, 미디어, 알림)만 선별 승인
        4. 화면 밝기, 폰트 스케일, 볼륨 등 환경 다형성 주입
        """
        # 1. 단말기 전역 스캔 차단
        self.guardian.enforce_device_scan_guards()

        # 2. 네이버 앱 위험 권한 회수 및 안전 권한 선별 승인
        self.guardian.sanitize_target_app_permissions()

        # 3. 시스템 환경 핑거프린트 다형성 노이즈 주입 (화면 밝기, 폰트 스케일, 볼륨) - 저전력/발열 방지 (10~35)
        rand_brightness = random.randint(10, 35)
        rand_font = random.choice(["0.95", "1.0", "1.05"])
        rand_vol = random.randint(4, 11)

        env_script = dedent(f"""
            settings put system screen_brightness {rand_brightness} 2>/dev/null || true
            settings put system font_scale {rand_font} 2>/dev/null || true
            cmd media_session volume --set {rand_vol} 2>/dev/null || true
            ime enable com.android.adbkeyboard/.AdbIME 2>/dev/null || true
            ime set com.android.adbkeyboard/.AdbIME 2>/dev/null || true
            settings put secure default_input_method com.android.adbkeyboard/.AdbIME 2>/dev/null || true
        """).strip()
        self.run_adb_su(env_script)

    def get_app_uid(self) -> str:
        """단말기 내 네이버 앱의 실제 Linux UID 동적 조회 (예: 10325, 10326, 10328, 10332)"""
        try:
            res = self.run_adb_su(f"pm list packages -U {self.package_name}")
            match = re.search(r"uid:(\d+)", res)
            if match:
                return match.group(1)
            res2 = self.run_adb_su(f"dumpsys package {self.package_name}")
            match2 = re.search(r"userId=(\d+)", res2)
            if match2:
                return match2.group(1)
        except Exception as e:
            logger.warning(f"[{self.device_id}] get_app_uid 조회 중 예외 발생: {e}")
        return "10328"

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

        self.run_adb_su("cmd appops set com.rosteam.gpsemulator MOCK_LOCATION allow; cmd appops set com.rosteam.gpsemulator POST_NOTIFICATION allow 2>/dev/null || true")
        self.run_adb_su("am start-foreground-service -n com.rosteam.gpsemulator/.servicex2484 2>/dev/null || true")
        self.run_adb_su(f"am broadcast -a com.rosteam.fakegps.MAPS_RECEIVE --ef LATITUDE {final_lat:.6f} --ef LONGITUDE {final_lng:.6f} 2>/dev/null || true")
        return final_lat, final_lng

    def get_free_storage_mb(self) -> int:
        """단말기 /data 파티션 남은 저장용량 (MB) 반환"""
        try:
            out = self.run_adb_su("df /data 2>/dev/null | tail -n 1")
            parts = out.split()
            if len(parts) >= 4:
                kb_val = int(parts[3])
                return kb_val // 1024
        except Exception:
            pass
        return 0

    def get_file_size_kb(self, remote_path: str) -> Optional[float]:
        """단말기 내 파일의 실제 크기(KB) 조회"""
        try:
            sz_out = self.run_adb_su(f"ls -l '{remote_path}' 2>/dev/null | tr -s ' ' | cut -d' ' -f5")
            if sz_out and sz_out.strip().isdigit():
                return round(int(sz_out.strip()) / 1024.0, 1)
        except Exception:
            pass
        return None

    def mutate_system_ssaid(self, target_ssaid: str) -> bool:
        """
        [안드로이드 13 ABX 원자적 SSAID 바이너리 인플레이스 변조]
        /data/system/users/0/settings_ssaid.xml의 ABX(Android Binary XML) 구조 내
        네이버 앱(com.nhn.android.search) 전용 SSAID(Android ID)를 원자적으로 교체 주입.
        NAPP_DI = MD5(SSAID)이므로 SSAID의 완전 변조는 네이버 앱 고유 식별자 전면 갱신을 보장합니다.
        """
        local_tmp = f"/tmp/ssaid_{self.device_id}.bin"
        local_patched = f"/tmp/ssaid_patched_{self.device_id}.bin"
        remote_tmp = f"/data/local/tmp/ssaid_{self.device_id}.bin"
        remote_patched = f"/data/local/tmp/ssaid_patched_{self.device_id}.bin"

        try:
            # 1. 단말기 settings_ssaid.xml 임시 복사 및 읽기 권한 개방
            self.run_adb_su(f"cp /data/system/users/0/settings_ssaid.xml {remote_tmp} && chmod 666 {remote_tmp}")
            res = subprocess.run(["adb", "-s", self.device_id, "pull", remote_tmp, local_tmp],
                                 capture_output=True, timeout=5)
            if res.returncode != 0 or not os.path.exists(local_tmp):
                logger.warning(f"[{self.device_id}] settings_ssaid.xml pull 실패")
                return False

            with open(local_tmp, "rb") as f:
                data = bytearray(f.read())

            pkg_bytes = self.package_name.encode("utf-8")
            idx = data.find(pkg_bytes)

            # 만약 settings_ssaid.xml 내 패키지 항목이 없는 경우 최초 1회 앱 기동/종료로 엔트리 생성 유도
            if idx == -1:
                logger.info(f"[{self.device_id}] settings_ssaid.xml 내 {self.package_name} 엔트리 부재 -> 1.5초 초기화 기동...")
                self.run_adb_su(f"am start -n {self.package_name}/.ui.pages.SearchHomePage; sleep 1.5; am force-stop {self.package_name}")
                self.run_adb_su(f"cp /data/system/users/0/settings_ssaid.xml {remote_tmp} && chmod 666 {remote_tmp}")
                subprocess.run(["adb", "-s", self.device_id, "pull", remote_tmp, local_tmp],
                               capture_output=True, timeout=5)
                with open(local_tmp, "rb") as f:
                    data = bytearray(f.read())
                idx = data.find(pkg_bytes)

            if idx == -1:
                logger.warning(f"[{self.device_id}] {self.package_name} SSAID 바이너리 엔트리 탐색 실패")
                return False

            # ABX 바이너리 윈도우 내 16자리 hex 문자열(value 및 defaultValue) 전수 교체
            window_start = max(0, idx - 50)
            window_end = min(len(data), idx + len(pkg_bytes) + 50)
            window = data[window_start:window_end]

            matches = list(re.finditer(rb"[0-9a-f]{16}", window))
            if not matches:
                logger.warning(f"[{self.device_id}] settings_ssaid.xml 16-hex SSAID 패턴 미매칭")
                return False

            for m in matches:
                abs_start = window_start + m.start()
                data[abs_start:abs_start+16] = target_ssaid.encode("ascii")

            with open(local_patched, "wb") as f:
                f.write(data)

            # 2. 패치된 바이너리 단말기 푸시 및 원자적 덮어쓰기
            subprocess.run(["adb", "-s", self.device_id, "push", local_patched, remote_patched],
                           capture_output=True, timeout=5)

            install_cmd = dedent(f"""\
                cp {remote_patched} /data/system/users/0/settings_ssaid.xml
                cp {remote_patched} /data/system/users/0/settings_ssaid.xml.fallback
                chown system:system /data/system/users/0/settings_ssaid.xml*
                chmod 600 /data/system/users/0/settings_ssaid.xml*
                rm -f {remote_tmp} {remote_patched}
                echo "{target_ssaid}" > /data/local/tmp/current_ssaid.txt
                settings put secure android_id {target_ssaid} 2>/dev/null || true
            """).strip()
            self.run_adb_su(install_cmd)
            logger.info(f"[{self.device_id}] [✓ ABX 바이너리 SSAID 패치 성공] -> {target_ssaid}")
            return True
        except Exception as e:
            logger.error(f"[{self.device_id}] mutate_system_ssaid 예외 발생: {e}")
            return False
        finally:
            for f in [local_tmp, local_patched]:
                if os.path.exists(f):
                    try: os.remove(f)
                    except Exception: pass

    def mutate_system_package_timestamps(self, target_install_ts: int, target_update_ts: int) -> bool:
        """
        [안드로이드 13 ABX 원자적 OS 패키지 설치/업데이트 일자 인플레이스 변조]
        1) /data/system/packages.xml ABX 바이너리 내 패키지 it (firstInstallTime), ut (lastUpdateTime) 인플레이스 교체
        2) /data/system/users/0/package-restrictions.xml ABX 바이너리 내 사용자 firstInstallTime 인플레이스 교체
        -> Zygote 소프트 리셋 시 PackageManagerService가 OS 커널/메모리에 직접 로드하여
           pm dump, getPackageInfo(), dumpsys package 등 시스템 전역에서 원천 반영.
        """
        local_pkg = f"/tmp/pkg_{self.device_id}.bin"
        local_pr = f"/tmp/pr_{self.device_id}.bin"
        remote_pkg = f"/data/local/tmp/pkg_{self.device_id}.bin"
        remote_pr = f"/data/local/tmp/pr_{self.device_id}.bin"

        try:
            # 1. 파일 임시 추출
            cmd = f"cat /data/system/packages.xml > {remote_pkg} && cat /data/system/users/0/package-restrictions.xml > {remote_pr} && chmod 666 {remote_pkg} {remote_pr}"
            self.run_adb_su(cmd)
            subprocess.run(["adb", "-s", self.device_id, "pull", remote_pkg, local_pkg], capture_output=True, timeout=5)
            subprocess.run(["adb", "-s", self.device_id, "pull", remote_pr, local_pr], capture_output=True, timeout=5)

            if not os.path.exists(local_pkg) or not os.path.exists(local_pr):
                logger.warning(f"[{self.device_id}] packages.xml / package-restrictions.xml pull 실패")
                return False

            # 2. packages.xml 패치
            with open(local_pkg, "rb") as f:
                pkg_data = bytearray(f.read())

            pkg_bytes = self.package_name.encode("utf-8")
            pos = 0
            pkg_patched = False
            while True:
                idx = pkg_data.find(pkg_bytes, pos)
                if idx == -1:
                    break
                after = pkg_data[idx+len(pkg_bytes):idx+len(pkg_bytes)+100]
                if b"/data/app" in after:
                    chunk = pkg_data[idx:idx+400]
                    ts_found = []
                    for i in range(len(chunk)-8):
                        v = struct.unpack(">Q", chunk[i:i+8])[0]
                        if 1700000000000 < v < 1900000000000:
                            if i >= 3 and chunk[i-3] == 0x9f:
                                attr_id = struct.unpack(">H", chunk[i-2:i])[0]
                                ts_found.append((idx+i, attr_id, v))
                    if len(ts_found) >= 2:
                        it_off = ts_found[0][0]
                        ut_off = ts_found[1][0]
                        pkg_data[it_off:it_off+8] = struct.pack(">Q", target_install_ts)
                        pkg_data[ut_off:ut_off+8] = struct.pack(">Q", target_update_ts)
                        pkg_patched = True
                        break
                pos = idx + len(pkg_bytes)

            # 3. package-restrictions.xml 패치
            with open(local_pr, "rb") as f:
                pr_data = bytearray(f.read())

            pr_idx = pr_data.find(pkg_bytes)
            pr_patched = False
            if pr_idx != -1:
                chunk = pr_data[pr_idx:pr_idx+200]
                for i in range(len(chunk)-8):
                    v = struct.unpack(">Q", chunk[i:i+8])[0]
                    if 1700000000000 < v < 1900000000000:
                        if i >= 3 and chunk[i-3] == 0x9f:
                            fit_off = pr_idx + i
                            pr_data[fit_off:fit_off+8] = struct.pack(">Q", target_install_ts)
                            pr_patched = True
                            break

            if not pkg_patched or not pr_patched:
                logger.warning(f"[{self.device_id}] ABX 타임스탬프 패턴 매칭 실패 (pkg: {pkg_patched}, pr: {pr_patched})")
                return False

            with open(local_pkg, "wb") as f:
                f.write(pkg_data)
            with open(local_pr, "wb") as f:
                f.write(pr_data)

            # 4. 단말기 푸시 및 원자적 덮어쓰기
            subprocess.run(["adb", "-s", self.device_id, "push", local_pkg, remote_pkg], capture_output=True, timeout=5)
            subprocess.run(["adb", "-s", self.device_id, "push", local_pr, remote_pr], capture_output=True, timeout=5)

            install_cmd = dedent(f"""\
                cp {remote_pkg} /data/system/packages.xml
                chown system:system /data/system/packages.xml && chmod 600 /data/system/packages.xml
                cp {remote_pr} /data/system/users/0/package-restrictions.xml
                chown system:system /data/system/users/0/package-restrictions.xml && chmod 600 /data/system/users/0/package-restrictions.xml
                rm -f {remote_pkg} {remote_pr}
            """).strip()
            self.run_adb_su(install_cmd)
            logger.info(f"[{self.device_id}] [✓ ABX 바이너리 시스템 패키지 설치/업데이트 일자 주입 성공] -> InstallTS: {target_install_ts} | UpdateTS: {target_update_ts}")
            return True
        except Exception as e:
            logger.error(f"[{self.device_id}] mutate_system_package_timestamps 예외 발생: {e}")
            return False
        finally:
            for f in [local_pkg, local_pr]:
                if os.path.exists(f):
                    try: os.remove(f)
                    except Exception: pass

    @staticmethod
    def generate_fake_serial() -> str:
        """
        [삼성 갤럭시 표준 11자리 가상 하드웨어 시리얼 생성]
        삼성 공장 출하 시리얼 규격:
        - 접두어: R3CR (베트남 1공장), R5CR (베트남 2공장)
        - 생산 배치 코드: 7, 8, 9, A, B, C
        - 고유 체크섬 시퀀스: 6자리 영숫자 (혼동 문자 I, O 제외)
        """
        import string
        prefix = random.choice(["R3CR", "R5CR"])
        batch = random.choice(["7", "8", "9", "A", "B", "C"])
        charset = string.digits + "ABCDEFGHJKLMNPRSTUVWXYZ"
        suffix = "".join(random.choices(charset, k=6))
        return f"{prefix}{batch}{suffix}"

    @staticmethod
    def generate_fake_ap_serial() -> str:
        """스냅드래곤 888 AP 칩셋 32-bit 고유 퓨즈 번호 가상화 (0x01 + 6자리 Hex)"""
        return f"0x01{random.randint(0x100000, 0xFFFFFF):06X}"

    def mutate_hardware_identifiers(self, custom_serial: Optional[str] = None) -> str:
        """
        [공장초기화 수준의 하드웨어 지문 가상화 및 고유 식별자 은닉]
        1. ro.serialno 및 ro.boot.serialno 가상화 (삼성 444 권한 프로퍼티 누출 차단)
        2. ro.boot.ap_serial 가상화 (퀄컴 칩셋 시리얼 스푸핑)
        3. persist.adb.wifi.guid 삭제 (단말기 실 시리얼 잔재 소거)
        4. /efs/FactoryApp/serial_no 권한 700 차단 (삼성 펌웨어 744 파일 누출 봉쇄)
        5. /sys/devices/soc0/serial_number 권한 600 차단 (AP 시리얼 누출 봉쇄)
        6. /proc/net/arp 및 /proc/net/route 권한 600 차단 (공유기 MAC / 사설 IP 노출 봉쇄)
        7. Nelo 환경 텔레메트리 싱크 차단 (/system/etc/hosts 바인드 마운트)
        """
        fake_serial = custom_serial if custom_serial else self.generate_fake_serial()
        fake_ap = self.generate_fake_ap_serial()

        hw_cmd = dedent(f"""\
            # 1. 하드웨어 프로퍼티 가상화 (Magisk resetprop)
            resetprop -n ro.serialno {fake_serial}
            resetprop -n ro.boot.serialno {fake_serial}
            resetprop -n ro.boot.ap_serial {fake_ap}
            resetprop -d persist.adb.wifi.guid 2>/dev/null || true

            # 2. 하드웨어 고유 파일 권한 강화 (일반 앱 읽기 차단 및 커널 불변 잠금)
            chattr -i /efs/FactoryApp/serial_no 2>/dev/null || true
            chmod 700 /efs/FactoryApp/serial_no 2>/dev/null || true
            chattr +i /efs/FactoryApp/serial_no 2>/dev/null || true
            chmod 600 /sys/devices/soc0/serial_number 2>/dev/null || true

            # 3. 네트워크 물리 지문 (ARP 라우터 MAC, 라우팅 테이블) 격리
            chmod 600 /proc/net/arp 2>/dev/null || true
            chmod 600 /proc/net/route 2>/dev/null || true

            # 4. Nelo 환경 텔레메트리 싱크 차단 (/system/etc/hosts 바인드 마운트)
            if ! grep -q "nelo" /system/etc/hosts 2>/dev/null; then
                cp /system/etc/hosts /data/local/tmp/hosts 2>/dev/null || true
                echo "127.0.0.1 kr-col-ext.nelo.navercorp.com" >> /data/local/tmp/hosts
                echo "127.0.0.1 nelo2-col.navercorp.com" >> /data/local/tmp/hosts
                chmod 644 /data/local/tmp/hosts
                mount -o bind /data/local/tmp/hosts /system/etc/hosts 2>/dev/null || true
            fi
        """).strip()

        self.run_adb_su(hw_cmd)
        logger.info(f"[{self.device_id}] [✓ 하드웨어 가상화 & 식별자 은닉 완료] -> Serial: {fake_serial} | AP: {fake_ap}")
        return fake_serial


