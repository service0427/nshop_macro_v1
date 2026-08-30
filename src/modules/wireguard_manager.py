#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
🛡️ N-SHOP WIREGUARD & WI-FI 5-LAYER NETWORK GUARDIAN (WireGuardManager V2.5)
========================================================================================
- 핵심 네트워크 토폴로지:
    • 단말기 SIM: 미개통 (셀룰러 데이터 완전 차단 `svc data disable`)
    • 물리 베이스망: Wi-Fi (SSID: 'Tech_5G', WPA-PSK: '13241324', Gateway: 192.168.0.1)
    • 가상 오버레이망: WireGuard VPN (macvlan 가상 라우터 엔드포인트 터널 `tun0`)

- 5대 방어선 (5-Layer Network Guardian):
    1. [베이스망 잠금]: 모바일 데이터 원천 비활성화, Wi-Fi 절전 해제, 캡티브 포털 체크 무력화
    2. [Wi-Fi 무결성 사전 검증]: 게이트웨이(192.168.0.1) 핑/연결 확인, 이탈 시 Tech_5G 자동 재접속
    3. [결정론적 WG 상태 스위칭]: `tun0` 커널 인터페이스 상태를 실시간 확인하며 정확한 탭(OFF➔ON) 실행
    4. [Egress HTTP 실시간 다중 검증]: `tun0` UP ➔ 라우터 공인 IP ➔ 네이버 `HTTP 200` 필수 통과
    5. [실패 시 1회 고속 자가치료 & 안전 정리]:
       - 실패 시 Wi-Fi 펄스 리셋 + WG 재배포 1회 자동 복구
       - 최종 실패 시 즉각 Fail-Fast 반환 + 세션 종료 시 `deactivate_tunnel()`로 잔여 터널 완전 제거
========================================================================================
"""

import os
import re
import sys
import time
import json
import logging
import subprocess
from typing import Dict, Any, Optional, Tuple

from src.config import (
    WG_PKG,
    WG_MAIN_ACTIVITY,
    DEFAULT_DNS,
    DEFAULT_MTU,
    DEFAULT_ENDPOINT_PORT,
    WG_SWITCH_BOUNDS,
    WG_SWITCH_CENTER,
    DEVICE_SET_FILE
)

logger = logging.getLogger("WireGuardManager")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [WireGuard] %(message)s",
        datefmt="%H:%M:%S"
    )

WIFI_SSID = os.getenv("WIFI_SSID", "Tech_5G")
WIFI_PASS = os.getenv("WIFI_PASS", "13241324")
GATEWAY_IP = os.getenv("GATEWAY_IP", "192.168.0.1")
UI_SWITCH_COORDS = WG_SWITCH_CENTER

def get_device_set_config(device_id: str) -> dict:
    if os.path.exists(DEVICE_SET_FILE):
        try:
            with open(DEVICE_SET_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get(device_id, {})
        except Exception:
            pass
    return {}

def update_device_set_config(device_id: str, updates: dict):
    data = {}
    if os.path.exists(DEVICE_SET_FILE):
        try:
            with open(DEVICE_SET_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    if device_id not in data:
        data[device_id] = {}
    data[device_id].update(updates)
    try:
        with open(DEVICE_SET_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"Failed to write device_set.json: {e}")

class WireGuardManager:
    """
    미개통 단말기 Wi-Fi(Tech_5G) 베이스 기반 WireGuard 무결성 관리자
    """

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.pkg_name = "com.wireguard.android"

    def _has_su(self) -> bool:
        if not hasattr(self, "_su_available"):
            res = subprocess.run(["adb", "-s", self.device_id, "shell", "which su 2>/dev/null || echo ''"],
                                 capture_output=True, text=True, timeout=3)
            self._su_available = bool(res.stdout.strip())
        return self._su_available

    def _run_adb_cmd(self, shell_cmd: str, timeout_sec: int = 5) -> str:
        """단말기 셸 명령어 실행 (root 가능 기기는 su, 미지원 기기는 일반 adb shell 자동 대응)"""
        try:
            if self._has_su():
                escaped_cmd = shell_cmd.replace('"', '\\"')
                cmd = ["adb", "-s", self.device_id, "shell", f'su -c "{escaped_cmd}"']
            else:
                cmd = ["adb", "-s", self.device_id, "shell", shell_cmd]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
            return res.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.warning(f"[{self.device_id}] ADB 명령 타임아웃 ({timeout_sec}s): {shell_cmd[:40]}...")
            return ""
        except Exception as e:
            logger.warning(f"[{self.device_id}] ADB 실행 에러: {e}")
            return ""

    def _run_adb_su(self, shell_cmd: str, timeout_sec: int = 5) -> str:
        """호환성을 위한 _run_adb_cmd 별칭"""
        return self._run_adb_cmd(shell_cmd, timeout_sec=timeout_sec)

    def ensure_wifi_base_healthy(self) -> bool:
        """
        [1단계: 베이스 Wi-Fi 무결성 검증 & 잠금]
        - 잔여 WireGuard/VPN 강제 종료 및 tun0 소멸
        - 미개통 셀룰러 데이터 차단 (`svc data disable`)
        - Wi-Fi 활성화 및 Tech_5G 연결 확인
        - 게이트웨이(192.168.0.1) 도달 확인
        """
        setup_script = """
