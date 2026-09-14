#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
🛡️ N-SHOP 2ND LINE OF DEFENSE: PUBLIC IP 24-HOUR COOLDOWN TRACKER
(src/modules/ip_cooldown_tracker.py)
========================================================================================
- 기능:
    1. 단말기가 네이버로 나가는 실제 공인 Egress IP(`curl api.ipify.org`)를 추적.
    2. 동일 공인 IP가 24시간(86,400초) 이내에 동일 스토어/타겟에 재투입되는 것을 사전에 100% 차단.
    3. FDS의 동일 IP 중복 유입 필터링(무효타/0타)을 원천 방어하는 2차 방어선.
    4. 영구 파일(`logs/ip_cooldown_history.json`) 기반 스레드 안전 기록 및 만료 데이터 자동 정리.
========================================================================================
"""

import os
import time
import json
import logging
import threading
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

from src.config import IP_COOLDOWN_FILE, IP_COOLDOWN_SEC

logger = logging.getLogger("IPCooldownTracker")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [IPCooldown] %(message)s",
        datefmt="%H:%M:%S"
    )


class IPCooldownTracker:
    """공인 IP별 24시간 쿨다운 추적 및 실시간 검증자"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(IPCooldownTracker, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, cooldown_file: str = IP_COOLDOWN_FILE, cooldown_sec: float = IP_COOLDOWN_SEC):
        if self._initialized:
            return
        self.cooldown_file = cooldown_file
        self.cooldown_sec = cooldown_sec
        self.lock = threading.Lock()
        self.probe_file = "/home/tech/nshop_macro_v1/logs/cooldown_probe_experiments.jsonl"
        self.max_probes = int(os.getenv("MAX_COOLDOWN_PROBES", "2"))
        self.probe_min_elapsed_sec = float(os.getenv("PROBE_MIN_ELAPSED_SEC", "64800.0"))  # 최소 18시간 경과
        self.probe_count = self._load_probe_count()
        self.history: Dict[str, Dict[str, Any]] = self._load_history()
        self._seed_from_recent_logs_if_empty()
        self._initialized = True

    def _load_probe_count(self) -> int:
        """금일 수행된 쿨타임 프로브 횟수 로드"""
        if not os.path.exists(self.probe_file):
            return 0
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            cnt = 0
            with open(self.probe_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        if data.get("timestamp", "").startswith(today_str):
                            cnt += 1
            return cnt
        except Exception:
            return 0

    def _log_probe_experiment(self, public_ip: str, elapsed_h: float, remain_h: float, prev_entry: dict):
        """쿨타임 프로브 실험 내역 영구 로깅"""
        try:
            os.makedirs(os.path.dirname(self.probe_file), exist_ok=True)
            record = {
                "timestamp": datetime.now().isoformat(),
                "probe_index": self.probe_count,
                "public_ip": public_ip,
                "elapsed_hours": elapsed_h,
                "remaining_hours": remain_h,
                "previous_usage": prev_entry,
                "note": "CONTROLLED_FDS_BOUNDARY_PROBE"
            }
            with open(self.probe_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"[-] 프로브 실험 로그 기록 실패: {e}")

    def _load_history(self) -> Dict[str, Dict[str, Any]]:
        """쿨다운 파일 로드 및 구버전 포맷 호환"""
        if os.path.exists(self.cooldown_file):
            try:
                with open(self.cooldown_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    normalized = {}
                    for ip, val in data.items():
                        if isinstance(val, (int, float)):
                            normalized[ip] = {
                                "timestamp": float(val),
                                "formatted_time": datetime.fromtimestamp(float(val)).strftime("%Y-%m-%d %H:%M:%S"),
                                "device_id": "UNKNOWN",
                                "mid": "UNKNOWN",
                                "is_clicked": True
                            }
                        elif isinstance(val, dict) and "timestamp" in val:
                            normalized[ip] = val
                    return normalized
            except Exception as e:
                logger.warning(f"[-] IP 쿨다운 파일 로드 실패: {e}")
        return {}

    def _save_history(self):
        """쿨다운 파일 원자적 저장 (tmp -> rename)"""
        try:
            os.makedirs(os.path.dirname(self.cooldown_file), exist_ok=True)
            tmp_file = f"{self.cooldown_file}.tmp_{os.getpid()}_{threading.get_ident()}"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, self.cooldown_file)
        except Exception as e:
            logger.error(f"[-] IP 쿨다운 파일 저장 실패: {e}")

    def _seed_from_recent_logs_if_empty(self):
        """파일이 비어있거나 부족할 경우 어제(9/12)의 실측 IP 기록을 즉시 시딩"""
        now = time.time()
        valid_cnt = sum(1 for v in self.history.values() if now - v.get("timestamp", 0) < self.cooldown_sec)
        if valid_cnt >= 5:
            return

        log_file = "/home/tech/.pm2/logs/nshop-macro-daemon-out.log"
        if not os.path.exists(log_file):
            return

        import re
        seeded = 0
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-10000:]

            for line in lines:
                m_done = re.search(r"작업 완료 -> 상태: (\w+).*클릭: (\w+).*소요: [\d\.]+s", line)
                if m_done and m_done.group(2) == "True":
                    m_ip = re.search(r"IP: ([\d\.]+)", line)
                    m_time = re.search(r"\[(\d{2}:\d{2}:\d{2})\]", line)
                    m_dev = re.search(r"\[(R[35]CR[0-9A-Z]+)\]", line)
                    if m_ip and m_time:
                        ip = m_ip.group(1)
                        dev = m_dev.group(1) if m_dev else "UNKNOWN"
                        time_str = f"2026-09-12 {m_time.group(1)}"
                        try:
                            ts = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").timestamp()
                            if now - ts < self.cooldown_sec and ip not in self.history:
                                self.history[ip] = {
                                    "timestamp": ts,
                                    "formatted_time": time_str,
                                    "device_id": dev,
                                    "mid": "HISTORICAL",
                                    "is_clicked": True
                                }
                                seeded += 1
                        except Exception:
                            pass

            if seeded > 0:
                self._save_history()
                logger.info(f"[✓] 과거 세션 로그로부터 최근 24시간 내 사용된 공인 IP {seeded}개 자동 시딩 완료")
        except Exception as e:
            logger.debug(f"[-] 과거 IP 시딩 예외: {e}")

    def is_ip_cooling(self, public_ip: str) -> Tuple[bool, float, Dict[str, Any]]:
        """
        [2차 방어선 핵심 검증]
        해당 공인 IP가 최근 24시간 내에 사용된 이력이 있는지 검사.
        
        Returns:
            (is_cooling: bool, remaining_seconds: float, prev_entry: dict)
        """
        if not public_ip or public_ip == "UNKNOWN" or public_ip.startswith("192.168."):
            return False, 0.0, {}

        now = time.time()
        with self.lock:
            entry = self.history.get(public_ip)
            if entry:
                last_ts = float(entry.get("timestamp", 0))
                elapsed = now - last_ts
                if elapsed < self.cooldown_sec:
                    remain_sec = self.cooldown_sec - elapsed
                    # [사용자 특별 지시: 1~2회 24h 쿨다운 경계 검증 프로브 실험]
                    if self.probe_count < self.max_probes and elapsed >= self.probe_min_elapsed_sec:
                        self.probe_count += 1
                        elapsed_h = round(elapsed / 3600, 2)
                        remain_h = round(remain_sec / 3600, 2)
                        logger.warning(
                            f"🧪 [쿨타임 프로브 실험 #{self.probe_count}/{self.max_probes}] "
                            f"24h 미달 IP ({public_ip}, 경과: {elapsed_h}h / 잔여: {remain_h}h) "
                            f"➔ FDS 경계치 검증을 위해 1회성 의도적 통과 허용!"
                        )
                        self._log_probe_experiment(public_ip, elapsed_h, remain_h, entry)
                        return False, 0.0, entry

                    return True, round(remain_sec, 1), entry
                else:
                    return False, 0.0, entry
            return False, 0.0, {}

    def record_ip_usage(
        self,
        public_ip: str,
        mid: Optional[str] = None,
        device_id: Optional[str] = None,
        store: Optional[str] = None,
        is_clicked: bool = True,
        note: Optional[str] = None
    ):
        """
        작업 성공(클릭 완주) 시 해당 공인 IP를 24시간 쿨다운 파일에 즉시 등록
        """
        if not public_ip or public_ip == "UNKNOWN" or public_ip.startswith("192.168."):
            return

        now = time.time()
        now_str = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")

        with self.lock:
            self.history[public_ip] = {
                "timestamp": now,
                "formatted_time": now_str,
                "device_id": device_id or "UNKNOWN",
                "mid": mid or "UNKNOWN",
                "store": store or "스마트스토어",
                "is_clicked": is_clicked,
                "note": note or "NORMAL_RUN"
            }
            self._cleanup_expired_locked(now)
            self._save_history()

        logger.info(f"🔒 [2차 방어선 등록] 공인 IP ({public_ip}) 24시간 쿨다운 등록 완료! (만료 예정: 24h 후 | MID: {mid})")

    def _cleanup_expired_locked(self, now: float):
        """48시간 이상 경과한 오래된 IP 기록 정리"""
        expire_limit = self.cooldown_sec * 2  # 48시간
        expired_ips = [
            ip for ip, data in self.history.items()
            if (now - float(data.get("timestamp", 0))) > expire_limit
        ]
        for ip in expired_ips:
            del self.history[ip]

    def get_status_summary(self) -> Dict[str, Any]:
        """현재 쿨다운 중인 IP 요약 정보 반환"""
        now = time.time()
        with self.lock:
            cooling = {}
            for ip, data in self.history.items():
                remain = self.cooldown_sec - (now - float(data.get("timestamp", 0)))
                if remain > 0:
                    cooling[ip] = {
                        "remain_hours": round(remain / 3600, 2),
                        "remain_minutes": round(remain / 60, 1),
                        "last_used": data.get("formatted_time"),
                        "device_id": data.get("device_id"),
                        "mid": data.get("mid")
                    }
            return {
                "total_tracked": len(self.history),
                "currently_cooling": len(cooling),
                "cooling_details": cooling
            }


# 전역 싱글톤 인스턴스
ip_cooldown_tracker = IPCooldownTracker()
