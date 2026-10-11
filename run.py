#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py

N-Shop Macro V1 통합 실행 진입점 (Unified CLI Entrypoint)

사용법 (Modes):
  1. 중앙 API 1회 작업 실행:
     python3 run.py api [--device R3CR70K98XZ] [--dwell 15] [--task-id 123]

  2. 다중 단말기 분산 배치 스케줄러:
     python3 run.py batch [--max-loops 50] [--concurrency 2] [--dwell 15]

  3. 수동 오프라인 타겟 테스트:
     python3 run.py test --keyword "보관백" --nvmid "41733443548" [--store "블루라팡"] [--device R3CR70K98XZ]

  4. 중앙 API 원격 서버 관제 및 배포:
     python3 run.py server status
     python3 run.py server reload
     python3 run.py server logs [-n 50]
     python3 run.py server db "SELECT task_id, status FROM tasks LIMIT 5;"
     python3 run.py server push services/task_service.py
     python3 run.py server pull services/task_service.py

  5. 단말기 정밀 건강 진단:
     python3 run.py check [단말기_시리얼]
"""

import sys
import json
import asyncio
import argparse
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from config.settings import CENTRAL_API_BASE
from src.core.api_client import CentralApiClient
from src.pipeline.conveyor_executor import (
    TaskInput,
    execute_task,
    clean_keyword,
    shorten_keyword
)
from src.device.device_selector import get_online_devices, select_device

# ==============================================================================
# 1. MODE: API (중앙 API 1회 작업 실행)
# ==============================================================================
async def run_api_mode(args):
    api_base = args.api_base or CENTRAL_API_BASE
    client = CentralApiClient(api_base)
    device_arg = args.device or args.physical_device or "phone_01"
    
    print("=" * 60)
    print(f"📡 [중앙 API 작업 요청] {api_base}/api/v1/task/assign (단말기: {device_arg})")
    print("=" * 60)

    try:
        assign_data = client.assign_task(device_id=device_arg, task_id=args.task_id)
    except Exception as e:
        print(f"❌ 작업 할당 API 호출 실패: {e}")
        return

    if not assign_data.get("success"):
        msg = assign_data.get("message") or assign_data.get("error") or "할당 가능한 작업이 없습니다."
        print(f"ℹ️ [스토어 쿨다운 대기 중 / NO_TASK]: {msg}")
        return

    task_id = assign_data.get("task_id")
    raw_kw = assign_data.get("keyword", "")
    nv_mid = assign_data.get("nv_mid")
    compare_id = assign_data.get("compare_id")
    store_name = assign_data.get("store_name")
    nnb = assign_data.get("nnb")
    buc = assign_data.get("buc")
    assigned_ip = assign_data.get("ip")

    print("\n📦 [할당 수신 완료]:")
    print(f"   • Task ID: {task_id}")
    print(f"   • 원본 검색어: {raw_kw}")
    print(f"   • nv_mid: {nv_mid}")
    print(f"   • compare_id: {compare_id or '(단독 상품)'}")
    print(f"   • store_name: {store_name or '(미지정)'}")
    print(f"   • NNB / BUC: {nnb} / {buc[:15] if buc else ''}...")
    print(f"   • 단말기 IP: {assigned_ip or '(미지정)'}")

    task_input = TaskInput(
        task_id=task_id,
        keyword=raw_kw,
        nv_mid=nv_mid,
        compare_id=compare_id,
        store_name=store_name,
        nnb=nnb,
        buc=buc,
        device_id=args.device or args.physical_device,
        dwell_seconds=args.dwell or 15,
        ip=assigned_ip
    )

    print("\n🚀 [매크로 실행 시작]...")
    result = await execute_task(task_input)

    print("\n" + "=" * 50)
    print("📋 [TASK RESULT JSON]:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("=" * 50)

    print("\n📡 [중앙 서버 결과 보고 중]...")
    report_res = client.report_task(result)
    print(f"✅ 결과 보고 응답: {json.dumps(report_res, ensure_ascii=False)}")

# ==============================================================================
# 2. MODE: BATCH (다중 단말기 분산 배치 스케줄러)
# ==============================================================================
async def run_batch_mode(args):
    api_base = args.api_base or CENTRAL_API_BASE
    client = CentralApiClient(api_base)
    max_loops = args.max_loops or 20
    concurrency = max(1, args.concurrency or 2)
    dwell = args.dwell or 15
    sem = asyncio.Semaphore(concurrency)

    print("=" * 60)
    print(f"🚀 [분산 배치 스케줄러 가동] 목표: {max_loops}회 | 동시성: {concurrency}대 | Dwell: {dwell}초")
    print(f"   중앙 API: {api_base}")
    print("=" * 60)

    devices = [args.device] if args.device else get_online_devices()
    if not devices:
        print("❌ 온라인 상태인 단말기가 없습니다.")
        return

    print(f"📱 투입 단말기 풀 ({len(devices)}대): {', '.join(devices)}")

    completed = 0
    success_cnt = 0
    fail_cnt = 0

    async def worker_loop(worker_idx: int):
        nonlocal completed, success_cnt, fail_cnt
        while completed < max_loops:
            async with sem:
                if completed >= max_loops:
                    break
                completed += 1
                cur_num = completed

                target_dev = devices[cur_num % len(devices)]
                print(f"\n🔄 [루프 #{cur_num}/{max_loops}] 단말기 {target_dev} 작업 할당 요청...")

                try:
                    assign_data = client.assign_task(device_id=target_dev)
                except Exception as e:
                    print(f"❌ [루프 #{cur_num}] 할당 에러: {e}")
                    await asyncio.sleep(5)
                    continue

                if not assign_data.get("success"):
                    print(f"ℹ️ [루프 #{cur_num} - NO_TASK]: {assign_data.get('message', '대기 중')} (10초 유휴 대기)")
                    await asyncio.sleep(10)
                    continue

                task_in = TaskInput(
                    task_id=assign_data.get("task_id"),
                    keyword=assign_data.get("keyword"),
                    nv_mid=assign_data.get("nv_mid"),
                    compare_id=assign_data.get("compare_id"),
                    store_name=assign_data.get("store_name"),
                    nnb=assign_data.get("nnb"),
                    buc=assign_data.get("buc"),
                    device_id=target_dev,
                    dwell_seconds=dwell,
                    ip=assign_data.get("ip")
                )

                try:
                    res = await execute_task(task_in)
                    if res.get("success"):
                        success_cnt += 1
                        print(f"🎉 [루프 #{cur_num} 성공] Task #{task_in.task_id} (단말기: {target_dev})")
                    else:
                        fail_cnt += 1
                        print(f"⚠️ [루프 #{cur_num} 실패/PASS] Task #{task_in.task_id}: {res.get('status')}")

                    client.report_task(res)
                except Exception as e:
                    fail_cnt += 1
                    print(f"❌ [루프 #{cur_num} 예외]: {e}")

                await asyncio.sleep(3)

    tasks = [asyncio.create_task(worker_loop(i)) for i in range(concurrency)]
    await asyncio.gather(*tasks)

    print("\n" + "=" * 60)
    print(f"🏁 [배치 스케줄러 완료] 총 {completed}회 완료 (성공: {success_cnt}건, 실패/PASS: {fail_cnt}건)")
    print("=" * 60)

# ==============================================================================
# 3. MODE: TEST (오프라인 수동 테스트)
# ==============================================================================
async def run_test_mode(args):
    if not args.keyword or not args.nvmid:
        print("❌ 수동 테스트 모드는 --keyword 와 --nvmid 가 필수입니다.")
        print("   예: python3 run.py test --keyword '보관백' --nvmid '41733443548'")
        return

    task_in = TaskInput(
        task_id=args.task_id or 9999,
        keyword=args.keyword,
        nv_mid=args.nvmid,
        compare_id=args.compare_id,
        store_name=args.store,
        device_id=args.device,
        dwell_seconds=args.dwell or 10
    )

    print("=" * 60)
    print(f"🧪 [수동 오프라인 테스트] 키워드: '{task_in.keyword}' | nv_mid: {task_in.nv_mid}")
    print(f"   단말기: {task_in.device_id or '(자동 선택)'} | 체류: {task_in.dwell_seconds}초")
    print("=" * 60)

    res = await execute_task(task_in)
    print("\n" + "=" * 50)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    print("=" * 50)

# ==============================================================================
# 4. MODE: SERVER (원격 중앙 API 서버 관제 및 배포)
# ==============================================================================
def run_server_mode(args, sub_args):
    from api.deploy import main as mgr_main
    sys.argv = ["deploy.py"] + sub_args
    mgr_main()

# ==============================================================================
# 5. MODE: CHECK (단말기 건강 정밀 진단)
# ==============================================================================
def run_check_mode(args, unknown=None):
    script = ROOT_DIR / "install" / "04_device_check.sh"
    cmd = [str(script)]
    target_dev = args.device or (unknown[0] if unknown else None)
    if target_dev:
        cmd.append(target_dev)
    subprocess.run(cmd)

# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="N-Shop Macro Unified CLI")
    
    # Intuitive positional mode or flag mode
    parser.add_argument("mode", nargs="?", default="api",
                        choices=["api", "batch", "test", "server", "check"],
                        help="실행 모드 (api, batch, test, server, check)")

    # Common parameters
    parser.add_argument("-d", "--device", "--physical-device", dest="device", type=str, default=None,
                        help="대상 단말기 시리얼 (예: R3CR70K98XZ)")
    parser.add_argument("--dwell", type=int, default=15, help="랜딩 후 체류 시간 (초, 기본: 15)")
    parser.add_argument("--api-base", type=str, default=CENTRAL_API_BASE, help="중앙 API 주소")
    parser.add_argument("--task-id", type=str, default=None, help="특정 task_id 지정")

    # Batch parameters
    parser.add_argument("--max-loops", type=int, default=20, help="배치 최대 반복 수")
    parser.add_argument("--concurrency", type=int, default=2, help="배치 동시 가동 수")

    # Test parameters
    parser.add_argument("--keyword", type=str, default=None, help="테스트 검색어")
    parser.add_argument("--nvmid", type=str, default=None, help="테스트 대상 nv_mid")
    parser.add_argument("--compare-id", type=str, default=None, help="카탈로그 매칭 compare_id")
    parser.add_argument("--store", type=str, default=None, help="스토어명")

    args, unknown = parser.parse_known_args()

    if args.mode == "api":
        asyncio.run(run_api_mode(args))
    elif args.mode == "batch":
        asyncio.run(run_batch_mode(args))
    elif args.mode == "test":
        asyncio.run(run_test_mode(args))
    elif args.mode == "server":
        run_server_mode(args, unknown)
    elif args.mode == "check":
        run_check_mode(args, unknown)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
