#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/tools/harvest_fleet_35.py

20대 단말기 고속 병렬 플릿을 활용한 50대 대표 대형 키워드 35위 순수 오가닉 꼬리 상품 전수 수집기
- 50대 대형 일반 e-커머스 키워드를 20대 단말기에 분산 할당
- 통합검색 -> 쇼핑섹션 .more 정식 실물 터치(CDP Real Touch) -> 쇼핑탭 __NEXT_DATA__ 전수 덤프
- 35위 순수 오가닉 타겟 상품 즉시 추출 및 JSON 파일 격리 보관
"""

import sys
import time
import json
import logging
import asyncio
import subprocess
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.models import TaskInput
from src.pipeline.executor import execute_task_pipeline
from src.device.network_controller import get_network_controller
from src.device.device_selector import get_online_devices
from src.device.adb_controller import force_stop_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("FleetHarvester")

# 50대 대표 대형 일반 e-커머스 키워드 (100% 순수 일반 쇼핑 카테고리)
MAJOR_ECOMMERCE_KEYWORDS_50 = [
    # 1. 식품 / 신선 / 건강 (8)
    "감자", "갓김치", "고춧가루", "깐마늘", "깻잎", "돼지고기다짐육", "땅콩", "레드비트",
    # 2. 가구 / 인테리어 / 침구 (7)
    "수납박스", "메모리폼매트리스", "그릇정리대", "대나무돗자리", "발매트", "빨래건조대", "도마",
    # 3. 스포츠 / 레저 / 캠핑 (7)
    "골프장갑", "골프거리측정기", "마라톤운동양말", "캠핑의자", "요가매트", "원터치텐트", "실내자전거",
    # 4. 생활 / 주방 / 욕실 (9)
    "냉면용기", "도시락가방", "도어체크", "수면안대", "손목보호대", "텀블러", "우산", "샤워기헤드", "물티슈",
    # 5. 패션 / 잡화 (7)
    "24인치캐리어", "남자반바지", "남자향수", "남자미니크로스백", "레디백", "선글라스", "리본끈",
    # 6. 가전 / 디지털 / 모바일 (9)
    "냉난방기", "차량용거치대", "보조배터리", "무선청소기", "마우스패드", "드라이기", "블루투스스피커", "선풍기", "에어프라이어",
    # 7. 문구 / 사무 / 뷰티 (3)
    "6공다이어리", "마이크커버", "폼클렌징"
]


def run_single_harvest_task(device_id: str, keyword: str, task_idx: int) -> Dict[str, Any]:
    """단일 단말기에서 특정 키워드로 쇼핑탭 35위 탐색 및 __NEXT_DATA__ 덤프 수행"""
    # 단말기 동시 스폰 시 USB 버스 락 충돌 방지 0.35초 시차 완충
    time.sleep((task_idx % 20) * 0.35)
    t0 = time.time()
    task_input = TaskInput(
        device_id=device_id,
        task_id=999000 + task_idx,
        keyword=keyword,
        target_rank=999,
        nv_mid="",
        store_name="",
        dwell_seconds=1,
        target_cycle_dur=30.0,
        task_start_time=t0,
        cycle_ymd=time.strftime("%Y%m%d"),
        cycle_his=time.strftime("%H%M%S"),
        scroll_mode="real_swipe",
        node_id="harvester-node"
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        res = loop.run_until_complete(asyncio.wait_for(execute_task_pipeline(task_input), timeout=45.0))
        dur = round(time.time() - t0, 1)
        if hasattr(res, "to_dict"):
            res_dict = res.to_dict()
        elif hasattr(res, "__dict__"):
            res_dict = vars(res)
        elif isinstance(res, dict):
            res_dict = res
        else:
            res_dict = {"status": str(res)}
        res_dict["duration_seconds"] = dur
        res_dict["keyword"] = keyword
        res_dict["device_id"] = device_id
        return res_dict
    except Exception as e:
        dur = round(time.time() - t0, 1)
        force_stop_app(device_id)
        return {
            "device_id": device_id,
            "keyword": keyword,
            "status": "EXCEPTION",
            "error_message": str(e),
            "duration_seconds": dur
        }
    finally:
        loop.close()


def run_fleet_harvest(limit: int = 50):
    devices = get_online_devices(force_refresh=True)
    if not devices:
        print("❌ 연결된 ADB 단말기가 없습니다.")
        return

    all_kws = MAJOR_ECOMMERCE_KEYWORDS_50[:limit]
    
    # 이미 logs/harvest/raw에 존재하는 키워드 확인
    import glob
    raw_files = glob.glob(str(PROJECT_ROOT / "logs" / "harvest" / "raw" / "*.json"))
    existing_kws = set()
    for f in raw_files:
        base = Path(f).name
        kw = base.split("_")[0]
        existing_kws.add(kw)

    missing_kws = [k for k in all_kws if k not in existing_kws]

    print("=" * 90)
    print(f"🚀 [20대 단말기 고속 병렬 플릿 가동] 50대 대표 키워드 __NEXT_DATA__ 전수 수집")
    print(f"   • 투입 단말기 수 : {len(devices)}대")
    print(f"   • 전체 키워드 수 : {len(all_kws)}개")
    print(f"   • 기수집 완료    : {len(all_kws) - len(missing_kws)}개 (스킵)")
    print(f"   • 신규 수집 대상 : {len(missing_kws)}개")
    print(f"   • 추출 기준      : 30~40위 오가닉 단일 상품 (판매처 미묶음, 40위 우선)")
    print("=" * 90)

    if missing_kws:
        # 1. 고속 로컬 이더넷 통신망 점검 및 단말기 일괄 터널링
        net_ctrl = get_network_controller("local")
        net_ctrl.setup()
        net_ctrl.connect_devices(devices)
        time.sleep(1.0)

        # 2. 배치 분할 실행 (20대씩 동시 병렬)
        batch_size = len(devices)
        all_results = []
        total_batches = (len(missing_kws) + batch_size - 1) // batch_size

        for b_idx in range(total_batches):
            batch_kws = missing_kws[b_idx * batch_size : (b_idx + 1) * batch_size]
            print(f"\n📦 [배치 {b_idx+1}/{total_batches}] {len(batch_kws)}개 키워드 20대 동시 병렬 기동...", flush=True)
            t_batch_start = time.time()

            tasks_to_run = []
            for i, kw in enumerate(batch_kws):
                dev = devices[i % len(devices)]
                tasks_to_run.append((dev, kw, b_idx * batch_size + i))

            with concurrent.futures.ProcessPoolExecutor(max_workers=len(tasks_to_run)) as executor:
                futures = {
                    executor.submit(run_single_harvest_task, dev, kw, idx): kw
                    for dev, kw, idx in tasks_to_run
                }
                for fut in concurrent.futures.as_completed(futures):
                    kw_name = futures[fut]
                    try:
                        r = fut.result()
                        all_results.append(r)
                        st = r.get("status", "UNKNOWN")
                        dur = r.get("duration_seconds", 0)
                        dev = r.get("device_id")
                        print(f"   ↳ [{dev}] '{kw_name:<10}' 완료 ({dur:>4.1f}s) -> 상태: {st}", flush=True)
                    except Exception as e:
                        print(f"   ↳ ❌ '{kw_name}' 예외: {e}", flush=True)

            print(f"✅ [배치 {b_idx+1} 완료] 소요: {round(time.time() - t_batch_start, 1)}초", flush=True)

    # 3. 새로운 30~40위 순수 단일 상품 추출기 실행
    from src.tools.extract_single_tail_products import extract_single_tail_products
    final_targets = extract_single_tail_products(target_kws=all_kws, min_rank=30, max_rank=40)

    print("\n" + "=" * 90)
    print(f"🎉 [50대 대표 키워드 30~40위 단일 상품 추출 완료] 총 {len(final_targets)}개 확보")
    print("=" * 90)
    print(f"{'순위':>4} | {'키워드':<14} | {'MID':<13} | {'판매처/몰명':<16} | {'가격':>8}원 | 상품명")
    print("-" * 90)
    for t in final_targets:
        print(f"{t['rank']:>3}위 | {t['keyword'][:13]:<14} | {t['nv_mid']:<13} | {t['mall_name'][:15]:<16} | {t['price']:>8}원 | {t['product_title'][:25]}")
    print("=" * 90)


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 50
    run_fleet_harvest(limit)
