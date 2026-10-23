#!/usr/bin/env python3
# ==============================================================================
# scripts/verify_1min_1to3_ip_blocks.py
#
# [1:3 동시성 & 1분 사이클 토글 환경 5회 연속 차단/무사통과 정밀 검증기]
# - 조건: 단말기 3대 (1:3), 사이클당 1분(60초) 완충 및 1분마다 IP 토글, 총 5사이클
# - 판정 기준: "더보기(SHOP_NAV_MORE)" 수행 대상 상품 중
#   1) 무사통과 (SUCCESS)
#   2) 일시적 접속차단 (LOGIN_CHALLENGE_DETECTED, SHOPPING_ACCESS_BLOCKED)
#   * 더보기가 아닌 경우 (SERP 직접 타격 등)는 검증 대상에서 분리/제외
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

LOGS_DIR = ROOT_DIR / "logs"
TODAY_LOG = LOGS_DIR / f"execution_history_{time.strftime('%Y%m%d')}.jsonl"
RESULT_PATH = LOGS_DIR / "verify_1min_1to3_ip_blocks_results.json"

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

def main():
    print("=" * 85)
    print("🚀 [1:3 동시성 & 1분 토글 5회 연속 차단/무사통과 정밀 검증 시작]")
    print("   • 단말기 대수 : 3대 (1:3 동시성)")
    print("   • 사이클 주기 : 1분 (60초 완충 & 1분마다 LTE IP 토글)")
    print("   • 총 실행 횟수 : 5회 사이클 (총 15개 태스크)")
    print("   • 판정 원칙   : '더보기' 수행 건 대상 접속차단 vs 무사통과 판독 (SERP 직타 분리)")
    print("=" * 85)

    start_line = get_log_line_count()
    t_start = time.time()

    cmd = [
        "python3", "-u", "run.py",
        "--net-mode", "lte",
        "-c", "3",
        "--cycles", "5",
        "--min-cycle-dur", "60",
        "--dwell", "25"
    ]

    print(f"\n▶ [러너 가동]: {' '.join(cmd)}")
    p = subprocess.Popen(cmd, cwd=str(ROOT_DIR))
    p.wait()

    t_total = time.time() - t_start
    records = read_log_records_since(start_line)

    print("\n" + "=" * 85)
    print(f"📊 [5회 사이클 실행 완료: 총 소요 {t_total:.1f}초 (평균 사이클: {t_total/5:.1f}초)]")
    print("=" * 85)

    # 분석
    cycles_data = []
    more_candidates = []
    serp_direct = []

    for r in records:
        status = r.get("status")
        st_type = r.get("search_type")
        s_rank = r.get("serp_rank")
        sh_rank = r.get("shopping_rank")
        failed_phase = r.get("failed_phase")
        checkpoints = r.get("checkpoints") or []
        err_msg = str(r.get("error_message") or "")

        # '더보기' 시도 여부 판정:
        # 1) shopping_rank가 있거나 search_type이 msearch인 경우 (쇼핑탭 성공)
        # 2) 실패 단계가 SHOP_NAV_MORE 이거나 에러에 '쇼핑탭'/'더보기'가 포함된 경우
        # 3) checkpoints에 SHOPPING_MORE_TOUCH 가 포함된 경우
        # 4) LOGIN_CHALLENGE나 SHOPPING_ACCESS_BLOCKED로 쇼핑 진입 중 차단된 경우
        is_more = False
        if sh_rank or st_type == "msearch":
            is_more = True
        elif failed_phase in ("SHOP_NAV_MORE", "SHOP_TAB", "TRANSITION_SHOPPING"):
            is_more = True
        elif any("MORE" in str(cp) for cp in checkpoints):
            is_more = True
        elif "LOGIN_CHALLENGE" in str(status) or "SHOPPING_ACCESS_BLOCKED" in str(status):
            is_more = True # 차단은 쇼핑 진입 또는 검색 시 발생하므로 검증 대상에 포함

        item_info = {
            "task_id": r.get("task_id"),
            "device_id": r.get("device_id"),
            "keyword": r.get("keyword"),
            "store_name": r.get("store_name"),
            "nv_mid": r.get("nv_mid"),
            "ip": r.get("ip"),
            "status": status,
            "success": (status == "SUCCESS"),
            "is_more": is_more,
            "rank": sh_rank if sh_rank else s_rank,
            "rank_type": "SHOP" if sh_rank else ("SERP" if s_rank else "-")
        }

        if is_more:
            more_candidates.append(item_info)
        else:
            serp_direct.append(item_info)

    # 더보기 대상 중 무사통과 vs 일시적 차단 집계
    clean_pass = [x for x in more_candidates if x["success"]]
    blocked = [x for x in more_candidates if "LOGIN_CHALLENGE" in str(x["status"]) or "SHOPPING_ACCESS_BLOCKED" in str(x["status"])]
    other_fail = [x for x in more_candidates if not x["success"] and x not in blocked]

    pass_rate = (len(clean_pass) / len(more_candidates) * 100) if more_candidates else 0.0
    block_rate = (len(blocked) / len(more_candidates) * 100) if more_candidates else 0.0

    print(f"\n📋 [더보기(SHOP_NAV_MORE) 대상 정밀 판독 결과]")
    print(f"  • 총 검증 대상 (더보기 진입 시도) : {len(more_candidates)}건 (비-더보기 {len(serp_direct)}건 제외)")
    print(f"  • 🟢 무사통과 (Clean PASS)        : {len(clean_pass)}건 ({pass_rate:.1f}%)")
    print(f"  • 🔴 일시적 접속차단 (BLOCKED)     : {len(blocked)}건 ({block_rate:.1f}%)")
    if other_fail:
        print(f"  • ⚪ 기타 실패 (타임아웃/미노출 등) : {len(other_fail)}건")

    # IP별 분석
    from collections import defaultdict
    ip_summary = defaultdict(lambda: {"total": 0, "pass": 0, "blocked": 0, "tasks": []})
    for x in more_candidates:
        ip = x["ip"] or "UNKNOWN"
        ip_summary[ip]["total"] += 1
        if x["success"]:
            ip_summary[ip]["pass"] += 1
        elif "LOGIN_CHALLENGE" in str(x["status"]) or "SHOPPING_ACCESS_BLOCKED" in str(x["status"]):
            ip_summary[ip]["blocked"] += 1
        ip_summary[ip]["tasks"].append(x)

    print(f"\n🌐 [사용한 공인 IP별 특징 및 무사통과 내역 (총 {len(ip_summary)}개 IP)]:")
    for ip, d in ip_summary.items():
        res_str = "🟢 100% 무사통과" if d["pass"] == d["total"] else (f"🔴 차단 발생 ({d['blocked']}/{d['total']})" if d["blocked"] > 0 else "⚪ 기타")
        print(f"  • IP: {ip:<15} | 더보기 {d['total']}건 중 [성공 {d['pass']}, 차단 {d['blocked']}] ➔ {res_str}")
        for t in d["tasks"]:
            print(f"      ↳ [{t['device_id']}] '{t['keyword']}' ({t['store_name']}) -> {t['status']} (순위: {t['rank']}위 {t['rank_type']})")

    out_obj = {
        "total_duration_sec": round(t_total, 1),
        "avg_cycle_sec": round(t_total / 5, 1),
        "total_records": len(records),
        "more_candidates_count": len(more_candidates),
        "serp_direct_count": len(serp_direct),
        "clean_pass_count": len(clean_pass),
        "clean_pass_rate": round(pass_rate, 1),
        "blocked_count": len(blocked),
        "blocked_rate": round(block_rate, 1),
        "ip_summary": ip_summary,
        "more_tasks": more_candidates,
        "serp_direct_tasks": serp_direct
    }

    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(out_obj, f, indent=2, ensure_ascii=False)

    print(f"\n💾 상세 결과 저장 완료: {RESULT_PATH}")

if __name__ == "__main__":
    main()
