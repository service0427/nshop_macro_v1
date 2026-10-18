#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/device/network_controller.py

통합 네트워크 인터페이스 및 공인 IP 토글 컨트롤러
---------------------------------------------------
1. LTE 동글 모드 (LteDongleNetworkController):
   - 인터페이스: enx001e101f0000 (Huawei E3372h LTE USB 동글)
   - 중계 포트: 31411 (gnirehtet relay)
   - 토글 방식: HuaweiDongleController (모바일 데이터 껐다 켜기)
   - 특성: KT 모바일 통신망 무작위 공인 IP 순환

2. MikroTik WireGuard 모드 (MikrotikWgNetworkController):
   - 인터페이스: wg_mkt0 (Linux PC -> 원격 MikroTik WireGuard 터널)
   - 중계 포트: 31412 (gnirehtet relay)
   - 정책 라우팅: Table 51820 격리 (PC 메인 유선 이더넷 enp42s0 100% 보존, SSH 절대 끊김 없음)
   - 토글 방식: 중앙 REST API (http://114.207.112.173:5000/api/v1/device/{router_num}/toggle)
   - 특성: 파주/계산/청라 등 전국 유선 가정용 고정 회선 macvlan DHCP 공인 IP 5초 즉시 순환

3. 팩토리 함수:
   - get_network_controller(mode="lte"|"wg", router_num="001")
"""

import os
import sys
import re
import time
import json
import logging
import subprocess
import requests
import concurrent.futures
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.device.huawei_dongle_controller import HuaweiDongleController

logger = logging.getLogger("NetworkController")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class BaseNetworkController(ABC):
    """네트워크 컨트롤러 추상 기본 클래스"""

    def __init__(self, mode: str, relay_port: int, interface_name: str):
        self.mode = mode
        self.relay_port = relay_port
        # [듀얼 릴레이 아키텍처] 단일 릴레이의 16대 클라이언트 토큰 상한을 원천 돌파하기 위해 2개 포트로 분산
        self.relay_ports = [relay_port, relay_port + 1]
        self.interface_name = interface_name
        self.gnirehtet_bin = Path("/tmp/gnirehtet/gnirehtet-rust-linux64/gnirehtet")
        self.bind_so = Path("/tmp/bind_test/libbind_outbound.so")

    @abstractmethod
    def setup(self) -> bool:
        """인터페이스 및 라우팅 환경 구성"""
        pass

    @abstractmethod
    def toggle_ip(self, cycle: int = 0, max_wait: int = 25) -> Dict[str, Any]:
        """공인 IP 토글 수행 및 결과 반환"""
        pass

    @abstractmethod
    def get_public_ip(self, sample_device: Optional[str] = None, max_retries: int = 5) -> str:
        """실측 공인 IP 확인"""
        pass

    def ensure_relay_daemon(self) -> bool:
        """gnirehtet relay 데몬들(듀얼 포트)이 지정된 인터페이스 바인딩으로 실행 중인지 확인하고 부재 시 실행"""
        env = os.environ.copy()
        if self.mode != "local":
            env["BIND_INTERFACE"] = self.interface_name
            env["LD_PRELOAD"] = str(self.bind_so)

        for port in self.relay_ports:
            is_running = False
            try:
                res = subprocess.run(f"lsof -i :{port} -sTCP:LISTEN", shell=True, capture_output=True, text=True)
                if res.returncode == 0 and "gnirehtet" in res.stdout:
                    is_running = True
            except Exception:
                pass

            if is_running:
                logger.debug(f"✅ [Relay Daemon] 포트 {port}에서 gnirehtet relay 정상 가동 중")
            else:
                logger.info(f"🚀 [Relay Daemon] 포트 {port} (인터페이스: {self.interface_name}) gnirehtet relay 기동...")
                log_path = f"/tmp/gnirehtet_relay_{port}.log"
                log_f = open(log_path, "a")
                subprocess.Popen(
                    [str(self.gnirehtet_bin), "relay", "-p", str(port)],
                    env=env,
                    stdout=log_f,
                    stderr=log_f,
                    start_new_session=True
                )
        time.sleep(1.0)
        return True

    def connect_devices(self, device_ids: List[str]) -> bool:
        """단말기들을 듀얼 릴레이 포트로 균등 분산 + 순차 스태거(120ms) 터널링 + IPv6 차단 + 전수 통신 검증"""
        self.ensure_relay_daemon()
        logger.info(f"🔌 [{self.mode.upper()}] 단말기 {len(device_ids)}대 -> Relay 포트 {self.relay_ports} 분산 스태거 터널링 및 기동...")

        half = len(device_ids) // 2
        dev_to_port = {}
        for idx, dev in enumerate(device_ids):
            port = self.relay_ports[0] if idx < half else self.relay_ports[1]
            dev_to_port[dev] = port

        # 1. USB 버스 경합 및 ADB 소켓 락 방지를 위한 120ms 순차 스태거 기동
        dns_servers = "192.168.11.1,168.126.63.1,8.8.8.8" if self.mode == "lte" else "168.126.63.1,8.8.8.8"
        for dev in device_ids:
            port = dev_to_port[dev]
            # 커널 IPv6 비활성화 보장 (IPv6 드랍으로 인한 5초 DNS 타임아웃 및 '사이트에 연결할 수 없습니다' 원천 방지)
            subprocess.run(f"adb -s {dev} shell su -c 'sysctl -w net.ipv6.conf.all.disable_ipv6=1 net.ipv6.conf.default.disable_ipv6=1 >/dev/null'", shell=True, capture_output=True, timeout=5)
            # Gnirehtet 초기화 및 릴레이 소켓 바인딩 (KT/동글 DNS + Google DNS 2중 지정)
            subprocess.run(f"adb -s {dev} shell am force-stop com.genymobile.gnirehtet", shell=True, capture_output=True, timeout=5)
            subprocess.run(f"{self.gnirehtet_bin} tunnel {dev} -p {port}", shell=True, capture_output=True, timeout=5)
            subprocess.run(f"{self.gnirehtet_bin} start {dev} -d {dns_servers} -p {port}", shell=True, capture_output=True, timeout=5)
            time.sleep(0.12)

        # 2. VPN 라우팅 테이블 및 DNS 소켓 안정화 대기
        time.sleep(2.5)

        # 3. [전수 개통 자가치유 게이트] 20대 단말기 전수 병렬 네이버 접속 헬스체크 및 미개통 기기 즉각 자가치유
        def _verify_and_heal(dev):
            port = dev_to_port[dev]
            check_cmd = f"adb -s {dev} shell 'curl -sI --max-time 4 https://m.naver.com'"
            try:
                res = subprocess.run(check_cmd, shell=True, capture_output=True, text=True, timeout=6)
                if "200" in (res.stdout or ""):
                    return dev, True
            except Exception as e:
                logger.warning(f"⚠️ [{dev}] 1차 헬스체크 예외 발생: {e}")

            # 미개통 감지 시 1회 즉각 재터널링 치유 (force-stop 선행 필수)
            logger.warning(f"⚠️ [{dev}] Gnirehtet 소켓 미개통 감지 -> 즉각 재터널링 자가치유 실행...")
            try:
                subprocess.run(f"adb -s {dev} shell am force-stop com.genymobile.gnirehtet", shell=True, capture_output=True, timeout=5)
                subprocess.run(f"{self.gnirehtet_bin} tunnel {dev} -p {port}", shell=True, capture_output=True, timeout=5)
                subprocess.run(f"{self.gnirehtet_bin} start {dev} -d {dns_servers} -p {port}", shell=True, capture_output=True, timeout=5)
                time.sleep(1.5)
                res2 = subprocess.run(check_cmd, shell=True, capture_output=True, text=True, timeout=6)
                return dev, "200" in (res2.stdout or "")
            except Exception as e:
                logger.error(f"❌ [{dev}] 재터널링 자가치유 중 예외 발생: {e}")
                return dev, False

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(device_ids), 20)) as ex:
            health_results = dict(list(ex.map(_verify_and_heal, device_ids)))

        online_count = sum(1 for ok in health_results.values() if ok)
        logger.info(f"🌐 [{self.mode.upper()}] 단말기 전수 통신 검증 완료: {online_count}/{len(device_ids)}대 온라인 (200 OK)")
        return True

    def teardown(self):
        """정리 작업 (기본은 no-op)"""
        pass

    def verify_naver_connectivity(self, sample_device: Optional[str] = None, max_retries: int = 10, timeout_per_try: float = 4.0) -> Dict[str, Any]:
        """
        네이버 서버(lcs.naver.com/m)와 실시간 통신 및 정품 NNB 쿠키 정상 발급 여부 검증
        - 1단계: 지정 인터페이스(--interface {self.interface_name}) 호스트 개통 검증
        - 2단계: sample_device 단말기 실제 네이버 응답(200 OK + NNB) 교차 검증 (Gnirehtet 터널 유효성 보장)
        - HTTP 200 OK 및 13자리 정품 NNB 쿠키 수신 시에만 통신망 정상 개통 판정
        """
        ua = "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36"
        url = "https://lcs.naver.com/m"

        for attempt in range(1, max_retries + 1):
            t0 = time.time()
            try:
                cmd = (
                    f"curl -sI --interface {self.interface_name} "
                    f"-H 'User-Agent: {ua}' "
                    f"-H 'Accept: */*' "
                    f"-H 'Connection: close' "
                    f"--max-time {timeout_per_try} '{url}'"
                )
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout_per_try + 2)
                raw = res.stdout
                dur = round(time.time() - t0, 3)

                m_status = re.search(r"HTTP/\S+\s+(\d{3})", raw)
                m_nnb = re.search(r"set-cookie:\s*NNB=([A-Z0-9]+)", raw, re.IGNORECASE)
                m_buc = re.search(r"set-cookie:\s*BUC=([^;\r\n]+)", raw, re.IGNORECASE)

                status_code = int(m_status.group(1)) if m_status else 0
                nnb = m_nnb.group(1).strip() if m_nnb else ""
                buc = m_buc.group(1).strip() if m_buc else ""

                if status_code == 200 and len(nnb) == 13:
                    # 2단계: 단말기 레벨 교차 검증 (Gnirehtet 터널 및 Android VPN 개통 확인)
                    dev_nnb = ""
                    if sample_device:
                        try:
                            dev_cmd = f"adb -s {sample_device} shell \"curl -sI --max-time {timeout_per_try} '{url}'\""
                            dev_res = subprocess.run(dev_cmd, shell=True, capture_output=True, text=True, timeout=timeout_per_try + 2)
                            m_dev_nnb = re.search(r"set-cookie:\s*NNB=([A-Z0-9]+)", dev_res.stdout, re.IGNORECASE)
                            dev_nnb = m_dev_nnb.group(1).strip() if m_dev_nnb else ""
                        except Exception:
                            pass

                        if len(dev_nnb) != 13:
                            logger.warning(f"⚠️ [단말기 네이버 미개통 감지] 호스트는 성공했으나 단말기({sample_device}) NNB 미발급 -> Gnirehtet 릴레이 및 터널 재보장...")
                            self.ensure_relay_daemon()
                            subprocess.run(f"adb -s {sample_device} shell am force-stop com.genymobile.gnirehtet", shell=True, capture_output=True, timeout=5)
                            subprocess.run(f"{self.gnirehtet_bin} stop {sample_device}", shell=True, capture_output=True, timeout=5)
                            subprocess.run(f"{self.gnirehtet_bin} tunnel {sample_device} -p {self.relay_port}", shell=True, capture_output=True, timeout=5)
                            dns_servers = "192.168.11.1,168.126.63.1,8.8.8.8" if self.mode == "lte" else "168.126.63.1,8.8.8.8"
                            subprocess.run(f"{self.gnirehtet_bin} start {sample_device} -d {dns_servers} -p {self.relay_port}", shell=True, capture_output=True, timeout=5)
                            time.sleep(2.5)
                            continue

                    logger.info(f"✅ [네이버 통신 검증 성공] HTTP {status_code} | NNB={nnb} 발급 완료 (인터페이스: {self.interface_name}, 단말기: {sample_device or 'N/A'}(NNB:{dev_nnb}), 소요: {dur}s, 시도: {attempt}/{max_retries})")
                    return {
                        "success": True,
                        "status_code": status_code,
                        "nnb": nnb,
                        "buc": buc,
                        "dev_nnb": dev_nnb,
                        "dur_sec": dur,
                        "attempts": attempt
                    }
                else:
                    logger.debug(f"⏳ [네이버 통신 대기] status={status_code}, nnb={nnb} (인터페이스: {self.interface_name}, 시도: {attempt}/{max_retries})")
            except Exception as e:
                logger.debug(f"⏳ [네이버 통신 예외 대기] {e} (인터페이스: {self.interface_name}, 시도: {attempt}/{max_retries})")

            time.sleep(1.0)

        logger.warning(f"⚠️ [네이버 통신 검증 타임아웃] 인터페이스 {self.interface_name} (단말기: {sample_device or 'N/A'}) {max_retries}회 시도 실패")
        return {"success": False, "status_code": 0, "nnb": "", "buc": "", "dur_sec": 0, "attempts": max_retries}


class LteDongleNetworkController(BaseNetworkController):
    """화웨이 LTE USB 동글 네트워크 컨트롤러"""

    def __init__(self, interface_name: str = "enx001e101f0000", relay_port: int = 31411):
        super().__init__(mode="lte", relay_port=relay_port, interface_name=interface_name)
        self.dongle = HuaweiDongleController()

    def _ensure_routing_table(self):
        """테이블 11 기본 라우팅 및 정책 라우팅 규칙 자동 보장"""
        try:
            subprocess.run(f"sudo ip route replace default via 192.168.11.1 dev {self.interface_name} table 11", shell=True, capture_output=True, timeout=5)
            rules = subprocess.run("ip rule show", shell=True, capture_output=True, text=True).stdout or ""
            if f"oif {self.interface_name} lookup 11" not in rules:
                subprocess.run(f"sudo ip rule add oif {self.interface_name} table 11", shell=True, capture_output=True, timeout=5)
            if "from 192.168.11.100 lookup 11" not in rules:
                subprocess.run("sudo ip rule add from 192.168.11.100 lookup 11", shell=True, capture_output=True, timeout=5)
        except Exception as e:
            logger.warning(f"⚠️ [LTE Dongle] 라우팅 테이블 11 설정 예외: {e}")

    def setup(self) -> bool:
        logger.info(f"📡 [LTE Dongle] 환경 점검: 인터페이스 {self.interface_name}")
        self._ensure_routing_table()
        self.ensure_relay_daemon()
        return True

    def toggle_ip(self, cycle: int = 0, max_wait: int = 25) -> Dict[str, Any]:
        logger.info("📶 [LTE Dongle] 모바일 네트워크 모드 고속 토글 시작...")
        res = self.dongle.fast_toggle_ip(max_wait=max_wait)
        self._ensure_routing_table()

        # Central API 기록용 페이로드 구성
        log_payload = {
            "cycle": cycle,
            "old_ip": res.get("old_ip"),
            "new_ip": res.get("new_ip"),
            "is_ip_changed": res.get("is_ip_changed", False),
            "session_upload_bytes": res.get("session_upload_bytes", 0),
            "session_download_bytes": res.get("session_download_bytes", 0),
            "total_upload_bytes": res.get("total_upload_bytes", 0),
            "total_download_bytes": res.get("total_download_bytes", 0),
            "connect_time_seconds": res.get("connect_time_seconds", 0),
            "toggle_duration_seconds": res.get("duration_sec", 0.0),
            "status": "SUCCESS" if res.get("success") else "FAILED",
            "device_count": 20,
            "memo": f"LTE Toggle {res.get('old_ip')} -> {res.get('new_ip')}"
        }

        # 중앙 API DB에 트래픽 로그 전송
        try:
            from src.core.api_client import CentralApiClient
            from config.settings import CENTRAL_API_BASE
            client = CentralApiClient(CENTRAL_API_BASE)
            api_res = client.report_lte_log(log_payload)
            if api_res.get("success"):
                logger.info(f"💾 [LTE 트래픽 중앙 DB 기록 완료] log_id={api_res.get('log_id')}")
        except Exception as e:
            logger.warning(f"⚠️ [LTE 트래픽 중앙 DB 기록 예외] {e}")

        return {
            "success": res.get("success", False),
            "old_ip": res.get("old_ip"),
            "new_ip": res.get("new_ip"),
            "is_ip_changed": res.get("is_ip_changed", False),
            "session_upload_bytes": res.get("session_upload_bytes", 0),
            "session_download_bytes": res.get("session_download_bytes", 0),
            "total_upload_bytes": res.get("total_upload_bytes", 0),
            "total_download_bytes": res.get("total_download_bytes", 0),
            "duration_sec": res.get("duration_sec", 0),
            "mode": "lte"
        }

    def get_public_ip(self, sample_device: Optional[str] = None, max_retries: int = 6) -> str:
        """
        화웨이 LTE 동글 인터페이스(enx001e101f0000) 기준 공인 IP 확인.
        sample_device가 주어진 경우 단말기의 실제 외부 IP와도 대조 검증.
        """
        dongle_ip = "UNKNOWN"
        for _ in range(max_retries):
            for url in ["http://checkip.amazonaws.com", "http://icanhazip.com", "http://api.ipify.org"]:
                try:
                    cmd = f"curl -s --interface {self.interface_name} --max-time 3 {url}"
                    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
                    ip = res.stdout.strip()
                    if ip and len(ip.split(".")) == 4:
                        dongle_ip = ip
                        break
                except Exception:
                    pass
            if dongle_ip != "UNKNOWN":
                break
            time.sleep(1.0)

        # 단말기 실측 IP 교차 확인
        if sample_device and dongle_ip != "UNKNOWN":
            try:
                res_dev = subprocess.run(
                    f"adb -s {sample_device} shell 'curl -s -m 3 http://icanhazip.com'",
                    shell=True, capture_output=True, text=True, timeout=5
                )
                dev_ip = res_dev.stdout.strip()
                if dev_ip and dev_ip != dongle_ip:
                    logger.warning(f"⚠️ [IP 불일치 감지] LTE 동글({dongle_ip}) != 단말기 {sample_device}({dev_ip})")
            except Exception:
                pass

        return dongle_ip


class MikrotikWgNetworkController(BaseNetworkController):
    """
    MikroTik WireGuard 원격 유선 라우터 네트워크 컨트롤러
    - PC 메인 유선 이더넷(enp42s0) 100% 보존
    - 전용 정책 라우팅 테이블(51820) 격리
    - 173 중앙 REST API로 원격 라우터 5초 IP 토글
    """

    def __init__(
        self,
        router_num: str = "001",
        interface_name: str = "wg_mkt0",
        relay_port: int = 31412,
        api_base: str = "http://114.207.112.173:5000",
        table_id: int = 51820
    ):
        super().__init__(mode="wg", relay_port=relay_port, interface_name=interface_name)
        self.router_num = f"{int(router_num):03d}" if router_num.isdigit() else router_num
        self.api_base = api_base
        self.table_id = table_id
        self.client_ip = "10.8.0.2"

    def _fetch_credentials(self) -> Dict[str, str]:
        """173 서버 API 및 DB를 통해 라우터 키셋 정보 획득"""
        # 1. 서버 엔드포인트 및 공개키
        url = f"{self.api_base}/api/v1/device/{self.router_num}/keys"
        resp = requests.get(url, timeout=5).json()
        endpoint = resp.get("endpoint")
        server_pubkey = resp.get("server_public_key")

        # 2. 클라이언트 Peer-01 키셋 조회 (SSH DB 경유)
        remote_code = f"""
import pymysql, json
conn = pymysql.connect(host='localhost', user='mikr', password='Tech1324', database='mikrotik', charset='utf8mb4')
with conn.cursor(pymysql.cursors.DictCursor) as cur:
    cur.execute("SELECT client_ip, private_key, public_key FROM wg_peers WHERE device_num = '{self.router_num}' AND peer_index = 1 LIMIT 1")
    row = cur.fetchone()
    print(json.dumps(row))
conn.close()
"""
        ssh_res = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5", "tech@114.207.112.173", "python3 -"],
            input=remote_code, capture_output=True, text=True, timeout=8
        )
        peer_data = json.loads(ssh_res.stdout.strip())
        client_privkey = peer_data["private_key"]
        client_ip = peer_data["client_ip"]

        return {
            "endpoint": endpoint,
            "server_pubkey": server_pubkey,
            "client_privkey": client_privkey,
            "client_ip": client_ip
        }

    def setup(self) -> bool:
        logger.info(f"🌐 [MikroTik WG] 라우터 [{self.router_num}] WireGuard 인터페이스 ({self.interface_name}) 설정 시작...")
        creds = self._fetch_credentials()
        endpoint = creds["endpoint"]
        server_pubkey = creds["server_pubkey"]
        client_privkey = creds["client_privkey"]
        self.client_ip = creds["client_ip"]

        # 1. 기존 인터페이스 존재 여부 확인 후 재생성/재설정
        subprocess.run(f"sudo ip link del dev {self.interface_name} 2>/dev/null", shell=True)
        subprocess.run(f"sudo ip link add dev {self.interface_name} type wireguard", shell=True, check=True)
        subprocess.run(f"sudo ip addr add {self.client_ip}/24 dev {self.interface_name}", shell=True, check=True)

        key_file = f"/tmp/{self.interface_name}.key"
        with open(key_file, "w") as f:
            f.write(client_privkey + "\n")
        os.chmod(key_file, 0o600)

        # 2. WireGuard 파라미터 적용
        wg_cmd = (
            f"sudo wg set {self.interface_name} "
            f"private-key {key_file} "
            f"peer {server_pubkey} "
            f"endpoint {endpoint} "
            f"allowed-ips 0.0.0.0/0 "
            f"persistent-keepalive 25"
        )
        subprocess.run(wg_cmd, shell=True, check=True)
        try:
            os.remove(key_file)
        except Exception:
            pass

        subprocess.run(f"sudo ip link set up dev {self.interface_name}", shell=True, check=True)

        # 3. 메인 이더넷 보호를 위한 격리 정책 라우팅 적용 (Table 51820)
        subprocess.run(f"sudo ip route replace default dev {self.interface_name} table {self.table_id}", shell=True, check=True)
        # 중복 룰 정리 후 재등록
        subprocess.run(f"sudo ip rule del from {self.client_ip} table {self.table_id} 2>/dev/null", shell=True)
        subprocess.run(f"sudo ip rule del oif {self.interface_name} table {self.table_id} 2>/dev/null", shell=True)
        subprocess.run(f"sudo ip rule add from {self.client_ip} table {self.table_id}", shell=True, check=True)
        subprocess.run(f"sudo ip rule add oif {self.interface_name} table {self.table_id}", shell=True, check=True)

        # 4. 핸드셰이크 확인 (최대 5초 대기)
        time.sleep(2.0)
        test_ip = self.get_public_ip()
        logger.info(f"🎉 [MikroTik WG 연결 성공] 인터페이스: {self.interface_name} | 실측 공인 IP: {test_ip} (라우터 {self.router_num})")

        # 5. 릴레이 데몬 보장
        self.ensure_relay_daemon()
        return True

    def toggle_ip(self, cycle: int = 0, max_wait: int = 20) -> Dict[str, Any]:
        """중앙 API를 통한 MikroTik MACVLAN 고속 공인 IP 토글"""
        url = f"{self.api_base}/api/v1/device/{self.router_num}/toggle"
        t0 = time.time()
        logger.info(f"🔄 [MikroTik WG] 라우터 [{self.router_num}] 공인 IP 즉시 토글 API 호출 중...")
        try:
            resp = requests.get(url, timeout=max_wait)
            data = resp.json()
            dur = data.get("duration_sec", round(time.time() - t0, 2))
            new_ip = data.get("new_ip")
            old_ip = data.get("old_ip")
            success = data.get("success", False)

            if success:
                logger.info(f"✅ [MikroTik WG 토글 완료] {old_ip} -> {new_ip} (소요: {dur}초)")
                # 통신 정상화 대기
                self._wait_for_egress_normalization(new_ip, max_wait=10)
                return {
                    "success": True,
                    "old_ip": old_ip,
                    "new_ip": new_ip,
                    "duration_sec": dur,
                    "mode": "wg"
                }
            else:
                logger.error(f"❌ [MikroTik WG 토글 실패] 응답: {data}")
                return {"success": False, "error": str(data), "duration_sec": dur, "mode": "wg"}
        except Exception as e:
            logger.error(f"❌ [MikroTik WG 토글 예외] {e}")
            return {"success": False, "error": str(e), "duration_sec": round(time.time() - t0, 2), "mode": "wg"}

    def _wait_for_egress_normalization(self, expected_ip: Optional[str] = None, max_wait: int = 10):
        """토글 직후 WireGuard 터널을 통한 아웃바운드 통신이 정상 복구될 때까지 확인"""
        t_start = time.time()
        while time.time() - t_start < max_wait:
            curr_ip = self.get_public_ip(max_retries=1)
            if curr_ip != "UNKNOWN":
                if not expected_ip or curr_ip == expected_ip:
                    logger.info(f"🌐 [네트워크 통신 정상화 확인] 터널 실측 공인 IP: {curr_ip} (대기: {time.time() - t_start:.1f}s)")
                    return True
            time.sleep(0.5)
        logger.warning("⚠️ [네트워크 정상화 타임아웃 경고] 다음 사이클 진행")
        return False

    def get_public_ip(self, sample_device: Optional[str] = None, max_retries: int = 5) -> str:
        for _ in range(max_retries):
            try:
                cmd = f"curl -s --interface {self.interface_name} --max-time 4 https://api.ipify.org"
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
                ip = res.stdout.strip()
                if ip and len(ip.split(".")) == 4:
                    return ip
            except Exception:
                pass
            time.sleep(0.5)
        return "UNKNOWN"


class LocalNetworkController(BaseNetworkController):
    """
    PC 메인 유선 이더넷(enp42s0) 네트워크 컨트롤러
    ---------------------------------------------
    - 인터페이스: enp42s0 (PC 메인 유선 이더넷)
    - 중계 포트: 31413 (gnirehtet relay)
    - IP 토글: 불필요 (메인 이더넷 고정 공인 IP 유지, --no-toggle 기본 적용)
    - 용도: LTE 동글 없이도 호스트 유선 통신망을 통한 초고속 테스트 및 검증
    """

    def __init__(self, interface_name: str = "enp42s0", relay_port: int = 31413):
        super().__init__(mode="local", relay_port=relay_port, interface_name=interface_name)

    def setup(self) -> bool:
        logger.info(f"🏠 [Local Ethernet] 환경 점검: 인터페이스 {self.interface_name} (Relay Port: {self.relay_port})")
        self.ensure_relay_daemon()
        return True

    def toggle_ip(self, cycle: int = 0, max_wait: int = 25) -> Dict[str, Any]:
        """메인 유선 이더넷은 공인 IP를 변경하지 않고 현재 IP 유지"""
        curr_ip = self.get_public_ip()
        logger.info(f"🏠 [Local Ethernet] 메인 유선 이더넷 고정 IP 유지 (IP: {curr_ip}, IP 토글 생략)")
        return {
            "success": True,
            "old_ip": curr_ip,
            "new_ip": curr_ip,
            "is_ip_changed": False,
            "duration_sec": 0.0,
            "mode": "local",
            "memo": f"Local Ethernet Fixed IP ({curr_ip})"
        }

    def get_public_ip(self, sample_device: Optional[str] = None, max_retries: int = 5) -> str:
        for _ in range(max_retries):
            try:
                cmd = f"curl -s --interface {self.interface_name} --max-time 4 https://api.ipify.org"
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
                ip = res.stdout.strip()
                if ip and len(ip.split(".")) == 4:
                    return ip
            except Exception:
                pass
            time.sleep(0.5)
        return "UNKNOWN"


def get_network_controller(mode: str = "lte", router_num: str = "001") -> BaseNetworkController:
    """네트워크 컨트롤러 팩토리"""
    mode = mode.lower().strip()
    if mode in ("wg", "wireguard", "mikrotik"):
        return MikrotikWgNetworkController(router_num=router_num)
    elif mode in ("local", "ethernet", "eth", "main"):
        return LocalNetworkController()
    else:
        return LteDongleNetworkController()
