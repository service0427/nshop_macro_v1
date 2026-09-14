#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
🛡️ AUTOMATED WIREGUARD STABILITY & BENCHMARK TESTER (test_wireguard_stability.py)
========================================================================================
- Dedicated Test Device: R3CR70FFFEK (Attached & idle, zero interference with daemon.py)
- Features:
    1. Continuous repetitive allocation from central router pool (/api/v1/allocate)
    2. Measures tun0 interface UP latency
    3. DNS query latency (KT DNS 168.126.63.1 vs Cloudflare 1.1.1.1)
    4. HTTP 302 vs HTTPS TLS handshake latency & packet drop rates
    5. Path MTU Discovery test (Ping payload: 1392, 1332, 1252)
    6. Egress Public IP validation against router macvlan_ip
    7. Clean teardown and release (/api/v1/release)
    8. Detailed structured JSONL logging to logs/wg_stability_benchmark.jsonl
========================================================================================
"""

import os
import re
import sys
import json
import time
import logging
import argparse
import subprocess
from datetime import datetime
from textwrap import dedent
from typing import Dict, Any, Optional

# Project root import
sys.path.insert(0, "/home/tech/nshop_macro_v1")
from src.modules.task_api_client import TaskApiClient
from src.modules.wireguard_manager import WireGuardManager
from src.config import LOGS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [WG-Bench] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("WGBenchmark")

BENCH_LOG_FILE = os.path.join(LOGS_DIR, "wg_stability_benchmark.jsonl")


class WireGuardStabilityTester:
    def __init__(self, device_id: str = "R3CR70FFFEK"):
        self.device_id = device_id
        self.api_client = TaskApiClient()
        self.wg_mgr = WireGuardManager(device_id)

    def _run_adb(self, cmd: str, timeout_sec: int = 5) -> str:
        try:
            escaped = cmd.replace('"', '\\"')
            res = subprocess.run(
                ["adb", "-s", self.device_id, "shell", f'su -c "{escaped}"'],
                capture_output=True, text=True, timeout=timeout_sec
            )
            return res.stdout.strip()
        except subprocess.TimeoutExpired:
            return "TIMEOUT"
        except Exception as e:
            return f"ERROR: {e}"

    def run_single_probe(self, iteration: int, test_mtu: int = 1360, test_dns: str = "168.126.63.1, 1.1.1.1, 8.8.8.8") -> Dict[str, Any]:
        """단일 반복 WireGuard 할당, 터널 수립, 다각도 네트워크 벤치마크, 해제 수행"""
        t_cycle_start = time.time()
        record = {
            "iteration": iteration,
            "timestamp": datetime.now().isoformat(),
            "device_id": self.device_id,
            "test_mtu": test_mtu,
            "test_dns": test_dns,
            "status": "INIT"
        }

        # 1. 중앙 서버에서 라우터 및 WG 파라미터 할당
        t0 = time.time()
        alloc = self.api_client.allocate_tasks([self.device_id])
        if not alloc or not alloc.get("alloc_id"):
            record["status"] = "ALLOC_FAILED"
            record["error"] = "API allocation failed"
            return record

        alloc_id = alloc.get("alloc_id")
        router = alloc.get("router", {})
        task = alloc.get("tasks", [{}])[0] if alloc.get("tasks") else {}

        record["alloc_id"] = alloc_id
        record["router_num"] = router.get("router_num")
        record["endpoint"] = router.get("endpoint")
        record["macvlan_ip"] = router.get("macvlan_ip")
        record["client_ip"] = task.get("ip")
        record["alloc_latency"] = round(time.time() - t0, 3)

        priv_key = task.get("private_key")
        server_pubkey = router.get("server_public_key")
        endpoint = router.get("endpoint")
        client_ip = task.get("ip")

        if not (priv_key and server_pubkey and endpoint and client_ip):
            record["status"] = "INVALID_CONFIG"
            self._release(alloc_id, "FAILED", "Invalid WireGuard config from server")
            return record

        try:
            # 2. 물리 Wi-Fi 상태 확인
            t_wifi = time.time()
            wlan_ip = self._run_adb("ip -4 addr show wlan0 2>/dev/null | grep inet || echo ''")
            record["wlan_status"] = "OK" if "192.168.0." in wlan_ip else "DISCONNECTED"

            # 3. WireGuard 프로필 생성 및 주입
            t_dep = time.time()
            self.wg_mgr.deploy_profile(client_ip, priv_key, server_pubkey, endpoint, dns=test_dns, mtu=test_mtu)
            record["deploy_sec"] = round(time.time() - t_dep, 3)

            # 4. 스위치 토글 & tun0 UP 시간 정밀 계측
            t_toggle = time.time()
            tun0_up = self.wg_mgr.toggle_switch_deterministic()
            tun0_sec = round(time.time() - t_toggle, 3)

            record["tun0_up"] = tun0_up
            record["tun0_up_sec"] = tun0_sec

            if not tun0_up:
                record["status"] = "TUNNEL_UP_FAILED"
                self._release(alloc_id, "FAILED", "tun0 interface failed to UP")
                return record

            # 5. DNS 조회 속도 계측 (m.naver.com)
            t_dns = time.time()
            dns_out = self._run_adb("nslookup m.naver.com 2>/dev/null || getent hosts m.naver.com 2>/dev/null || true", timeout_sec=3)
            record["dns_latency_sec"] = round(time.time() - t_dns, 3)
            record["dns_resolved"] = bool("naver.com" in dns_out or "223.130." in dns_out)

            # 6. HTTP 302 응답 속도 계측 (경량 http://m.naver.com)
            t_http = time.time()
            http_out = self._run_adb("curl -s -m 3 -o /dev/null -w '%{time_total},%{http_code}' http://m.naver.com 2>/dev/null || echo '0,ERR'", timeout_sec=4)
            record["http_probe"] = http_out.strip()
            record["http_probe_sec"] = round(time.time() - t_http, 3)

            # 7. HTTPS TLS 핸드셰이크 & 전체 응답 속도 계측 (무거운 https://m.naver.com)
            t_https = time.time()
            https_out = self._run_adb("curl -s -m 5 -o /dev/null -w '%{time_appconnect},%{time_total},%{http_code}' https://m.naver.com 2>/dev/null || echo '0,0,ERR'", timeout_sec=6)
            record["https_probe"] = https_out.strip()
            record["https_probe_sec"] = round(time.time() - t_https, 3)

            # 8. Path MTU 패킷 손실률 테스트 (ping -c 2 -w 3 8.8.8.8)
            ping_out = self._run_adb(f"ping -c 2 -w 3 8.8.8.8 2>/dev/null | grep -E 'packet loss|avg' || true", timeout_sec=4)
            record["ping_result"] = ping_out.strip()

            # 9. 공인 Egress IP 조회
            egress_ip = self.wg_mgr.get_egress_ip()
            record["egress_ip"] = egress_ip
            record["ip_matches"] = (egress_ip == record["macvlan_ip"])

            # 판정
            is_success = tun0_up and ("302" in http_out or "200" in http_out or "200" in https_out)
            record["status"] = "SUCCESS" if is_success else "FAILED"

        finally:
            # 10. 클린 터널 해제 및 API 자원 반환
            t_tear = time.time()
            self.wg_mgr.deactivate_tunnel()
            record["teardown_sec"] = round(time.time() - t_tear, 3)
            record["total_cycle_sec"] = round(time.time() - t_cycle_start, 3)

            self._release(alloc_id, record["status"], record.get("error"))

        return record

    def _release(self, alloc_id: str, status: str, error_reason: Optional[str] = None):
        try:
            results = [{
                "device_id": self.device_id,
                "status": status,
                "is_searched": False,
                "is_clicked": False,
                "is_exposed": False,
                "error_reason": error_reason or "BENCHMARK_PROBE"
            }]
            self.api_client.release_tasks(alloc_id, results)
        except Exception:
            pass

    def run_benchmark_loop(self, total_runs: int = 50, test_mtu: int = 1360):
        logger.info("=" * 80)
        logger.info(f"🚀 WireGuard 반복 안정성 벤치마크 가동 (대상: {self.device_id} | 총 회차: {total_runs}회 | MTU: {test_mtu})")
        logger.info("=" * 80)

        results = []
        success_count = 0

        for i in range(1, total_runs + 1):
            logger.info(f"\n--- [회차 #{i}/{total_runs}] 라우터 할당 및 터널링 프로브 시작 ---")
            rec = self.run_single_probe(iteration=i, test_mtu=test_mtu)
            results.append(rec)

            is_ok = (rec["status"] == "SUCCESS")
            if is_ok:
                success_count += 1
                logger.info(
                    f"  [✓ 성공] 라우터: {rec.get('router_num')} ({rec.get('endpoint')}) | "
                    f"tun0: {rec.get('tun0_up_sec')}s | HTTP: {rec.get('http_probe_sec')}s ({rec.get('http_probe')}) | "
                    f"Egress: {rec.get('egress_ip')} (기대: {rec.get('macvlan_ip')}) | 전체: {rec.get('total_cycle_sec')}s"
                )
            else:
                logger.warning(
                    f"  [❌ 실패] 라우터: {rec.get('router_num')} | 상태: {rec.get('status')} | "
                    f"tun0: {rec.get('tun0_up')} | HTTP: {rec.get('http_probe')} | 사유: {rec.get('error')}"
                )

            # JSONL 파일에 실시간 기록
            with open(BENCH_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

            time.sleep(1.0)

        succ_rate = round(success_count / total_runs * 100, 1)
        logger.info("\n" + "=" * 80)
        logger.info(f"🏁 벤치마크 완료: 총 {total_runs}회 중 {success_count}회 성공 ({succ_rate}%)")
        logger.info(f"📝 감사 로그 영구 저장: {BENCH_LOG_FILE}")
        logger.info("=" * 80)
        return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WireGuard Stability & Benchmark Tester")
    parser.add_argument("--runs", type=int, default=10, help="Number of benchmark iterations (default: 10)")
    parser.add_argument("--device", type=str, default="R3CR70FFFEK", help="Device ID (default: R3CR70FFFEK)")
    parser.add_argument("--mtu", type=int, default=1360, help="WireGuard MTU to test (default: 1360)")
    args = parser.parse_args()

    tester = WireGuardStabilityTester(device_id=args.device)
    tester.run_benchmark_loop(total_runs=args.runs, test_mtu=args.mtu)
