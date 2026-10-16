#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/monitor/fleet_screen_watchdog.py

[플릿 화면 상태 고빈도 실시간 감시 & SearchHomePage 자동 탈출 워치독]
1. 10초 주기로 전 단말기(20대)의 최상위 액티비티(ResumedActivity)를 고속 병렬 스캔.
2. 만약 네이버 앱 메인(SearchHomePage)에 멈춰있는 단말기가 감지될 경우:
   - 현재 실행 중인 태스크 프로세스 여부 대조
   - 유휴(IDLE) 상태에서 SearchHomePage가 방치된 경우 -> 'am force-stop'으로 즉각 회수하여 클린 런처로 복귀
   - 작업 중인데 웹뷰로 전환되지 못한 경우 -> SchemeProcessActivity 인텐트 재전송으로 즉각 수화/전환 유도
3. 단말기별 실시간 화면 상태표를 logs/fleet_screen_status.txt에 지속 갱신.
"""

import os
import sys
import time
import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List

NAVER_APP_PACKAGE = "com.nhn.android.search"

DEVICES = [
    'R3CR70FFFEK', 'R3CR70K98XZ', 'R3CR70KB1RA', 'R3CR70P0Y5E',
    'R3CR80BLS9K', 'R3CR80HKLKL', 'R3CR90CCP1D', 'R3CRB0WCGET',
    'R3CRC0B4X2F', 'R3CRC0XEZ5E', 'R3CRC0XFL0R', 'R3CRC0ZCD2Z',
    'R5CR80AML3N', 'R5CR80ZYL9K', 'R5CR81SA7RK', 'R5CR82FNMVX',
    'R5CR82H78WT', 'R5CR91SH8LM', 'R5CRA28JXXF', 'R5CRC2RDAFB'
]

STATUS_FILE = "/home/tech/nshop_macro_v1/logs/fleet_screen_status.txt"


def scan_single_device(dev: str) -> Dict[str, Any]:
    """단일 단말기 실시간 액티비티 및 프로세스 확인"""
    act_name = "UNKNOWN"
    is_app_running = False
    try:
        # 최상위 액티비티 추출 (메인 화면)
        cmd = f"adb -s {dev} shell dumpsys activity activities | grep -E 'topResumedActivity=' | tail -n 1"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3)
        raw = res.stdout.strip()
        if "ActivityRecord{" in raw:
            act_name = raw.split("ActivityRecord{")[-1].split("}")[0].strip().split()[-1]
        elif raw:
            act_name = raw
        else:
            act_name = "SCREEN_OFF_OR_LOCK"

        # 앱 프로세스 생존 확인
        res_pid = subprocess.run(f"adb -s {dev} shell pidof {NAVER_APP_PACKAGE}", shell=True, capture_output=True, text=True, timeout=2)
        pids = res_pid.stdout.strip().split()
        is_app_running = len(pids) > 0
    except Exception as e:
        act_name = f"ERROR: {e}"

    screen_category = "OTHER"
    if "InAppBrowserActivity" in act_name:
        screen_category = "IN_APP_BROWSER"
    elif "SearchHomePage" in act_name:
        screen_category = "STUCK_ON_MAIN"
    elif "SchemeProcessActivity" in act_name:
        screen_category = "SCHEME_ROUTING"
    elif "LauncherActivity" in act_name or "launcher" in act_name.lower():
        screen_category = "LAUNCHER_IDLE"
    elif "SubHomeActivity" in act_name:
        screen_category = "COVER_SCREEN"

    return {
        "device": dev,
        "activity": act_name,
        "category": screen_category,
        "is_app_running": is_app_running
    }


# 단말기별 연속 메인 고착 횟수 추적
STUCK_COUNTER: Dict[str, int] = {}


def get_active_worker_devices() -> List[str]:
    """현재 백그라운드에서 실행 중인 executor 워커 프로세스의 대상 단말기 목록 조회 (fleet_state.json 기반)"""
    active_devs = set()
    # 1. fleet_state.json 검사 (SSOT)
    try:
        from src.monitor.fleet_state import FleetStateManager
        devs_map = FleetStateManager.get_all_devices()
        now = time.time()
        for dev, info in devs_map.items():
            st = info.get("state", "")
            up = info.get("updated_at", 0)
            # 활성 진행 중 상태이면서 최근 120초 이내 갱신된 단말기
            if st in ("STAGGER_WAIT", "LAUNCHING", "SERP", "SHOPPING", "DWELL", "TRANSITION") and (now - up < 120):
                active_devs.add(dev)
    except Exception:
        pass

    # 2. 프로세스 보조 검사
    try:
        res = subprocess.run("ps -ef | grep 'run.py' | grep -v grep", shell=True, capture_output=True, text=True, timeout=2)
        lines = res.stdout.strip().splitlines()
        for line in lines:
            for d in DEVICES:
                if d in line:
                    active_devs.add(d)
    except Exception:
        pass

    return list(active_devs)


def run_watchdog_iteration(auto_heal: bool = True) -> Dict[str, Any]:
    """20대 단말기 전수 스캔 및 이상 화면 안전 치유"""
    t0 = time.time()
    active_workers = get_active_worker_devices()

    with ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(scan_single_device, DEVICES))

    summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scan_duration": round(time.time() - t0, 2),
        "total_devices": len(results),
        "in_browser": sum(1 for r in results if r["category"] == "IN_APP_BROWSER"),
        "stuck_main": sum(1 for r in results if r["category"] == "STUCK_ON_MAIN"),
        "launcher_idle": sum(1 for r in results if r["category"] == "LAUNCHER_IDLE"),
        "routing": sum(1 for r in results if r["category"] == "SCHEME_ROUTING"),
        "other": sum(1 for r in results if r["category"] not in ("IN_APP_BROWSER", "STUCK_ON_MAIN", "LAUNCHER_IDLE", "SCHEME_ROUTING")),
        "active_workers_count": len(active_workers),
        "details": results
    }

    # SearchHomePage 고착 기기 안전 치유
    # 규칙:
    # 1) 작업 중인 단말기는 갓 스폰된 과도기일 수 있으므로 절대 즉시 force-stop 금지!
    # 2) 작업이 없는 유휴 기기라도 최소 6회 연속(60초 이상) 메인에 완전 방치된 경우에만 회수 (오인 사살 원천 방지)
    healed = []
    for r in results:
        dev = r["device"]
        cat = r["category"]
        if cat == "STUCK_ON_MAIN":
            STUCK_COUNTER[dev] = STUCK_COUNTER.get(dev, 0) + 1
            is_worker_active = dev in active_workers

            should_heal = False
            if not is_worker_active and STUCK_COUNTER[dev] >= 6:
                should_heal = True  # 유휴 상태에서 60초 이상 방치된 진짜 고착 기기만 안전 회수
            elif is_worker_active and STUCK_COUNTER[dev] >= 8:
                should_heal = True  # 작업 중인데 80초 이상 웹뷰 전환 못하고 메인 고착

            if auto_heal and should_heal:
                logger.info(f"⚡ [워치독 안전 회수] {dev} (고착 횟수: {STUCK_COUNTER[dev]}, 작업중: {is_worker_active})")
                subprocess.run(f"adb -s {dev} shell am force-stop {NAVER_APP_PACKAGE}", shell=True, timeout=3)
                healed.append(dev)
                STUCK_COUNTER[dev] = 0
        else:
            STUCK_COUNTER[dev] = 0

    summary["healed_devices"] = healed


    # 리포트 파일 갱신
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        f.write(f"📡 [플릿 화면 실시간 감시 대시보드] {summary['timestamp']} (스캔: {summary['scan_duration']}s)\n")
        f.write(f"• 브라우저/쇼핑 활성: {summary['in_browser']}대 | 런처 대기: {summary['launcher_idle']}대 | 메인고착: {summary['stuck_main']}대 | 라우팅: {summary['routing']}대\n")
        if healed:
            f.write(f"• ⚡ 즉각 치유(force-stop 회수): {', '.join(healed)}\n")
        f.write("-" * 90 + "\n")
        f.write(f"{'단말기 ID':^14} | {'화면 상태':^18} | {'앱 프로세스':^12} | {'최상위 액티비티':^40}\n")
        f.write("-" * 90 + "\n")
        for r in results:
            cat_mark = "✅ " if r["category"] == "IN_APP_BROWSER" else ("💤 " if r["category"] == "LAUNCHER_IDLE" else ("🚨 " if r["category"] == "STUCK_ON_MAIN" else "  "))
            app_str = "실행중" if r["is_app_running"] else "종료됨(IDLE)"
            f.write(f"{r['device']:^14} | {cat_mark + r['category']:<18} | {app_str:^12} | {r['activity']:<40}\n")
        f.write("=" * 90 + "\n")

    return summary


if __name__ == "__main__":
    is_daemon = "--daemon" in sys.argv
    dur_arg = 1
    if not is_daemon and len(sys.argv) > 1 and sys.argv[1].isdigit():
        dur_arg = int(sys.argv[1])

    if is_daemon:
        print("🚀 [Watchdog Daemon Started] 감시 주기: 10초")
        while True:
            try:
                s = run_watchdog_iteration(auto_heal=True)
                # stdout 간결 출력
                if s['stuck_main'] > 0 or len(s['healed_devices']) > 0:
                    print(f"[{s['timestamp']}] 활성={s['in_browser']} | 대기={s['launcher_idle']} | 고착={s['stuck_main']} | 치유={len(s['healed_devices'])}대 ({', '.join(s['healed_devices'])})")
            except Exception as e:
                print(f"Watchdog err: {e}")
            time.sleep(10)
    else:
        for i in range(dur_arg):
            s = run_watchdog_iteration(auto_heal=True)
            print(f"[{s['timestamp']}] 브라우저={s['in_browser']} | 런처대기={s['launcher_idle']} | 메인고착={s['stuck_main']} | 치유={len(s['healed_devices'])}대")
            if i < dur_arg - 1:
                time.sleep(10)

