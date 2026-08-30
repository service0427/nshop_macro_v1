# -*- coding: utf-8 -*-
"""
========================================================================================
[모듈명] 데몬 인터랙티브 제어 & 프로세스 락 관리자 (DaemonController)
(src/scheduler/daemon_controller.py)
========================================================================================
- 기능:
    1. 중복 실행 차단 flock 싱글 인스턴스 락 관리
    2. pause.flag 파일 실시간 감지 및 일시정지(PAUSED) 동기화
    3. 키보드 인터랙션 단축키 (p: 일시정지 / r: 재개 / s: 현황판 / q: 비상종료)
    4. 비상 시그널(SIGINT, SIGTERM) 발생 시 안전 세션 반납 및 단말기 클린업
========================================================================================
"""

import os
import sys
import time
import fcntl
import signal
import logging
import threading
from typing import Callable, Optional
from src.config import PAUSE_FLAG_FILE

logger = logging.getLogger("DaemonController")

LOCK_FILE = "/tmp/nshop_macro_daemon.lock"
ALT_PAUSE_FLAG = "/tmp/nshop.pause"


class DaemonController:
    """데몬 수명 주기 및 제어기"""

    def __init__(self, on_emergency_exit: Optional[Callable] = None, on_status_request: Optional[Callable] = None):
        self.running = True
        self.paused = False
        self.lock_file_fd = None
        self.on_emergency_exit = on_emergency_exit
        self.on_status_request = on_status_request

    def acquire_lock(self):
        """중복 실행 방지 flock 락 획득"""
        try:
            self.lock_file_fd = open(LOCK_FILE, "w")
            fcntl.flock(self.lock_file_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.lock_file_fd.write(f"{os.getpid()}\n")
            self.lock_file_fd.flush()
        except (IOError, BlockingIOError):
            logger.error(f"\n[❌ 중복 실행 차단] 이미 nshop_macro 데몬 프로세스가 실행 중입니다! (Lock: {LOCK_FILE})")
            logger.error("기존 프로세스를 확인하거나 종료(python3 daemon.py --stop) 후 다시 실행해주세요.\n")
            sys.exit(1)

    def release_lock(self):
        """flock 락 해제"""
        if self.lock_file_fd:
            try:
                fcntl.flock(self.lock_file_fd, fcntl.LOCK_UN)
                self.lock_file_fd.close()
                if os.path.exists(LOCK_FILE):
                    os.remove(LOCK_FILE)
            except Exception:
                pass

    def check_pause_flag(self) -> bool:
        """pause.flag 파일 존재 여부에 따른 PAUSED 실시간 동기화"""
        flag_exists = os.path.exists(PAUSE_FLAG_FILE) or os.path.exists(ALT_PAUSE_FLAG)
        if flag_exists:
            if not self.paused:
                self.paused = True
                logger.warning("\n" + "=" * 80)
                logger.warning(" ⏸️  [일시정지 (PAUSE) 활성화]")
                logger.warning("    - pause.flag 파일 감지됨: 새 작업 할당 요청을 멈추고 대기합니다.")
                logger.warning("    - 재개 방법: python3 daemon.py --resume  (또는 터미널에 'r' + Enter)")
                logger.warning("=" * 80 + "\n")
            return True
        return self.paused

    def set_pause(self, paused: bool):
        self.paused = paused
        if not paused:
            for f in [PAUSE_FLAG_FILE, ALT_PAUSE_FLAG]:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass

    def start_keyboard_listener(self):
        """콘솔 키보드 리스너 스레드 (p/r/s/q)"""
        def _listen():
            while self.running:
                try:
                    line = sys.stdin.readline()
                    if not line:
                        time.sleep(0.5)
                        continue
                    cmd = line.strip().lower()
                    if cmd in ["p", "pause", "ㅔ"]:
                        self.set_pause(True)
                        logger.warning("\n" + "=" * 80)
                        logger.warning(" ⏸️  [스케줄러 일시정지 (PAUSED)]")
                        logger.warning("    - 새 작업 할당 요청을 일시 중단합니다.")
                        logger.warning("    - 현재 실행 중인 단말기 작업은 완료 후 안전하게 IDLE 대기합니다.")
                        logger.warning("    - 다시 시작하려면 'r' + Enter 를 입력하세요.")
                        logger.warning("=" * 80 + "\n")
                    elif cmd in ["r", "resume", "ㄱ"]:
                        self.set_pause(False)
                        logger.info("\n" + "=" * 80)
                        logger.info(" ▶️  [스케줄러 재개 (RESUMED)]")
                        logger.info("    - 유휴 단말기 작업 할당 및 디스패치를 다시 가동합니다!")
                        logger.info("=" * 80 + "\n")
                    elif cmd in ["s", "status", "ㄴ"]:
                        if self.on_status_request:
                            self.on_status_request()
                    elif cmd in ["q", "quit", "exit", "ㅂ"]:
                        logger.warning("\n🛑 'q' 키 입력 감지 -> 비상 안전 종료를 진행합니다...")
                        self.running = False
                        if self.on_emergency_exit:
                            self.on_emergency_exit()
                        break
                except Exception:
                    break

        t = threading.Thread(target=_listen, daemon=True, name="KeyboardListener")
        t.start()

    def setup_signal_handlers(self):
        """Ctrl+C 및 SIGTERM 시그널 핸들러 등록"""
        def _handler(signum, frame):
            self.running = False
            if self.on_emergency_exit:
                self.on_emergency_exit()

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)
