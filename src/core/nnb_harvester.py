#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/core/nnb_harvester.py

네이버 정품 NNB/BUC 초고속 패킷 수집 및 수위 조절 모듈
- lcs.naver.com/m 엔드포인트 0.2초 초경량 패킷 호출
- 로컬 nnb_pool.json 수집/적재/상태 추적
- 21분(1260초) 이상 숙성된 READY 토큰 인출
- 웜업에서 채굴된 신생아 토큰 저금(Bank)
- 수위 조절기(Watermark Controller) 자동 보충
"""

import sys
import re
import time
import json
import subprocess
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple

from config.settings import (
    NNB_POOL_FILE,
    DEFAULT_DEVICE_ID,
    MIN_AGING_SECONDS,
    TARGET_NNB_POOL_SIZE,
    LCS_BEACON_URL,
    IP_CHECK_URL
)

def load_pool() -> List[Dict[str, Any]]:
    if not NNB_POOL_FILE.exists():
        return []
    try:
        with open(NNB_POOL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_pool(pool: List[Dict[str, Any]]):
    with open(NNB_POOL_FILE, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)

def get_device_public_ip(device_id: str = DEFAULT_DEVICE_ID) -> str:
    try:
        cmd = ["adb", "-s", device_id, "shell", f"curl -s {IP_CHECK_URL}"]
        res = subprocess.run(cmd, capture_output=True, timeout=5)
        return res.stdout.decode("utf-8", errors="ignore").strip()
    except Exception:
        return "UNKNOWN"

def harvest_single_packet(device_id: str = DEFAULT_DEVICE_ID) -> Optional[Dict[str, Any]]:
    """단말기 내부에서 lcs.naver.com/m 호출하여 0.2초 만에 정품 NNB+BUC 발급"""
    cmd = [
        "adb", "-s", device_id, "shell",
        f"curl -s -D - -o /dev/null {LCS_BEACON_URL}"
    ]
    t0 = time.time()
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=8)
        dur = time.time() - t0
        raw = res.stdout.decode("utf-8", errors="ignore")

        m_nnb = re.search(r"set-cookie:\s*NNB=([^;\r\n]+)", raw, re.IGNORECASE)
        m_buc = re.search(r"set-cookie:\s*BUC=([^;\r\n]+)", raw, re.IGNORECASE)

        if not m_nnb:
            return None

        nnb = m_nnb.group(1).strip()
        buc = m_buc.group(1).strip() if m_buc else ""
        now = time.time()

        return {
            "nnb": nnb,
            "buc": buc,
            "issued_at": now,
            "issued_time": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
            "source": "LCS_PACKET",
            "dur_sec": round(dur, 3),
            "status": "AGING",
            "used_at": None,
            "used_target": None
        }
    except Exception:
        return None

def bank_newborn_nnb(nnb: str, buc: str = "", source: str = "APP_WARMUP", device_id: str = DEFAULT_DEVICE_ID) -> Dict[str, Any]:
    """앱 웜업 과정에서 생성된 순정 신생아 NNB를 풀에 저금"""
    pool = load_pool()
    now = time.time()
    item = {
        "nnb": nnb,
        "buc": buc,
        "issued_at": now,
        "issued_time": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "device_id": device_id,
        "dur_sec": 0.0,
        "status": "AGING",
        "used_at": None,
        "used_target": None
    }
    pool.append(item)
    save_pool(pool)
    return item

def get_next_ready_nnb(min_age_seconds: int = MIN_AGING_SECONDS) -> Optional[Dict[str, Any]]:
    """풀에서 21분 이상 경과한 READY NNB 중 가장 먼저 숙성된 항목 1개 인출"""
    pool = load_pool()
    now = time.time()
    candidates = []
    for item in pool:
        if item.get("status") != "USED":
            age = now - item.get("issued_at", now)
            if age >= min_age_seconds:
                candidates.append((item, age))

    if not candidates:
        return None

    # 가장 오래된 순서대로 정렬
    candidates.sort(key=lambda x: x[0]["issued_at"])
    return candidates[0][0]

def mark_nnb_used(nnb_val: str, target: str = ""):
    """타격 완료된 NNB를 USED 상태로 확정 갱신"""
    pool = load_pool()
    now = time.time()
    for item in pool:
        if item.get("nnb") == nnb_val:
            item["status"] = "USED"
            item["used_at"] = now
            item["used_time"] = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
            item["used_target"] = target
            break
    save_pool(pool)

def topup_pool(target_size: int = TARGET_NNB_POOL_SIZE, device_id: str = DEFAULT_DEVICE_ID) -> int:
    """활성 NNB 수량이 목표치 미달 시 lcs.naver.com/m 패킷으로 즉시 자동 보충"""
    pool = load_pool()
    now = time.time()
    active = [x for x in pool if x.get("status") != "USED"]
    needed = target_size - len(active)
    if needed <= 0:
        return 0

    ip = get_device_public_ip(device_id)
    print(f"🌾 [NNB Harvester] 활성 풀 부족분 {needed}개 자동 채굴 시작 (단말기: {device_id}, IP: {ip})...")
    collected = 0
    for i in range(needed):
        item = harvest_single_packet(device_id)
        if item:
            item["ip"] = ip
            pool.append(item)
            collected += 1
        time.sleep(0.15)
    save_pool(pool)
    print(f"✅ [NNB Harvester] {collected}개 보충 완료 (현재 활성 풀: {len(active) + collected}개)")
    return collected

def get_pool_status() -> Dict[str, Any]:
    pool = load_pool()
    now = time.time()
    ready_list = []
    aging_list = []
    used_list = []

    for item in pool:
        if item.get("status") == "USED":
            used_list.append(item)
        else:
            age = now - item.get("issued_at", now)
            if age >= MIN_AGING_SECONDS:
                item["status"] = "READY"
                ready_list.append(item)
            else:
                item["status"] = "AGING"
                aging_list.append(item)

    return {
        "total": len(pool),
        "ready_count": len(ready_list),
        "aging_count": len(aging_list),
        "used_count": len(used_list),
        "ready_items": ready_list,
        "aging_items": aging_list,
        "used_items": used_list
    }
