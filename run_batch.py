#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
N-Shop Automation Macro Batch Runner (run_batch.py)
[5초 시차 병렬 투입 (5s Staggered Dispatch) 1회 배치 실행기]
========================================================================================
"""

import os
import sys
import json
import time
import logging
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.modules.task_api_client import TaskApiClient
from src.pipeline.worker_pipeline import DeviceWorkerPipeline

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("BatchRunner")

def load_device_set(config_path: str = "device_set.json") -> list:
    active_5 = ["R3CR70KAZDM", "R3CR70SZ0JJ", "R3CRB0WCGET", "R5CR713T5WT", "R5CR9336DSB"]
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                keys = list(data.keys())
                matched = [k for k in active_5 if k in keys]
                return matched if matched else active_5
        except Exception:
            pass
    return active_5

def run_batch(device_ids: list = None, stagger_sec: float = 5.0):
    if not device_ids:
        device_ids = load_device_set()

    logger.info(f"[*] ==========================================================================")
    logger.info(f"[*] 🚀 5대 단말기 5초 시차 병렬 배치 시작 (총 {len(device_ids)}대: {device_ids})")
    logger.info(f"[*] ==========================================================================")

    client = TaskApiClient()
    alloc_data = client.allocate_tasks(device_ids)
    if not alloc_data or alloc_data.get("status") != "success":
        logger.error(f"[!] 작업 할당 실패 또는 응답 없음. 배치를 종료합니다.")
        return

    alloc_id = alloc_data.get("alloc_id")
    router_info = alloc_data.get("router", {})
    tasks_list = alloc_data.get("tasks") or alloc_data.get("jobs") or []
    tasks_by_dev = {t.get("device_id"): t for t in tasks_list if isinstance(t, dict)}

    logger.info(f"[*] [할당 수신] alloc_id: {alloc_id} | 작업 수: {len(tasks_list)} | 라우터: {router_info.get('router_num')}")

    results = []
    with ThreadPoolExecutor(max_workers=len(device_ids)) as executor:
        future_map = {}
        for idx, dev_id in enumerate(device_ids):
            task_info = tasks_by_dev.get(dev_id, {"device_id": dev_id, "job_type": "NO_TASK"})
            
            if idx > 0 and stagger_sec > 0:
                logger.info(f"[*] ⏱️ 다음 단말기({dev_id}) {stagger_sec}초 간격 시차 투입 대기...")
                time.sleep(stagger_sec)

            pipeline = DeviceWorkerPipeline(dev_id)
            future = executor.submit(pipeline.execute_task, task_info, router_info)
            future_map[future] = dev_id

        for future in as_completed(future_map):
            dev_id = future_map[future]
            try:
                res = future.result()
                results.append(res)
            except Exception as e:
                logger.error(f"[{dev_id}] 워커 스레드 예외 발생: {e}")
                results.append({
                    "device_id": dev_id,
                    "status": "FAILED",
                    "error_reason": f"WORKER_EXCEPTION: {str(e)}"
                })

    # 작업 결과 일괄 반환
    logger.info(f"[*] ==========================================================================")
    logger.info(f"[*] 📤 서버에 작업 결과 일괄 반환 전송 (alloc_id: {alloc_id})...")
    client.release_tasks(alloc_id, results)

    logger.info(f"[*] ==========================================================================")
    logger.info(f"[*] 📊 배치 실행 요약 리포트")
    for r in results:
        logger.info(f" - [{r.get('device_id')}] 상태: {r.get('status')} | 키워드: '{r.get('keyword')}' | 노출: {r.get('is_exposed')} (순위: {r.get('exposure_rank')}) | 클릭: {r.get('is_clicked')} | 소요: {r.get('execution_sec')}s | 사유: {r.get('error_reason')}")
    logger.info(f"[*] ==========================================================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="N-Shop Staggered Parallel Batch Runner")
    parser.add_argument("--devices", "-d", type=str, default="", help="Comma separated device IDs")
    parser.add_argument("--stagger", "-s", type=float, default=5.0, help="Stagger delay in seconds (default: 5.0)")
    args = parser.parse_args()

    devs = [x.strip() for x in args.devices.split(",") if x.strip()] if args.devices else None
    run_batch(device_ids=devs, stagger_sec=args.stagger)