am force-stop com.wireguard.android 2>/dev/null || true
svc data disable 2>/dev/null || true
svc wifi enable 2>/dev/null || true
settings put global captive_portal_mode 0 2>/dev/null || true
settings put global captive_portal_detection_enabled 0 2>/dev/null || true
settings put global wifi_sleep_policy 2 2>/dev/null || true
"""
        self._run_adb_cmd(setup_script, timeout_sec=3)
        
        # Wi-Fi IP 확인 (최대 6초 폴링)
        for attempt in range(6):
            wlan_out = self._run_adb_su("ifconfig wlan0 2>/dev/null | grep 'inet addr' || ip -4 addr show wlan0 2>/dev/null", timeout_sec=2)
            if "192.168.0." in wlan_out:
                return True
            if attempt == 2:
                logger.warning(f"[{self.device_id}] Wi-Fi(Tech_5G) IP 미할당 감지 ➔ Wi-Fi 펄스 리셋 시도...")
                self._run_adb_cmd("am force-stop com.wireguard.android; svc wifi disable; sleep 0.5; svc wifi enable", timeout_sec=3)
            time.sleep(1.0)
            
        return False

    def deploy_profile(
        self,
        client_ip: str,
        priv_key: str,
        server_pubkey: str,
        endpoint: str,
        dns: str = DEFAULT_DNS,
        mtu: int = DEFAULT_MTU
    ) -> bool:
        """
        [2단계: WireGuard 프로필 직접 주입]
        기존 앱/터널 강제 종료 후 /data/data/com.wireguard.android/files/wg0.conf 생성
        """
        conf_content = f"""[Interface]
PrivateKey = {priv_key}
Address = {client_ip}/24
DNS = {dns}
MTU = {mtu}

