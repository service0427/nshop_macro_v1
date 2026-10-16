#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/monitor/fleet_state.py

20대 단말기 플릿 실시간 상태 및 쿨타임 모니터링 공유 모듈 (Fleet Live State Hub)
-----------------------------------------------------------------------------
- 각 단말기 워커 프로세스에서 자신의 현재 진행 키워드, 단계, 체류 시간, 쿨타임 사유를 기록
- 메인 루프에서 Cycle, 공인 IP, 세트 간 쿨타임/대기 사유 기록
- 원자적(Atomic) JSON 쓰기로 동시성 충돌 방지
"""

import os
import sys
import time
import json
from pathlib import Path
from typing import Dict, Any, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
STATE_FILE = ROOT_DIR / "logs" / "fleet_state.json"
STATE_FILE_TMP = ROOT_DIR / "logs" / "fleet_state.json.tmp"


class FleetStateManager:
    """플릿 전체의 실시간 상태를 디스크에 공유하는 매니저"""

    @classmethod
    def _read_raw(cls) -> Dict[str, Any]:
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {
            "global": {
                "cycle": 0,
                "ip": "-",
                "net_mode": "lte",
                "status": "IDLE",
                "status_detail": "대기 중",
                "cooldown_remaining_sec": 0,
                "cooldown_reason": "",
                "updated_at": time.time()
            },
            "devices": {}
        }

    @classmethod
    def _write_raw(cls, data: Dict[str, Any]):
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE_TMP, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(STATE_FILE_TMP, STATE_FILE)
        except Exception:
            pass

    @classmethod
    def update_global(
        cls,
        cycle: Optional[int] = None,
        ip: Optional[str] = None,
        net_mode: Optional[str] = None,
        status: Optional[str] = None,
        status_detail: Optional[str] = None,
        cooldown_remaining_sec: Optional[int] = None,
        cooldown_reason: Optional[str] = None
    ):
        """메인 프로세스에서 전체 시스템 상태 및 쿨타임 갱신"""
        data = cls._read_raw()
        g = data.setdefault("global", {})
        if cycle is not None:
            g["cycle"] = cycle
        if ip is not None:
            g["ip"] = ip
        if net_mode is not None:
            g["net_mode"] = net_mode
        if status is not None:
            g["status"] = status
        if status_detail is not None:
            g["status_detail"] = status_detail
        if cooldown_remaining_sec is not None:
            g["cooldown_remaining_sec"] = cooldown_remaining_sec
        if cooldown_reason is not None:
            g["cooldown_reason"] = cooldown_reason
        g["updated_at"] = time.time()
        cls._write_raw(data)

    @classmethod
    def update_device(
        cls,
        device_id: str,
        state: Optional[str] = None,
        keyword: Optional[str] = None,
        store_name: Optional[str] = None,
        target_mid: Optional[str] = None,
        rank: Optional[str] = None,
        progress: Optional[str] = None,
        elapsed_sec: Optional[float] = None,
        last_result: Optional[str] = None,
        screenshot: Optional[str] = None,
        status_msg: Optional[str] = None
    ):
        """개별 단말기 워커 프로세스에서 실시간 상태 갱신"""
        data = cls._read_raw()
        devs = data.setdefault("devices", {})
        dev = devs.setdefault(device_id, {
            "device_id": device_id,
            "state": "IDLE",
            "keyword": "-",
            "store_name": "-",
            "target_mid": "-",
            "rank": "-",
            "progress": "대기",
            "elapsed_sec": 0.0,
            "last_result": "-",
            "screenshot": "",
            "status_msg": "대기 중",
            "updated_at": time.time()
        })

        if state is not None:
            dev["state"] = state
        if keyword is not None:
            dev["keyword"] = keyword
        if store_name is not None:
            dev["store_name"] = store_name
        if target_mid is not None:
            dev["target_mid"] = target_mid
        if rank is not None:
            dev["rank"] = rank
        if progress is not None:
            dev["progress"] = progress
        if elapsed_sec is not None:
            dev["elapsed_sec"] = round(elapsed_sec, 1)
        if last_result is not None:
            dev["last_result"] = last_result
        if screenshot is not None:
            dev["screenshot"] = screenshot
        if status_msg is not None:
            dev["status_msg"] = status_msg
        dev["updated_at"] = time.time()

        cls._write_raw(data)

    @classmethod
    def get_snapshot(cls) -> Dict[str, Any]:
        """현재 전체 상태 스냅샷 반환"""
        return cls._read_raw()
