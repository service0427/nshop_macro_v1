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
from src.scheduler.daemon_controller import LOCK_FILE, PAUSE_FLAG_FILE, ALT_PAUSE_FLAG

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
    """--pause / --resume / --stop 제어 명령 처리"""
    if args.pause:
        with open(PAUSE_FLAG_FILE, "w") as f:
            f.write(f"PAUSED_AT_{time.time()}\n")
        print("\n" + "=" * 70)
        print(" ⏸️  [일시정지 명령 전송 완료]")
        print("    - 실행 중인 데몬에 일시정지(PAUSE) 플래그를 전달했습니다.")
        print("    - 현재 진행 중인 작업 완료 후 새 작업 할당이 멈춥니다.")
        print("    - 다시 재개하려면: python3 daemon.py --resume")
        print("=" * 70 + "\n")
        return True

    if args.resume:
        for f in [PAUSE_FLAG_FILE, ALT_PAUSE_FLAG]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        print("\n" + "=" * 70)
        print(" ▶️  [재개 명령 전송 완료]")
        print("    - 실행 중인 데몬의 일시정지가 해제되었습니다.")
        print("    - 스케줄러가 즉시 작업을 다시 시작합니다!")
        print("=" * 70 + "\n")
        return True

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
    parser.add_argument("--interval", "-i", type=float, default=10.0, help="Scheduler loop interval in seconds (default: 10.0)")
    parser.add_argument("--stagger", "-s", type=float, default=5.0, help="Stagger delay between worker dispatches in seconds (default: 5.0)")
    parser.add_argument("--loops", "-l", type=int, default=0, help="Max scheduler loop cycles to run before exit (0 = infinite)")
    parser.add_argument("--tasks", "-n", type=int, default=0, help="Max total tasks to process before exit (0 = infinite)")

    # 외부 제어 명령 플래그
    parser.add_argument("--pause", action="store_true", help="Pause running daemon without killing it")
    parser.add_argument("--resume", action="store_true", help="Resume paused daemon")
    parser.add_argument("--stop", action="store_true", help="Stop running daemon safely")
    args = parser.parse_args()

    # 제어 명령 플래그 우선 처리
    if handle_control_flags(args):
        return

    target_devices = [x.strip() for x in args.devices.split(",") if x.strip()] if args.devices else None

    scheduler = DynamicDaemonScheduler(
        device_ids=target_devices,
        max_workers=args.workers,
        loop_interval_sec=args.interval,
        stagger_sec=args.stagger,
        max_loops=args.loops,
        max_tasks=args.tasks
    )
    scheduler.start()


if __name__ == "__main__":
    main()
