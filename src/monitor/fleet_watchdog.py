#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/monitor/fleet_watchdog.py

2분 단위 N-Shop 플릿 구동 실시간 워치독 (Fleet Watchdog)
-------------------------------------------------------
1. 2분(120초) 주기로 최근 실행 세션 품질 및 프로세스 상태 전수 점검
2. 절대 철칙 위반 감지 시 즉시 run.py 긴급 중지(KILL) 및 EMERGENCY_STOP 플래그 생성:
   - 광고(CPC/ader/adcr) 오클릭 감지 시 -> 즉시 중지
   - 카탈로그(판매처 묶음 상품) 오클릭 감지 시 -> 즉시 중지
   - 연속 3회 이상 IP 429 차단([에러페이지]) 발생 시 -> 즉시 중지
   - 연속 3회 이상 로그인 팝업 발생 시 -> 즉시 중지
3. 2분마다 정밀 상태 리포트 출력 및 로그 저장
"""

import os
import sys
import time
import json
import signal
import subprocess
from pathlib import Path
from typing import Dict, Any, List

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.monitor.click_quality_agent import ClickQualityAuditor

TRAFFIC_DIR = ROOT_DIR / "logs" / "traffic"
WATCHDOG_LOG = ROOT_DIR / "logs" / "fleet_watchdog.log"
EMERGENCY_FLAG = ROOT_DIR / "logs" / "EMERGENCY_STOP.flag"


def log_watchdog(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def kill_fleet_runner():
    """run.py 플릿 실행기 및 하위 프로세스 긴급 종료"""
    log_watchdog("🚨 [EMERGENCY KILL] run.py 플릿 프로세스 강제 중지 실행...")
    subprocess.run("pkill -9 -f 'run.py --net-mode lte' || true", shell=True)
    try:
        with open(EMERGENCY_FLAG, "w", encoding="utf-8") as f:
            f.write(f"STOPPED_AT={time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    except Exception:
        pass


def run_watchdog_cycle(watchdog_start_time: float) -> Dict[str, Any]:
    """단일 2분 주기 점검 수행 (워치독 기동 이후 생성된 세션만 검수)"""
    auditor = ClickQualityAuditor()
    all_audits = auditor.scan_recent_sessions(limit=25)
    
    # 0. 워치독 기동 이후 생성된 세션만 필터링
    audits = []
    for a in all_audits:
        s_dir = Path(a["session_dir"])
        tf = s_dir / "traffic.json"
        if tf.exists() and os.path.getmtime(tf) >= watchdog_start_time:
            audits.append(a)

    # 1. 프로세스 생존 점검
    res = subprocess.run("pgrep -f 'run.py --net-mode lte'", shell=True, capture_output=True, text=True)
    is_running = bool(res.stdout.strip())
    pids = res.stdout.strip().split()

    if not is_running:
        log_watchdog("ℹ️ [Watchdog] run.py 프로세스가 종료되었거나 미구동 상태입니다.")
        return {"status": "PROCESS_NOT_RUNNING", "action": "NONE"}

    if not audits:
        log_watchdog(f"⏳ [Watchdog] run.py (PID={pids}) 기동 중이나, 워치독 기동 이후 완료된 신규 세션 대기 중...")
        return {"status": "HEALTHY", "pids": pids, "audits_count": 0}

    # 2. 최근 감사 세션 검수
    ad_clicks = [a for a in audits if a.get("is_ad_clicked")]
    catalog_clicks = [a for a in audits if a.get("is_catalog_clicked")]
    ip_429_blocks = [a for a in audits if a.get("is_ip_rate_limited")]
    login_popups = [a for a in audits if "네이버 로그인 팝업" in str(a.get("issues", []))]

    # [치명적 1: 광고 클릭 감지]
    if ad_clicks:
        reason = f"치명적 오류: 광고(CPC/adcr/ader) 클릭 {len(ad_clicks)}건 감지됨!"
        log_watchdog(f"💥 {reason}")
        kill_fleet_runner()
        return {"status": "ABORTED", "reason": reason, "detail": ad_clicks[0]}

    # [치명적 2: 카탈로그(판매처 묶음) 오클릭 감지]
    if catalog_clicks:
        reason = f"치명적 오류: 판매처 묶음 상품(카탈로그) 클릭 {len(catalog_clicks)}건 감지됨!"
        log_watchdog(f"💥 {reason}")
        kill_fleet_runner()
        return {"status": "ABORTED", "reason": reason, "detail": catalog_clicks[0]}

    # [치명적 3: 연속 3회 이상 429 차단 지속]
    recent_3 = audits[:3]
    recent_429_count = sum(1 for a in recent_3 if a.get("is_ip_rate_limited"))
    if len(recent_3) >= 3 and recent_429_count >= 3:
        reason = "치명적 오류: 연속 3회 이상 IP 429 차단([에러페이지]) 지속 발생! (IP 풀 고갈 또는 망 차단)"
        log_watchdog(f"💥 {reason}")
        kill_fleet_runner()
        return {"status": "ABORTED", "reason": reason, "detail": recent_3}

    # [치명적 4: 연속 3회 이상 로그인 팝업]
    recent_login_count = sum(1 for a in recent_3 if "네이버 로그인 팝업" in str(a.get("issues", [])))
    if len(recent_3) >= 3 and recent_login_count >= 3:
        reason = "치명적 오류: 연속 3회 이상 네이버 로그인 창 강제 발생!"
        log_watchdog(f"💥 {reason}")
        kill_fleet_runner()
        return {"status": "ABORTED", "reason": reason, "detail": recent_3}

    # 3. 정상 상태 집계 보고
    total = len(audits)
    pass_cnt = sum(1 for a in audits if a.get("passed"))
    pass_rate = round((pass_cnt / total * 100), 1) if total > 0 else 0.0

    log_watchdog(
        f"✅ [Watchdog 2분 정상 순항] PID={pids} | 최근 {total}세션 PASS={pass_cnt}건({pass_rate}%) | "
        f"광고=0건 | 카탈로그=0건 | 429차단={len(ip_429_blocks)}건"
    )

    return {
        "status": "HEALTHY",
        "pids": pids,
        "pass_rate": pass_rate,
        "total_audits": total,
        "pass_count": pass_cnt,
        "ip_429_count": len(ip_429_blocks),
        "latest": audits[0] if audits else None
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="2-Minute Interval Fleet Watchdog")
    parser.add_argument("--interval", type=int, default=120, help="Check interval in seconds (default: 120)")
    parser.add_argument("--once", action="store_true", help="Run single check cycle and exit")
    args = parser.parse_args()

    # 기존 플래그 제거
    if EMERGENCY_FLAG.exists():
        try:
            EMERGENCY_FLAG.unlink()
        except Exception:
            pass

    start_time = time.time()
    log_watchdog(f"🐕 [Fleet Watchdog 기동] 감시 주기: {args.interval}초 | 비상정지 플래그 초기화 완료 (시작: {time.strftime('%Y-%m-%d %H:%M:%S')})")

    if args.once:
        res = run_watchdog_cycle(start_time)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    while True:
        try:
            res = run_watchdog_cycle(start_time)
            if res.get("status") == "ABORTED":
                log_watchdog(f"🛑 [워치독 비상 정지 완료] 사유: {res.get('reason')}")
                break
        except Exception as e:
            log_watchdog(f"⚠️ [워치독 사이클 예외] {e}")

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
