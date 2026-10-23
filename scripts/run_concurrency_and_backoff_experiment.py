#!/usr/bin/env python3
# ==============================================================================
# scripts/run_concurrency_and_backoff_experiment.py
#
# [동시성 단계적 스케일링(1:3 ~ 1:10) 및 차단 회복 쿨다운(0s/5s/10s/30s) 정밀 검증기]
# - 대상 상품: 소림우드 원목도마 (MID: 82891733411, config/campaigns/sorim_wood_10kws.json)
# - 실험 1: 1:3 -> 1:4 -> 1:5 -> 1:6 -> 1:7 -> 1:8 -> 1:9 -> 1:10 동시성별 성공률/차단율 측정
# - 실험 2: 동일 IP 상에서 차단 감지 후 재진입 쿨다운 (0초 vs 5초 vs 10초 vs 30초) 회복률 측정
# ==============================================================================

import os
import sys
import time
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.device.network_controller import get_network_controller

LOGS_DIR = ROOT_DIR / "logs"
CAMPAIGN_PATH = ROOT_DIR / "config" / "campaigns" / "sorim_wood_10kws.json"
TODAY_LOG = LOGS_DIR / f"execution_history_{time.strftime('%Y%m%d')}.jsonl"
EXP_RESULT_PATH = LOGS_DIR / "experiment_concurrency_and_backoff_results.json"

ctrl = get_network_controller(mode="lte")

def get_log_line_count() -> int:
    if not TODAY_LOG.exists():
        return 0
    with open(TODAY_LOG, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)

