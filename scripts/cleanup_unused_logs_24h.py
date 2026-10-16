#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/cleanup_unused_logs_24h.py

24시간 경과 미사용 로그 및 히스토리 안전 정제 스크립트
---------------------------------------------------------
- 사용자 엄명: "무턱대고 다 지우지말고, 사용하지 않는 logs 폴더의 파일중에서 24시간 지난것을 지워"
- 현재 활성 모니터링/러너 필수 파일 및 최근 24시간 이내 데이터는 100% 보존.
- 24시간 이전의 미사용 대용량 캡처, 트래픽 세션, 구형 실행 로그만 안전하게 선별 제거.
"""

import os
import sys
import time
import shutil
import argparse
from pathlib import Path
from typing import Set, Tuple, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"

# 100% 필수 보존 파일 목록 (실시간 모니터링/어제 순위 대조용)
PROTECTED_EXACT_NAMES: Set[str] = {
    "run_master.log",
    "fleet_state.json",
    "latest_eval_report.json",
    "latest_eval_report.txt",
    "device_anomaly_report.txt",
    "fleet_screen_status.txt",
    "fleet_watchdog.log",
    "active_50_targets.json",
    "organic_candidates_30_40.tsv",
    "pm2_stop_2350.log",
}

# 100% 필수 보존 디렉토리
PROTECTED_DIRS: Set[str] = {
    "data", # execution_history.json 등 영구 누적 데이터
}


def get_dir_size(path: Path) -> int:
    """디렉토리 총 용량 계산"""
    total = 0
    try:
        for p in path.glob("**/*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except Exception:
                    pass
    except Exception:
        pass
    return total


def run_cleanup(dry_run: bool = False, hours: float = 24.0) -> Tuple[int, int]:
    now = time.time()
    cutoff = now - (hours * 3600)
    cutoff_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(cutoff))
    today_str = time.strftime("%Y%m%d", time.localtime(now))
    yesterday_str = time.strftime("%Y%m%d", time.localtime(now - 86400))

    print(f"🧹 [24시간 로그 정제 시작] 기준 시각: {cutoff_str} 이전 (24시간 경과)")
    if dry_run:
        print("⚠️ [DRY RUN 모드] 실제 파일 삭제 없이 대상만 점검합니다.\n")

    total_bytes_freed = 0
    total_items_removed = 0

    # 1. 루트 logs/ 디렉토리의 단독 파일 점검
    print("📁 [1/6] logs/ 루트 레벨 미사용 파일 검사...")
    for item in sorted(LOGS_DIR.iterdir()):
        if not item.is_file():
            continue
        fname = item.name

        # 필수 보호 파일은 절대 건드리지 않음
        if fname in PROTECTED_EXACT_NAMES:
            continue
        # 오늘 및 어제 execution_history 파일은 베이스라인 비교용으로 보존
        if fname in (f"execution_history_{today_str}.jsonl", f"execution_history_{yesterday_str}.jsonl"):
            continue

        try:
            st = item.stat()
            if st.st_mtime < cutoff:
                sz = st.st_size
                total_bytes_freed += sz
                total_items_removed += 1
                mtime_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
                print(f"   🗑️ 삭제 대상: {fname} ({sz / (1024*1024):.2f} MB, {mtime_str})")
                if not dry_run:
                    item.unlink()
        except Exception as e:
            print(f"   ⚠️ 오류 ({fname}): {e}")

    # 2. logs/captures/ 내 24시간 경과 스크린샷 점검
    captures_dir = LOGS_DIR / "captures"
    if captures_dir.exists() and captures_dir.is_dir():
        print(f"\n📁 [2/6] logs/captures/ 24시간 경과 스크린샷 검사...")
        cap_del_count = 0
        cap_del_bytes = 0
        for f in captures_dir.iterdir():
            if not f.is_file():
                continue
            try:
                st = f.stat()
                if st.st_mtime < cutoff:
                    sz = st.st_size
                    cap_del_bytes += sz
                    cap_del_count += 1
                    if not dry_run:
                        f.unlink()
            except Exception:
                pass
        total_bytes_freed += cap_del_bytes
        total_items_removed += cap_del_count
        print(f"   🗑️ captures 정리: {cap_del_count}개 파일 ({cap_del_bytes / (1024**3):.2f} GB)")

    # 3. logs/traffic/ 내 24시간 경과 세션 점검
    traffic_dir = LOGS_DIR / "traffic"
    if traffic_dir.exists() and traffic_dir.is_dir():
        print(f"\n📁 [3/6] logs/traffic/ 24시간 경과 세션 검사...")
        traf_del_dirs = 0
        traf_del_bytes = 0
        for date_dir in sorted(traffic_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            dname = date_dir.name
            if dname < yesterday_str:
                # 어제 이전의 모든 날짜 폴더는 전량 삭제
                sz = get_dir_size(date_dir)
                traf_del_bytes += sz
                traf_del_dirs += 1
                print(f"   🗑️ 날짜 폴더 삭제: {dname}/ ({sz / (1024**3):.2f} GB)")
                if not dry_run:
                    shutil.rmtree(date_dir, ignore_errors=True)
            elif dname == yesterday_str:
                # 어제 폴더는 24시간 기준 시간 단위로 세분화하여 삭제
                for sub in sorted(date_dir.iterdir()):
                    if not sub.is_dir():
                        continue
                    try:
                        st = sub.stat()
                        if st.st_mtime < cutoff:
                            sz = get_dir_size(sub)
                            traf_del_bytes += sz
                            traf_del_dirs += 1
                            if not dry_run:
                                shutil.rmtree(sub, ignore_errors=True)
                    except Exception:
                        pass
        total_bytes_freed += traf_del_bytes
        total_items_removed += traf_del_dirs
        print(f"   🗑️ traffic 정리: {traf_del_dirs}개 세션 디렉토리 ({traf_del_bytes / (1024**3):.2f} GB)")

    # 4. logs/lte/ 내 24시간 경과 요약 결과 점검
    lte_dir = LOGS_DIR / "lte"
    if lte_dir.exists() and lte_dir.is_dir():
        print(f"\n📁 [4/6] logs/lte/ 24시간 경과 세션 검사...")
        lte_del_dirs = 0
        lte_del_bytes = 0
        for date_dir in sorted(lte_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            dname = date_dir.name
            if dname < yesterday_str:
                sz = get_dir_size(date_dir)
                lte_del_bytes += sz
                lte_del_dirs += 1
                print(f"   🗑️ lte 날짜 폴더 삭제: {dname}/ ({sz / (1024*1024):.2f} MB)")
                if not dry_run:
                    shutil.rmtree(date_dir, ignore_errors=True)
            elif dname == yesterday_str:
                for sub in sorted(date_dir.iterdir()):
                    if not sub.is_dir():
                        continue
                    try:
                        st = sub.stat()
                        if st.st_mtime < cutoff:
                            sz = get_dir_size(sub)
                            lte_del_bytes += sz
                            lte_del_dirs += 1
                            if not dry_run:
                                shutil.rmtree(sub, ignore_errors=True)
                    except Exception:
                        pass
        total_bytes_freed += lte_del_bytes
        total_items_removed += lte_del_dirs
        print(f"   🗑️ lte 정리: {lte_del_dirs}개 디렉토리 ({lte_del_bytes / (1024*1024):.2f} MB)")

    # 5. logs/harvest/raw/ 내 24시간 경과 임시 JSON 점검
    harvest_raw = LOGS_DIR / "harvest" / "raw"
    if harvest_raw.exists() and harvest_raw.is_dir():
        print(f"\n📁 [5/6] logs/harvest/raw/ 24시간 경과 수집 JSON 검사...")
        hr_del_count = 0
        hr_del_bytes = 0
        for f in harvest_raw.iterdir():
            if not f.is_file():
                continue
            try:
                st = f.stat()
                if st.st_mtime < cutoff:
                    sz = st.st_size
                    hr_del_bytes += sz
                    hr_del_count += 1
                    if not dry_run:
                        f.unlink()
            except Exception:
                pass
        total_bytes_freed += hr_del_bytes
        total_items_removed += hr_del_count
        print(f"   🗑️ harvest/raw 정리: {hr_del_count}개 파일 ({hr_del_bytes / (1024*1024):.2f} MB)")

    # 6. logs/local, logs/wg, logs/packet_experiment, logs/test 등 과거 단발성 폴더 내 24시간 경과 데이터
    misc_dirs = ["local", "wg", "packet_experiment", "test", "analysis"]
    print(f"\n📁 [6/6] 기타 임시/과거 테스트 디렉토리 검사...")
    misc_del_count = 0
    misc_del_bytes = 0
    for md in misc_dirs:
        p = LOGS_DIR / md
        if not p.exists() or not p.is_dir():
            continue
        for item in list(p.iterdir()):
            try:
                st = item.stat()
                if st.st_mtime < cutoff:
                    if item.is_file():
                        sz = st.st_size
                        misc_del_bytes += sz
                        misc_del_count += 1
                        if not dry_run:
                            item.unlink()
                    elif item.is_dir():
                        sz = get_dir_size(item)
                        misc_del_bytes += sz
                        misc_del_count += 1
                        if not dry_run:
                            shutil.rmtree(item, ignore_errors=True)
            except Exception:
                pass
    total_bytes_freed += misc_del_bytes
    total_items_removed += misc_del_count
    print(f"   🗑️ 기타 디렉토리 정리: {misc_del_count}개 항목 ({misc_del_bytes / (1024*1024):.2f} MB)")

    print(f"\n✨ [정리 완료 요약]")
    print(f"   • 총 제거된 항목: {total_items_removed:,}개")
    print(f"   • 확보된 디스크 공간: {total_bytes_freed / (1024**3):.2f} GB")
    return total_items_removed, total_bytes_freed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="24시간 경과 미사용 로그 및 히스토리 안전 정제")
    parser.add_argument("--dry-run", action="store_true", help="실제 삭제 없이 대상 및 용량 점검")
    parser.add_argument("--hours", type=float, default=24.0, help="보존 시간 기준 (기본 24.0시간)")
    args = parser.parse_args()

    run_cleanup(dry_run=args.dry_run, hours=args.hours)
