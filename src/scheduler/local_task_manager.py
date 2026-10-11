#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/scheduler/local_task_manager.py

로컬 JSON 기반 모의 작업 할당 및 스토어 쿨다운(80분) 스케줄러
- tasks.json을 로컬 API 데이터베이스로 활용
- 스토어별 80분(4800초) 쿨다운 엄격 준수
- 타격 완료 시 상태 갱신 및 히스토리 기록
"""

import time
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any

from config.settings import TASKS_FILE, STORE_COOLDOWN_SECONDS

def load_tasks() -> List[Dict[str, Any]]:
    if not TASKS_FILE.exists():
        return []
    try:
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_tasks(tasks: List[Dict[str, Any]]):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)

def allocate_next_task() -> Tuple[Optional[Dict[str, Any]], str]:
    """
    스토어 쿨타임(80분)을 만족하는 다음 타겟 작업 1개 할당
    - 반환: (task_dict, status_message)
    - 쿨타임 미충족 시: (None, 'COOLDOWN_WAIT: 남은시간 N분')
    """
    tasks = load_tasks()
    if not tasks:
        return None, "NO_TASKS_CONFIGURED"

    now = time.time()
    available = []
    min_cooldown_left = float("inf")

    for t in tasks:
        if not t.get("enabled", True):
            continue

        last_exec = t.get("last_executed_at")
        cd_sec = t.get("cooldown_seconds", STORE_COOLDOWN_SECONDS)

        if last_exec is None:
            available.append((t, 0))
        else:
            elapsed = now - last_exec
            if elapsed >= cd_sec:
                available.append((t, elapsed))
            else:
                remain = cd_sec - elapsed
                if remain < min_cooldown_left:
                    min_cooldown_left = remain

    if not available:
        rem_min = min_cooldown_left / 60
        return None, f"COOLDOWN_WAIT ({rem_min:.1f}분 대기 필요)"

    # 가장 오래 실행되지 않았거나 누적 타수가 적은 작업 우선 선택
    available.sort(key=lambda x: (x[0].get("total_hits", 0), -x[1]))
    selected = available[0][0]
    return selected, "ALLOCATED"

def report_task_result(task_id: str, success: bool):
    tasks = load_tasks()
    now = time.time()
    for t in tasks:
        if t.get("task_id") == task_id:
            t["last_executed_at"] = now
            t["last_executed_time"] = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
            if success:
                t["total_hits"] = t.get("total_hits", 0) + 1
            break
    save_tasks(tasks)

def get_scheduler_status() -> Dict[str, Any]:
    tasks = load_tasks()
    now = time.time()
    summary = []
    for t in tasks:
        last = t.get("last_executed_at")
        cd_sec = t.get("cooldown_seconds", STORE_COOLDOWN_SECONDS)
        if last is None:
            status = "READY"
            rem_str = "즉시 가능"
        else:
            elapsed = now - last
            if elapsed >= cd_sec:
                status = "READY"
                rem_str = "쿨다운 충족 (즉시 가능)"
            else:
                status = "COOLDOWN"
                rem_str = f"남은 쿨다운: {(cd_sec - elapsed)/60:.1f}분"
        summary.append({
            "task_id": t["task_id"],
            "store_name": t["store_name"],
            "keyword": t["keyword"],
            "total_hits": t.get("total_hits", 0),
            "status": status,
            "cooldown_detail": rem_str
        })
    return {"tasks": summary}