def read_log_records_since(start_line: int) -> List[Dict[str, Any]]:
    if not TODAY_LOG.exists():
        return []
    records = []
    with open(TODAY_LOG, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if idx >= start_line:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass
    return records

def run_cmd(cmd_list: List[str], timeout: int = 180) -> subprocess.CompletedProcess:
    print(f"\n▶ [실행 명령]: {' '.join(cmd_list)}")
    t0 = time.time()
    res = subprocess.run(cmd_list, cwd=str(ROOT_DIR), capture_output=True, text=True, timeout=timeout)
    dur = time.time() - t0
    print(f"  ↳ 소요 시간: {dur:.1f}s | 반환 코드: {res.returncode}")
    return res

def summarize_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(records)
    success = sum(1 for r in records if r.get("status") == "SUCCESS")
    challenge = sum(1 for r in records if "LOGIN_CHALLENGE" in str(r.get("status")))
    waf_block = sum(1 for r in records if "SHOPPING_ACCESS_BLOCKED" in str(r.get("status")) or "WAF" in str(r.get("status")))
    not_found = sum(1 for r in records if "NOT_FOUND" in str(r.get("status")))
    other = total - success - challenge - waf_block - not_found
    rate = (success / total * 100) if total > 0 else 0.0
    return {
        "total": total,
        "success": success,
        "success_rate": round(rate, 1),
        "login_challenge": challenge,
        "waf_block": waf_block,
        "not_found": not_found,
        "other": other,
        "details": [
            {"device": r.get("device_id"), "kw": r.get("keyword"), "status": r.get("status"), "rank": r.get("serp_rank") or r.get("shopping_rank")}
            for r in records
        ]
    }

def main():
    print("=" * 85)
    print("🔬 [동시성 스케일링(1:3 ~ 1:10) 및 차단 회복 쿨다운(0s/5s/10s/30s) 정밀 검증 실험 시작]")
    print(f"   • 대상 상품 : 소림우드 원목도마 ({CAMPAIGN_PATH})")
    print(f"   • 네트워크 : LTE 동글 단일 공인 IP 환경")
    print("=" * 85)

    all_results = {
        "concurrency_scaling": {},
        "backoff_recovery": {}
    }

    # =========================================================================
    # [실험 1] 1:3부터 1:10까지 동시성 단계별 단일 사이클 테스트
    # =========================================================================
    print("\n" + "#" * 85)
    print("📊 [실험 1단계: 동시성 스케일링 1:3 ~ 1:10 단계별 검증]")
    print("#" * 85)

    concurrency_levels = [3, 4, 5, 6, 7, 8, 9, 10]

    for c in concurrency_levels:
        print(f"\n🔄 [1:{c} 검증 전 LTE 공인 IP 신규 토글]...")
        t_res = ctrl.toggle_ip()
        print(f"   ↳ IP 변경: {t_res.get('old_ip')} -> {t_res.get('new_ip')}")
        time.sleep(3.0)

        print(f"--- [1:{c} 동시성 테스트 (단말기 {c}대 투입)] ---")
        line_start = get_log_line_count()
        t_start = time.time()

        cmd = [
            "python3", "run.py",
            "--net-mode", "lte",
            "--campaign", str(CAMPAIGN_PATH),
            "-c", str(c),
            "--once",
            "--fresh-campaign"
        ]

        try:
            run_cmd(cmd, timeout=180)
        except subprocess.TimeoutExpired:
            print(f"⚠️ 1:{c} 테스트 타임아웃 발생 (180초 초과)")

        t_elapsed = time.time() - t_start
        new_records = read_log_records_since(line_start)
        summary = summarize_records(new_records)
        summary["cycle_elapsed_sec"] = round(t_elapsed, 1)

        print(f"  📊 [결과 1:{c}] 총 {summary['total']}건 | 성공 {summary['success']}건 ({summary['success_rate']}%) | 챌린지 {summary['login_challenge']}건 | WAF {summary['waf_block']}건 (소요 {summary['cycle_elapsed_sec']}s)")
        all_results["concurrency_scaling"][f"1:{c}"] = summary

        # 중간 저장
        with open(EXP_RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)

        time.sleep(5.0)

    # =========================================================================
    # [실험 2] 동일 IP 상에서 차단 발생 시 회복 대기시간 검증 (0초 vs 5초 vs 10초 vs 30초)
    # =========================================================================
    print("\n" + "#" * 85)
    print("⏱️ [실험 2단계: 차단 발생 시 쿨다운 회복 시간(0s / 5s / 10s / 30s) 정밀 검증]")
    print("   • 동일 공인 IP 유지 상태(--no-toggle)에서 연속 타격 시 성공/차단 전이 양상 관측")
    print("#" * 85)

    backoff_delays = [0, 5, 10, 30]

    for delay in backoff_delays:
        print(f"\n🔄 [{delay}s 검증 전 LTE 공인 IP 신규 토글]...")
        t_res = ctrl.toggle_ip()
        print(f"   ↳ IP 변경: {t_res.get('old_ip')} -> {t_res.get('new_ip')}")
        time.sleep(3.0)

        print(f"\n--- [동일 IP 쿨다운 {delay}초 대기 검증] ---")
        line_start = get_log_line_count()

        # 1차 타격 (3대 동시 기동으로 세션 활성화 및 상태 체크)
        cmd_first = [
            "python3", "run.py",
            "--net-mode", "lte",
            "--campaign", str(CAMPAIGN_PATH),
            "-c", "3",
            "--once",
            "--no-toggle",
            "--fresh-campaign"
        ]
        run_cmd(cmd_first, timeout=120)
        rec_first = read_log_records_since(line_start)
        s_first = summarize_records(rec_first)
        print(f"  ↳ 1차 타격: 총 {s_first['total']}건 | 성공 {s_first['success']}건 | 챌린지 {s_first['login_challenge']}건")

        # 지정된 쿨다운 대기
        if delay > 0:
            print(f"  ⏳ [쿨다운 완충 대기] {delay}초간 요청 일체 중단...")
            time.sleep(float(delay))
        else:
            print("  ⚡ [즉시 후속 타격 (0초 대기: 무리하게 밀어붙이기)]")

        # 2차 타격 (동일 IP에서 3대 후속 기동)
        line_mid = get_log_line_count()
        cmd_second = [
            "python3", "run.py",
            "--net-mode", "lte",
            "--campaign", str(CAMPAIGN_PATH),
            "-c", "3",
            "--once",
            "--no-toggle",
            "--fresh-campaign"
        ]
        run_cmd(cmd_second, timeout=120)
        rec_second = read_log_records_since(line_mid)
        s_second = summarize_records(rec_second)
        print(f"  ↳ 2차 후속 타격: 총 {s_second['total']}건 | 성공 {s_second['success']}건 ({s_second['success_rate']}%) | 챌린지 {s_second['login_challenge']}건")

        all_results["backoff_recovery"][f"{delay}s_wait"] = {
            "first_run": s_first,
            "backoff_sec": delay,
            "second_run": s_second
        }

        # 중간 저장
        with open(EXP_RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 85)
    print(f"🎉 [실험 전 과정 완료] 결과가 '{EXP_RESULT_PATH}'에 저장되었습니다.")
    print("=" * 85)

if __name__ == "__main__":
    main()