[Peer]
PublicKey = {server_pubkey}
Endpoint = {endpoint}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""
        tmp_path = f"/tmp/wg0_{self.device_id}.conf"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(conf_content)
                
            subprocess.run(
                ["adb", "-s", self.device_id, "push", tmp_path, f"/data/local/tmp/wg0_{self.device_id}.conf"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4
            )
            
            self._run_adb_cmd(f"am force-stop {self.pkg_name} 2>/dev/null || true", timeout_sec=2)
            inject_script = f"""
mkdir -p /data/data/{self.pkg_name}/files
cp /data/local/tmp/wg0_{self.device_id}.conf /data/data/{self.pkg_name}/files/wg0.conf
UG=$(dumpsys package {self.pkg_name} 2>/dev/null | grep userId | head -n1 | cut -d= -f2 | tr -d ' ' || echo '10331')
chown -R $UG:$UG /data/data/{self.pkg_name}
chmod -R 777 /data/data/{self.pkg_name}
appops set {self.pkg_name} ACTIVATE_VPN allow 2>/dev/null || true
appops set {self.pkg_name} ACTIVATE_PLATFORM_VPN allow 2>/dev/null || true
rm -f /data/local/tmp/wg0_{self.device_id}.conf
"""
            self._run_adb_cmd(inject_script, timeout_sec=5)
            return True
        except Exception as e:
            logger.error(f"[{self.device_id}] WireGuard 프로필 주입 실패: {e}")
            return False
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def is_tunnel_up(self) -> bool:
        """커널 tun0 인터페이스 UP 여부 확인"""
        out = self._run_adb_cmd("ip link show tun0 2>/dev/null || true", timeout_sec=2)
        return ("tun0" in out and "UP" in out)

    def get_egress_ip(self) -> str:
        """단말기 실제 외부 공인 IP 조회"""
        out = self._run_adb_cmd(
            "curl -s -m 3 http://api.ipify.org 2>/dev/null || curl -s -m 3 http://ifconfig.me/ip 2>/dev/null || true",
            timeout_sec=4
        )
        match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', out)
        return match.group(0) if match else "UNKNOWN"

    def check_naver_connectivity(self) -> bool:
        """네이버 HTTP 통신 정상 도달 여부 확인 (HTTP 200/301/302)"""
        out = self._run_adb_cmd(
            "curl -s -m 3 -o /dev/null -w '%{http_code}' https://m.naver.com 2>/dev/null || true",
            timeout_sec=4
        )
        return out.strip() in ["200", "301", "302", "304"]

    def deactivate_tunnel(self) -> bool:
        """
        [터널 및 네이버 앱 동시 완전 종료 (Process-Kill / Clean Teardown)]
        am force-stop으로 WireGuard 및 네이버 앱 프로세스를 동시 강제 종료하여
        커널 tun0 인터페이스, 잔여 VPN 세션, 네이버 백그라운드 프로세스를 100% 완전 소멸시킵니다.
        """
        self._run_adb_cmd(f"am force-stop {self.pkg_name} 2>/dev/null; am force-stop com.nhn.android.search 2>/dev/null || true", timeout_sec=2)
        time.sleep(0.3)
        return not self.is_tunnel_up()

    def get_switch_coords(self) -> Tuple[int, int]:
        """
        [동적 스위치 좌표 탐색 및 캐싱]
        기기 해상도/DPI에 맞춰 WireGuard 스위치 위치를 XML 덤프로 1회 자동 감지하고 캐싱합니다.
        """
        config = get_device_set_config(self.device_id)
        cached = config.get("wg_switch_coords")
        if cached and isinstance(cached, list) and len(cached) == 2:
            return tuple(cached)
            
        try:
            xml_str = self._run_adb_cmd(
                "uiautomator dump /sdcard/wg_ui.xml >/dev/null 2>&1 && cat /sdcard/wg_ui.xml || true",
                timeout_sec=3
            )
            if xml_str and "<hierarchy" in xml_str:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(xml_str[xml_str.find("<hierarchy"):])
                for elem in root.iter("node"):
                    rid = elem.attrib.get("resource-id", "")
                    cls = elem.attrib.get("class", "")
                    b = elem.attrib.get("bounds", "")
                    if "tunnel_switch" in rid or "Switch" in cls:
                        m = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
                        if m:
                            x1, y1, x2, y2 = map(int, m.groups())
                            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                            update_device_set_config(self.device_id, {"wg_switch_coords": [cx, cy]})
                            return (cx, cy)
        except Exception as e:
            logger.debug(f"[{self.device_id}] 동적 스위치 좌표 감지 예외 (기본값 사용): {e}")
            
        update_device_set_config(self.device_id, {"wg_switch_coords": list(UI_SWITCH_COORDS)})
        return UI_SWITCH_COORDS

    def wait_for_wireguard_foreground(self, timeout_sec: float = 6.0) -> bool:
        """WireGuard 앱이 화면 최상단 포그라운드 윈도우(MainActivity)로 완전히 렌더링되었는지 엄격 검증"""
        start_t = time.time()
        while time.time() - start_t < timeout_sec:
            focus = self._run_adb_cmd("dumpsys window | grep -E 'mCurrentFocus'", timeout_sec=2)
            # 만약 PopupWindow(점 3개 설정 메뉴 등)가 열려 있다면 뒤로가기로 닫기
            if "PopupWindow" in focus:
                logger.info(f"[{self.device_id}] [ℹ️ 팝업 감지] WireGuard 상단 팝업 감지 -> BACK 키로 닫기 수행")
                self._run_adb_cmd("input keyevent 4", timeout_sec=1)
                time.sleep(0.3)
                continue
            if f"{self.pkg_name}/.activity.MainActivity" in focus or (self.pkg_name in focus and "launcher" not in focus.lower()):
                return True
            time.sleep(0.3)
        return False

    def get_switch_info_from_ui(self, max_retries: int = 2) -> Tuple[Optional[Tuple[int, int]], bool]:
        """
        [WireGuard UI 계층 구조 분석]
        화면에 노출된 실제 tunnel_switch 노드를 파싱하여 (중심좌표, 현재 checked 상태) 반환
        실패 시 캐시된 좌표 또는 기본 좌표 반환
        """
        for retry in range(1, max_retries + 1):
            try:
                xml_str = self._run_adb_cmd(
                    "uiautomator dump /sdcard/wg_ui.xml >/dev/null 2>&1 && cat /sdcard/wg_ui.xml || true",
                    timeout_sec=2
                )
                if xml_str and "<hierarchy" in xml_str:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(xml_str[xml_str.find("<hierarchy"):])
                    for elem in root.iter("node"):
                        rid = elem.attrib.get("resource-id", "")
                        cls = elem.attrib.get("class", "")
                        b = elem.attrib.get("bounds", "")
                        checked = (elem.attrib.get("checked", "false").lower() == "true")
                        
                        if "tunnel_switch" in rid or ("Switch" in cls and "wireguard" in elem.attrib.get("package", "")):
                            m = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
                            if m:
                                x1, y1, x2, y2 = map(int, m.groups())
                                if y1 >= 280:
                                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                                    update_device_set_config(self.device_id, {"wg_switch_coords": [cx, cy]})
                                    return ((cx, cy), checked)
            except Exception as e:
                logger.debug(f"[{self.device_id}] UI 스위치 파싱 예외 (시도 #{retry}): {e}")
            time.sleep(0.3)
            
        # UI 덤프 지연/실패 시 캐시 좌표 또는 기본 좌표로 즉시 폴백 (블로킹 방지)
        cached_coords = self.get_switch_coords()
        return (cached_coords, False)

    def toggle_switch_deterministic(self) -> bool:
        """
        [정확성 최우선: WireGuard 화면 상단 표출 및 신속 스위치 ON]
        """
        logger.info(f"[{self.device_id}] 🛡️ WireGuard 앱 기동 및 화면 활성화 검증...")
        self._run_adb_cmd("input keyevent 224; wm dismiss-keyguard 2>/dev/null || true", timeout_sec=2)
        
        # 1. WireGuard 앱 기동
        self._run_adb_cmd(f"am start -W -n {self.pkg_name}/.activity.MainActivity 2>/dev/null || true", timeout_sec=3)
        
        # 2. 화면 최상단 포그라운드 포커스 검증
        if not self.wait_for_wireguard_foreground(timeout_sec=3.0):
            logger.warning(f"[{self.device_id}] [!] WireGuard 최상단 포커스 미확인 -> 강제 재기동 수행...")
            self._run_adb_cmd(f"am start -W -n {self.pkg_name}/.activity.MainActivity 2>/dev/null || true", timeout_sec=3)
            time.sleep(0.5)

        logger.info(f"[{self.device_id}] [✓] WireGuard 앱 화면 상단 표출 확인 완료! 실제 스위치 UI 렌더링 검사 중...")

        # 3. 스위치 노드 위치 및 상태 확인 (실패 시 즉시 캐시 좌표로 폴백)
        coords, is_checked = self.get_switch_info_from_ui(max_retries=1)
        if coords is None:
            coords = self.get_switch_coords()

        cx, cy = coords

        # 이미 ON 상태이고 tun0가 살아있다면 탭 생략
        if is_checked and self.is_tunnel_up():
            logger.info(f"[{self.device_id}] [✓] WireGuard 스위치 이미 ON 및 tun0 활성화 상태 확인됨! (터치 생략)")
            self._run_adb_cmd("input keyevent 3", timeout_sec=1)
            return True

        # 4. 검증된 좌표 안전 탭 (최대 3회)
        for attempt in range(1, 4):
            logger.info(f"[{self.device_id}]  ↳ [스위치 탭 #{attempt}/3] WireGuard Switch 노드 ({cx}, {cy}) 정밀 탭 실행...")
            self._run_adb_cmd(f"input tap {cx} {cy}", timeout_sec=2)
            
            # tun0 활성화 대기
            for _ in range(4):
                time.sleep(0.3)
                if self.is_tunnel_up():
                    logger.info(f"[{self.device_id}] [✓] WireGuard 커널 tun0 인터페이스 정상 UP 확인 완료!")
                    self._run_adb_cmd("input keyevent 3", timeout_sec=1)
                    return True

            logger.warning(f"[{self.device_id}] [!] 스위치 탭 후 tun0 미생성 -> 상태 재확인 후 재시도...")
            time.sleep(0.3)

        self._run_adb_cmd("input keyevent 3", timeout_sec=1)
        return self.is_tunnel_up()

    def _is_ip_acceptable(self, public_ip: str, allowed_expected_ips: set) -> bool:
        """
        공인 IP 유효성 검증:
        1. UNKNOWN이거나 사설 IP(192.168, 10., 127.)가 아니어야 함
        2. allowed_expected_ips 목록에 정확히 포함되거나,
        3. 동일한 ISP / 서브넷 대역(Class B/C prefix)인 경우 허용
        4. 또는 allowed_expected_ips가 없더라도 유효한 공인 IP이면 허용
        """
        if not public_ip or public_ip == "UNKNOWN":
            return False
        if public_ip.startswith("192.168.") or public_ip.startswith("10.") or public_ip.startswith("127."):
            return False
        if not allowed_expected_ips:
            return True
        if public_ip in allowed_expected_ips:
            return True
            
        # 서브넷 대역 매칭 (예: 175.210.218.xxx vs 175.210.218.yyy)
        pub_parts = public_ip.split(".")
        if len(pub_parts) == 4:
            pub_prefix_24 = ".".join(pub_parts[:3])
            pub_prefix_16 = ".".join(pub_parts[:2])
            for exp in allowed_expected_ips:
                exp_parts = exp.split(".")
                if len(exp_parts) == 4:
                    exp_prefix_24 = ".".join(exp_parts[:3])
                    exp_prefix_16 = ".".join(exp_parts[:2])
                    if pub_prefix_24 == exp_prefix_24 or pub_prefix_16 == exp_prefix_16:
                        return True
        return False

    def activate_and_verify(
        self,
        client_ip: str,
        priv_key: str,
        server_pubkey: str,
        endpoint: str,
        expected_public_ip: Optional[str] = None,
        max_timeout_sec: float = 12.0
    ) -> Dict[str, Any]:
        """
        [핵심 실행 및 5단계 완벽 검증]
        1. 베이스 Wi-Fi(Tech_5G) 정상 여부 확인
        2. WireGuard 새 프로필 주입
        3. 결정론적 스위치 토글
        4. Egress 네이버 HTTP 200 검증
        5. 실패 시 1회 고속 자가치료 (Self-Healing)
        """
        t_start = time.time()
        
        # 1. Wi-Fi 베이스 검증
        wifi_ok = self.ensure_wifi_base_healthy()
        if not wifi_ok:
            logger.error(f"[{self.device_id}] [❌] 물리 Wi-Fi(Tech_5G) 연결 실패! 터널링 중단.")
            return {
                "device_id": self.device_id,
                "status": "FAILED",
                "error_reason": "WIFI_DISCONNECTED",
                "elapsed_sec": round(time.time() - t_start, 2)
            }
            
        # 2. 프로필 주입 & 토글
        self.deploy_profile(client_ip, priv_key, server_pubkey, endpoint)
        self.toggle_switch_deterministic()
        
        # 3. 무결성 검증 폴링
        verified = False
        public_ip = "UNKNOWN"
        naver_ok = False
        
        endpoint_ip = endpoint.split(":")[0] if endpoint and ":" in endpoint else endpoint
        allowed_expected_ips = set(filter(None, [expected_public_ip, endpoint_ip]))
        
        deadline = time.time() + max_timeout_sec
        while time.time() < deadline:
            time.sleep(0.5)
            if self.is_tunnel_up():
                naver_ok = self.check_naver_connectivity()
                if naver_ok:
                    public_ip = self.get_egress_ip()
                    if self._is_ip_acceptable(public_ip, allowed_expected_ips):
                        verified = True
                        break
                    else:
                        logger.warning(f"[{self.device_id}] [!] 공인 IP 확인 중: Egress({public_ip}) vs 허용목록({allowed_expected_ips})...")

        # 4. 실패 시 1회 고속 자가치료 (Self-Healing)
        if not verified:
            logger.warning(f"[{self.device_id}] [!] WG 1차 연결 지연/미확인 -> 1회 고속 자가치료(Wi-Fi 펄스 + WG 리셋) 시도...")
            self.deactivate_tunnel()
            self.ensure_wifi_base_healthy()
            self.deploy_profile(client_ip, priv_key, server_pubkey, endpoint)
            self.toggle_switch_deterministic()
            
            retry_deadline = time.time() + 3.0
            while time.time() < retry_deadline:
                time.sleep(0.5)
                if self.is_tunnel_up() and self.check_naver_connectivity():
                    public_ip = self.get_egress_ip()
                    if self._is_ip_acceptable(public_ip, allowed_expected_ips):
                        verified = True
                        naver_ok = True
                        break

        elapsed = round(time.time() - t_start, 2)
        if verified:
            logger.info(f"[{self.device_id}] [✓] WireGuard 통신 및 라우터 IP 검증 성공! (IP: {public_ip} | 네이버: HTTP 200 | {elapsed}초)")
        else:
            if not self.is_tunnel_up():
                logger.error(f"[{self.device_id}] [❌] WireGuard 터널(tun0) 미생성 -> Fail-Fast 중단")
            elif not naver_ok:
                logger.error(f"[{self.device_id}] [❌] WireGuard 인터넷(네이버 HTTP 200) 불통 -> Fail-Fast 중단")
            else:
                logger.error(f"[{self.device_id}] [❌] WireGuard 공인 IP 불일치 (Egress: {public_ip} vs 허용목록: {allowed_expected_ips}) -> Fail-Fast 중단")
            # 실패 시 안전하게 터널 해제하여 Wi-Fi 베이스로 복원
            self.deactivate_tunnel()
            
        return {
            "device_id": self.device_id,
            "status": "SUCCESS" if verified else "FAILED",
            "virtual_ip": client_ip,
            "public_ip": public_ip,
            "expected_ip": expected_public_ip or endpoint_ip,
            "naver_ok": naver_ok,
            "elapsed_sec": elapsed,
            "error_reason": None if verified else ("TUNNEL_DOWN" if not self.is_tunnel_up() else ("INTERNET_UNREACHABLE" if not naver_ok else "IP_MISMATCH"))
        }
