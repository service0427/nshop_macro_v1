#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
N-Shop Automation Macro 24/7 Dynamic Scheduler Daemon (daemon.py)
[10초 주기 동적 가용 단말기 풀 & 시차 병렬 무한 루프 스케줄러]
========================================================================================
- 기능 요약:
    1. [중복 실행 방지]: flock 기반 싱글 인스턴스 락 적용
    2. [24/7 동적 가용 워커 풀]: 10초마다 유휴 단말기만 모아서 실시간 작업 재요청
    3. [하드웨어 안전 방어]: 배터리 < 20% 자동 PASS, 과열(43°C) 쿨다운, USB 전원 리셋 자가치료
    4. [실시간 상태 현황판]: 매 10초마다 각 워커의 실행 주기, 모드(클릭/탐색), 키워드, 소요 시간 표시
    5. [터미널 인터랙션]: [p: 일시정지 | r: 재개 | s: 현황판 | q: 비상종료]
========================================================================================
"""

import os
import sys
import time
import signal
import logging
import argparse

from src.scheduler.daemon_scheduler import DynamicDaemonScheduler
from src.scheduler.daemon_controller import LOCK_FILE
from src.config import EXCLUDED_DEVICES, DEVICE_COOLDOWN_SEC, DEVICE_FAIL_COOLDOWN_SEC, DISPATCH_INTERVAL_SEC, MAX_DISPATCH_BATCH

# 표준출력 및 표준에러 실시간 버퍼링 해제 (PM2 실시간 로그 스트리밍 보장)
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

# 루트 로거 포맷 및 표준출력 핸들러 구성
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
for h in root_logger.handlers[:]:
    root_logger.removeHandler(h)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s", datefmt="%H:%M:%S"))
root_logger.addHandler(_handler)
logger = logging.getLogger("DynamicScheduler")


def handle_control_flags(args) -> bool:
    """--stop 제어 명령 처리"""
    if args.stop:
        if os.path.exists(LOCK_FILE):
            try:
                with open(LOCK_FILE, "r") as f:
                    pid = int(f.read().strip())
                print(f"[*] 실행 중인 데몬 프로세스 (PID: {pid})에 종료 신호(SIGINT) 전송 중...")
                os.kill(pid, signal.SIGINT)
                print("[✓] 안전 종료 신호를 전송했습니다.\n")
            except Exception as e:
                print(f"[!] 데몬 프로세스 종료 실패: {e}\n")
        else:
            print("[!] 실행 중인 데몬 lock 파일을 찾을 수 없습니다.\n")
        return True

    return False


def main():
    parser = argparse.ArgumentParser(description="N-Shop 24/7 Dynamic Scheduler Daemon")
    parser.add_argument("--workers", "-w", type=int, default=0, help="Number of worker slots (0 = auto-detect all connected ADB devices)")
    parser.add_argument("--devices", "-d", type=str, default="", help="Comma separated device IDs (e.g. -d R5CR9336DSB)")
    parser.add_argument("--exclude-devices", "-x", type=str, default=",".join(EXCLUDED_DEVICES), help=f"Comma separated device IDs to exclude (default: {','.join(EXCLUDED_DEVICES)})")
    parser.add_argument("--interval", "-i", type=float, default=30.0, help="Scheduler loop interval in seconds (default: 30.0)")
    parser.add_argument("--stagger", "-s", type=float, default=1.0, help="Stagger delay between worker dispatches in seconds (default: 1.0)")
    parser.add_argument("--loops", "-l", type=int, default=0, help="Max scheduler loop cycles to run before exit (0 = infinite)")
    parser.add_argument("--tasks", "-n", type=int, default=0, help="Max total tasks to process before exit (0 = infinite)")
    parser.add_argument("--until", "-u", type=str, default="23:50", help="Auto stop daemon at HH:MM (e.g. 23:50, default: 23:50)")
    parser.add_argument("--device-cooldown", type=float, default=DEVICE_COOLDOWN_SEC, help=f"Per-device cooldown on success in seconds (default: {DEVICE_COOLDOWN_SEC})")
    parser.add_argument("--fail-cooldown", type=float, default=DEVICE_FAIL_COOLDOWN_SEC, help=f"Per-device cooldown on failure/click-fail in seconds (default: {DEVICE_FAIL_COOLDOWN_SEC})")
    parser.add_argument("--dispatch-interval", type=float, default=DISPATCH_INTERVAL_SEC, help=f"Rolling dispatch interval between batches in seconds (default: {DISPATCH_INTERVAL_SEC})")
    parser.add_argument("--batch-size", type=int, default=MAX_DISPATCH_BATCH, help=f"Max devices to dispatch per rolling cycle (default: {MAX_DISPATCH_BATCH})")
    parser.add_argument("--max-ip-retries", type=int, default=5, help="Max unused IP retry attempts per time slot before skipping (default: 5)")
    parser.add_argument("--stop", action="store_true", help="Stop running daemon safely")
    args = parser.parse_args()

    # 제어 명령 플래그 우선 처리
    if handle_control_flags(args):
        return

    target_devices = [x.strip() for x in args.devices.split(",") if x.strip()] if args.devices else None
    exclude_devices = [x.strip() for x in args.exclude_devices.split(",") if x.strip()] if args.exclude_devices else []

    scheduler = DynamicDaemonScheduler(
        device_ids=target_devices,
        exclude_device_ids=exclude_devices,
        max_workers=args.workers,
        loop_interval_sec=args.interval,
        stagger_sec=args.stagger,
        max_loops=args.loops,
        max_tasks=args.tasks,
        until_time=args.until,
        device_cooldown_sec=args.device_cooldown,
        device_fail_cooldown_sec=args.fail_cooldown,
        dispatch_interval_sec=args.dispatch_interval,
        batch_size=args.batch_size,
        max_ip_retries=args.max_ip_retries
    )
    scheduler.start()


if __name__ == "__main__":
    main()
