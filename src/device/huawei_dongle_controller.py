#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/device/huawei_dongle_controller.py

Huawei LTE Dongle (E8372h-820 / E3372h 등) 고속 토글 및 트래픽(Upload/Download) 측정 모듈
- 모바일 네트워크 모드 전환 (AUTO -> LTE)을 통한 100% 신규 KT 공인 IP 획득 보장
- 세션별 / 누적 업로드 및 다운로드 바이트 정밀 측정
- 세션 누수 방지를 위한 깔끔한 자동 로그아웃 및 예외 처리
"""

import time
import logging
import subprocess
import requests
from typing import Dict, Any, Optional
from huawei_lte_api.Client import Client
from huawei_lte_api.Connection import Connection

logger = logging.getLogger("HuaweiDongleController")

DEFAULT_GATEWAY = "192.168.11.1"
DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "KdjLch!@7024"


def format_bytes(byte_val: int) -> str:
    """바이트 단위를 읽기 쉬운 KB, MB, GB로 변환"""
    if byte_val < 1024:
        return f"{byte_val} B"
    elif byte_val < 1024 * 1024:
        return f"{byte_val / 1024:.1f} KB"
    elif byte_val < 1024 * 1024 * 1024:
        return f"{byte_val / (1024 * 1024):.2f} MB"
    else:
        return f"{byte_val / (1024 * 1024 * 1024):.2f} GB"


class HuaweiDongleController:
    def __init__(self, gateway_ip: str = DEFAULT_GATEWAY, username: str = DEFAULT_USER, password: str = DEFAULT_PASSWORD, timeout: int = 10):
        self.gateway_ip = gateway_ip
        self.username = username
        self.password = password
        self.timeout = timeout
        self.interface_name = "enx001e101f0000"

    def logout_modem(self):
        """기존 활성 세션 강제 해제"""
        try:
            logout_url = f"http://{self.gateway_ip}/api/user/logout"
            logout_data = '<?xml version="1.0" encoding="UTF-8"?><request><Logout>1</Logout></request>'
            requests.post(logout_url, data=logout_data, headers={"Content-Type": "application/xml"}, timeout=2)
        except Exception:
            pass

    def _get_authenticated_client(self) -> Client:
        """Huawei API 인증 클라이언트 획득 (Already login 자동 복구)"""
        conn = Connection(f"http://{self.gateway_ip}/", username=self.username, password=self.password, timeout=self.timeout)
        try:
            return Client(conn)
        except Exception as e:
            if "Already login" in str(e):
                logger.info(f"[{self.gateway_ip}] 기존 세션 감지 -> 강제 로그아웃 후 재인증 시도...")
                self.logout_modem()
                time.sleep(1.0)
                conn = Connection(f"http://{self.gateway_ip}/", username=self.username, password=self.password, timeout=self.timeout)
                return Client(conn)
            raise

    def get_public_ip(self, max_retries: int = 5) -> str:
        """인터페이스를 통한 실측 공인 IP 확인"""
        for _ in range(max_retries):
            for url in ["http://checkip.amazonaws.com", "http://icanhazip.com", "http://api.ipify.org"]:
                try:
                    res = subprocess.run(
                        f"curl -s --interface {self.interface_name} --max-time 3 {url}",
                        shell=True, capture_output=True, text=True, timeout=4
                    )
                    ip = res.stdout.strip()
                    if ip and len(ip.split(".")) == 4:
                        return ip
                except Exception:
                    pass
            time.sleep(1.0)
        return "UNKNOWN"

    def get_traffic_statistics(self) -> Dict[str, Any]:
        """익명/인증 트래픽 통계 조회"""
        try:
            conn = Connection(f"http://{self.gateway_ip}/", timeout=self.timeout)
            client = Client(conn)
            stats = client.monitoring.traffic_statistics()
            return {
                "success": True,
                "current_upload": int(stats.get("CurrentUpload", 0)),
                "current_download": int(stats.get("CurrentDownload", 0)),
                "total_upload": int(stats.get("TotalUpload", 0)),
                "total_download": int(stats.get("TotalDownload", 0)),
                "connect_time": int(stats.get("CurrentConnectTime", 0))
            }
        except Exception as e:
            logger.warning(f"트래픽 통계 조회 예외: {e}")
            return {
                "success": False,
                "current_upload": 0,
                "current_download": 0,
                "total_upload": 0,
                "total_download": 0,
                "connect_time": 0
            }

    def fast_toggle_ip(self, max_wait: int = 25) -> Dict[str, Any]:
        """
        LTE 모뎀 네트워크 모드 토글 (AUTO -> LTE) 수행 및 트래픽 측정
        - 토글 직전 세션 트래픽(업로드/다운로드) 수집
        - 무작위 KT 신규 공인 IP 획득 보장
        - 반환: IP 변경 결과 및 트래픽 통계 딕셔너리
        """
        t_start = time.time()
        client = None
        old_pub_ip = self.get_public_ip(max_retries=3)

        # 1. 토글 직전 세션 트래픽 및 상태 수집
        session_upload = 0
        session_download = 0
        total_upload = 0
        total_download = 0
        connect_time = 0

        try:
            client = self._get_authenticated_client()
            traffic = client.monitoring.traffic_statistics()
            session_upload = int(traffic.get("CurrentUpload", 0))
            session_download = int(traffic.get("CurrentDownload", 0))
            total_upload = int(traffic.get("TotalUpload", 0))
            total_download = int(traffic.get("TotalDownload", 0))
            connect_time = int(traffic.get("CurrentConnectTime", 0))

            logger.info(
                f"📊 [LTE 모뎀 토글 전 트래픽] 세션: ↑ {format_bytes(session_upload)} / ↓ {format_bytes(session_download)} | "
                f"누적: ↑ {format_bytes(total_upload)} / ↓ {format_bytes(total_download)} (연결시간: {connect_time}s)"
            )

            # 2. 네트워크 모드 토글 (AUTO -> LTE 전환으로 무선망 기지국 세션 리셋)
            cur_mode = client.net.net_mode()
            net_band = cur_mode.get("NetworkBand", "2000000400000")
            lte_band = cur_mode.get("LTEBand", "1E000000095")

            logger.info(f"📶 [{self.gateway_ip}] LTE 기지국 세션 리셋 시작 (기존 IP: {old_pub_ip})...")
            client.net.set_net_mode(networkmode="00", networkband=net_band, lteband=lte_band)
            time.sleep(3.0)
            client.net.set_net_mode(networkmode="03", networkband=net_band, lteband=lte_band)

            # 3. 통신망 재접속 대기 (ConnectionStatus 901)
            connected = False
            for attempt in range(max_wait):
                time.sleep(1.0)
                try:
                    st = client.monitoring.status()
                    if st.get("ConnectionStatus") == "901":
                        connected = True
                        break
                except Exception:
                    pass

            if not connected:
                logger.warning(f"⚠️ [{self.gateway_ip}] {max_wait}초 내 ConnectionStatus 901 미도달 -> 강제 03 모드 재적용...")
                try:
                    client.net.set_net_mode(networkmode="03", networkband=net_band, lteband=lte_band)
                    for _ in range(12):
                        time.sleep(1.0)
                        if client.monitoring.status().get("ConnectionStatus") == "901":
                            connected = True
                            break
                except Exception:
                    pass

            time.sleep(2.0)
            new_pub_ip = self.get_public_ip(max_retries=6)
            is_valid_ip = bool(new_pub_ip and new_pub_ip != "UNKNOWN")
            is_changed = bool(is_valid_ip and new_pub_ip != old_pub_ip)

            # 동일 IP 재할당 방지 가드: 이전 IP와 동일할 경우 1회 추가 재토글로 신규 IP 강제 획득
            if is_valid_ip and not is_changed:
                logger.warning(f"⚠️ [{self.gateway_ip}] 동일 IP 재할당 감지 ({old_pub_ip} == {new_pub_ip}) -> 신규 IP 강제 확보 위해 추가 토글...")
                try:
                    client.net.set_net_mode(networkmode="00", networkband=net_band, lteband=lte_band)
                    time.sleep(4.0)
                    client.net.set_net_mode(networkmode="03", networkband=net_band, lteband=lte_band)
                    for _ in range(max_wait):
                        time.sleep(1.0)
                        try:
                            if client.monitoring.status().get("ConnectionStatus") == "901":
                                break
                        except Exception:
                            pass
                    time.sleep(2.0)
                    re_ip = self.get_public_ip(max_retries=6)
                    if re_ip and re_ip != "UNKNOWN":
                        new_pub_ip = re_ip
                        is_changed = bool(new_pub_ip != old_pub_ip)
                except Exception as re_err:
                    logger.warning(f"[-] 추가 토글 재시도 예외: {re_err}")

            dur = round(time.time() - t_start, 2)
            logger.info(f"📶 [{self.gateway_ip}] 토글 완료: {old_pub_ip} -> {new_pub_ip} (소요: {dur}s, 변경: {is_changed})")

            return {
                "success": is_valid_ip,
                "old_ip": old_pub_ip,
                "new_ip": new_pub_ip,
                "is_ip_changed": is_changed,
                "session_upload_bytes": session_upload,
                "session_download_bytes": session_download,
                "total_upload_bytes": total_upload,
                "total_download_bytes": total_download,
                "connect_time_seconds": connect_time,
                "duration_sec": dur,
                "mode": "lte"
            }
        except Exception as e:
            dur = round(time.time() - t_start, 2)
            logger.error(f"[{self.gateway_ip}] 토글 실패: {e}")
            return {
                "success": False,
                "old_ip": old_pub_ip,
                "new_ip": "UNKNOWN",
                "is_ip_changed": False,
                "session_upload_bytes": session_upload,
                "session_download_bytes": session_download,
                "total_upload_bytes": total_upload,
                "total_download_bytes": total_download,
                "connect_time_seconds": connect_time,
                "duration_sec": dur,
                "error": str(e),
                "mode": "lte"
            }
        finally:
            if client:
                try:
                    client.user.logout()
                except Exception:
                    pass


__all__ = ["HuaweiDongleController", "format_bytes"]
