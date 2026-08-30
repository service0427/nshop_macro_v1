# -*- coding: utf-8 -*-
"""
========================================================================================
[모듈명] 데몬 프로세스 락 및 안전 시그널 관리자 (DaemonController)
(src/scheduler/daemon_controller.py)
========================================================================================
- 기능:
    1. 중복 실행 차단 flock 싱글 인스턴스 락 관리
    2. 비상/종료 시그널(SIGINT, SIGTERM) 발생 시 안전 세션 반납 및 단말기 클린업
========================================================================================
"""

import os
import sys
import fcntl
import signal
import logging
from typing import Callable, Optional

logger = logging.getLogger("DaemonController")

LOCK_FILE = "/tmp/nshop_macro_daemon.lock"


class DaemonController:
    """데몬 수명 주기 및 싱글 인스턴스 락 제어기 (24/7 PM2 무인 운영 전용)"""

    def __init__(self, on_emergency_exit: Optional[Callable] = None):
        self.running = True
        self.lock_file_fd = None
        self.on_emergency_exit = on_emergency_exit

    def acquire_lock(self, max_retries: int = 5, retry_delay: float = 0.8):
        """중복 실행 방지 flock 락 획득 (PM2 재기동 시 이전 프로세스 해제 대기 재시도 지원)"""
        for attempt in range(1, max_retries + 1):
            try:
                self.lock_file_fd = open(LOCK_FILE, "w")
                fcntl.flock(self.lock_file_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.lock_file_fd.write(f"{os.getpid()}\n")
                self.lock_file_fd.flush()
                return
            except (IOError, BlockingIOError):
                if attempt < max_retries:
                    time.sleep(retry_delay)
                else:
                    logger.error(f"\n[❌ 중복 실행 차단] 이미 nshop_macro 데몬 프로세스가 실행 중입니다! (Lock: {LOCK_FILE})")
                    logger.error("기존 프로세스를 확인하거나 pm2 restart/stop 후 다시 실행해주세요.\n")
                    sys.exit(1)

    def release_lock(self):
        """flock 락 해제"""
        if self.lock_file_fd:
            try:
                fcntl.flock(self.lock_file_fd, fcntl.LOCK_UN)
                self.lock_file_fd.close()
                self.lock_file_fd = None
                if os.path.exists(LOCK_FILE):
                    os.remove(LOCK_FILE)
            except Exception:
                pass

    def setup_signal_handlers(self):
        """Ctrl+C 및 SIGTERM 시그널 핸들러 등록 (pm2 stop / restart 시 안전 세션 반납)"""
        def _handler(signum, frame):
            logger.warning(f"\n🛑 종료 시그널({signum}) 감지 -> 잔여 세션 안전 반납 및 클린업을 진행합니다...")
            self.running = False
            try:
                if self.on_emergency_exit:
                    self.on_emergency_exit()
            finally:
                self.release_lock()
                sys.exit(0)

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)
