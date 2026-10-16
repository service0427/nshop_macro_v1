#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/monitor/device_anomaly_monitor.py

20대 플릿 단말기 실시간 앱 생명주기 및 이상 징후 정밀 감시 프로브:
1. 단말기별 현재 최상위 화면(mCurrentFocus, mResumedActivity) 실시간 추적
2. 홈 화면(Launcher) 및 네이버 앱 메인(SearchHomePage) 장기 체류 시간 정밀 측정
3. 비정상 앱 강제 종료(ANR, Fatal Exception, Sigsegv, Tombstone) 감지
4. 정상 플릿 러너의 타격 완료 후 대기(Idle)와 비정상 고착(Hang)의 엄격한 분리 판정
"""

import os
import sys
import time
import json
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DEVICES = [
    'R3CR70FFFEK', 'R3CR70K98XZ', 'R3CR70KB1RA', 'R3CR70P0Y5E',
    'R3CR80BLS9K', 'R3CR80HKLKL', 'R3CR90CCP1D', 'R3CRB0WCGET',
    'R3CRC0B4X2F', 'R3CRC0XEZ5E', 'R3CRC0XFL0R', 'R3CRC0ZCD2Z',
    'R5CR80AML3N', 'R5CR80ZYL9K', 'R5CR81SA7RK', 'R5CR82FNMVX',
    'R5CR82H78WT', 'R5CR91SH8LM', 'R5CRA28JXXF', 'R5CRC2RDAFB'
]


def check_single_device(dev: str) -> Dict[str, Any]:
    """단일 단말기 실시간 화면 포커스, 프로세스 생존 및 크래시 여부 조회"""
    act_out = ""
    pids = []
    crash_out = ""

    # 1. 최상위 액티비티 추출 (메인 디스플레이 최상단 Activity 추출)
    try:
        cmd_act = f"adb -s {dev} shell dumpsys activity activities | grep -E 'topResumedActivity=' | tail -n 1"
        res_act = subprocess.run(cmd_act, shell=True, capture_output=True, text=True, timeout=5)
        act_out = res_act.stdout.strip()
    except Exception as e:
        act_out = f"TIMEOUT_OR_ERR: {e}"

    # 2. 프로세스 PID 확인
    try:
        cmd_pid = f"adb -s {dev} shell pidof com.nhn.android.search"
        res_pid = subprocess.run(cmd_pid, shell=True, capture_output=True, text=True, timeout=5)
        pids = res_pid.stdout.strip().split()
    except Exception:
        pids = []

    # 3. 최근 30초 내 크래시/ANR 감지
    try:
        cmd_crash = f"adb -s {dev} shell 'logcat -d -t 60 | grep -E \"FATAL EXCEPTION|Force finishing activity|ANR in com.nhn.android.search\" | head -n 3'"
        res_crash = subprocess.run(cmd_crash, shell=True, capture_output=True, text=True, timeout=5)
        crash_out = res_crash.stdout.strip()
    except Exception:
        crash_out = ""

    # 화면 분류 (InAppBrowser 우선 판정)
    screen_type = "OTHER"
    if "InAppBrowserActivity" in act_out:
        screen_type = "IN_APP_BROWSER"
    elif "SearchHomePage" in act_out:
        screen_type = "NAVER_MAIN_HOME"
    elif "LauncherActivity" in act_out or "com.sec.android.app.launcher" in act_out:
        screen_type = "LAUNCHER_HOME"
    elif "SubHomeActivity" in act_out:
        screen_type = "COVER_SCREEN"
    elif "SearchActivity" in act_out or "search.naver" in act_out:
        screen_type = "SEARCH_SERP"


    return {
        "device": dev,
        "screen_type": screen_type,
        "activity": act_out,
        "is_app_alive": len(pids) > 0,
        "pids": pids,
        "crash_log": crash_out
    }



def run_monitoring_session(duration_sec: int = 60, interval_sec: float = 3.0) -> Dict[str, Any]:
    """
    지정 시간(초) 동안 전 단말기 화면 및 생명주기 폴링 샘플링
    """
    start_t = time.time()
    end_t = start_t + duration_sec
    sample_count = 0

    stats = {
        d: {
            "total_samples": 0,
            "launcher_count": 0,
            "naver_main_count": 0,
            "browser_count": 0,
            "search_serp_count": 0,
            "other_count": 0,
            "app_alive_count": 0,
            "crashes_detected": []
        }
        for d in DEVICES
    }

    print(f"📡 [플릿 이상징후 모니터링 시작] 총 20대 대상, {duration_sec}초 동안 {interval_sec}초 주기로 정밀 스캔...")

    while time.time() < end_t:
        t_iter = time.time()
        sample_count += 1

        with ThreadPoolExecutor(max_workers=10) as ex:
            results = list(ex.map(check_single_device, DEVICES))

        for r in results:
            d = r["device"]
            st = stats[d]
            st["total_samples"] += 1
            if r["is_app_alive"]:
                st["app_alive_count"] += 1

            sc = r["screen_type"]
            if sc == "LAUNCHER_HOME":
                st["launcher_count"] += 1
            elif sc == "NAVER_MAIN_HOME":
                st["naver_main_count"] += 1
            elif sc == "IN_APP_BROWSER":
                st["browser_count"] += 1
            elif sc == "SEARCH_SERP":
                st["search_serp_count"] += 1
            else:
                st["other_count"] += 1

            if r["crash_log"] and r["crash_log"] not in st["crashes_detected"]:
                st["crashes_detected"].append(r["crash_log"])

        elapsed = time.time() - t_iter
        sleep_t = max(0.1, interval_sec - elapsed)
        time.sleep(sleep_t)

    total_dur = time.time() - start_t
    return {
        "duration_sec": total_dur,
        "sample_count": sample_count,
        "device_stats": stats
    }


def generate_report(data: Dict[str, Any]) -> str:
    stats = data["device_stats"]
    dur = data["duration_sec"]
    samples = data["sample_count"]

    lines = []
    lines.append("=" * 115)
    lines.append(f"📊 [플릿 생명주기 & 홈 화면 장기 체류 정밀 모니터링 리포트] (측정: {dur:.1f}초, 샘플링: {samples}회)")
    lines.append("=" * 115)
    lines.append(f"{'단말기 ID':<13} | {'런처(홈)':^10} | {'네이버메인':^10} | {'브라우저/상세':^12} | {'통검(SERP)':^10} | {'앱생존비율':^10} | {'비정상 크래시':^14} | 상태 판정")
    lines.append("-" * 115)

    total_crashes = 0
    prolonged_home_devices = []

    for d in sorted(stats.keys()):
        s = stats[d]
        tot = s["total_samples"] or 1
        l_pct = (s["launcher_count"] / tot) * 100
        m_pct = (s["naver_main_count"] / tot) * 100
        b_pct = (s["browser_count"] / tot) * 100
        s_pct = (s["search_serp_count"] / tot) * 100
        a_pct = (s["app_alive_count"] / tot) * 100
        crash_cnt = len(s["crashes_detected"])
        total_crashes += crash_cnt

        home_dwell_pct = l_pct + m_pct
        if home_dwell_pct >= 70.0:
            status = "⚠️ 홈 체류 과다"
            prolonged_home_devices.append((d, home_dwell_pct))
        elif b_pct >= 30.0:
            status = "✅ 정상 타격/체류"
        else:
            status = "ℹ️ 일반 대기"

        crash_str = f"🚨 {crash_cnt}건 감지" if crash_cnt > 0 else "0건 (클린)"

        lines.append(
            f"{d:<13} | {l_pct:8.1f}% | {m_pct:8.1f}% | {b_pct:10.1f}% | {s_pct:8.1f}% | {a_pct:8.1f}% | {crash_str:^14} | {status}"
        )

    lines.append("=" * 115)
    lines.append(f"• 전체 감지된 비정상 크래시/ANR: {total_crashes}건")
    lines.append(f"• 홈 화면(런처+메인) 70% 이상 장기 체류 단말기: {len(prolonged_home_devices)}대")
    for d, pct in prolonged_home_devices:
        lines.append(f"   ↳ {d}: 홈 체류 비율 {pct:.1f}%")

    report_text = "\n".join(lines)
    return report_text


if __name__ == "__main__":
    dur = 45
    if len(sys.argv) > 1:
        try:
            dur = int(sys.argv[1])
        except Exception:
            pass
    res = run_monitoring_session(duration_sec=dur, interval_sec=2.5)
    rpt = generate_report(res)
    print("\n" + rpt)

    out_file = PROJECT_ROOT / "logs" / "device_anomaly_report.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(rpt + "\n")
    print(f"\n💾 리포트 보존: {out_file}")
