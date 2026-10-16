#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/tools/simulate_daily_v2.py

[일자별 가상 사이트 · 슬롯 쿼터 · 1~5순위 키워드 풀 통합 시뮬레이터]
------------------------------------------------------------------
1. 10개 외부 제휴 사이트(site_01~site_10)로부터 5분 주기 슬롯 동기화 모의
2. 유니크 상품별 중복 슬롯 합산 및 최대 100타 상한(Hard-Cap) 쿼터 검증
3. 1~5순위 키워드 풀 동적 회전 및 1P 미노출 소멸(is_exposed=0) 시 차순위 자동 투입 검증
4. 일자별(Day 1, Day 2, Day 3) 다일 누적 실행 및 마감(COMPLETED) 상태 전환 검증
"""

import sys
import time
import argparse
import requests
from pathlib import Path
from typing import Dict, Any, List

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

CENTRAL_API_BASE = "http://114.207.112.173:8000"


def simulate_multi_day(days: int = 3, cycles_per_day: int = 10, devices_per_cycle: int = 20, hit_rate: float = 0.75):
    print("=" * 85)
    print(f"🚀 [v2 일자별 가상 사이트 · 슬롯 쿼터 · 다중 키워드 통합 시뮬레이션 시작]")
    print(f"• 시뮬레이션 일수 : {days}일")
    print(f"• 일별 사이클 수  : {cycles_per_day}회차")
    print(f"• 회차당 단말기   : {devices_per_cycle}대 (회당 {devices_per_cycle}타 모의)")
    print(f"• 모의 성공률    : {hit_rate * 100:.0f}%")
    print(f"• 중앙 서버 API  : {CENTRAL_API_BASE}")
    print("=" * 85 + "\n")

    base_date = time.strftime("%Y-%m-%d")
    import datetime
    start_dt = datetime.datetime.strptime(base_date, "%Y-%m-%d")

    total_sim_allocated = 0
    total_sim_success = 0
    day_reports = []

    for d_idx in range(days):
        cur_dt = start_dt + datetime.timedelta(days=d_idx)
        date_str = cur_dt.strftime("%Y-%m-%d")
        day_tag = f"DAY {d_idx + 1} ({date_str})"

        print(f"\n{'#' * 85}")
        print(f"📅 [{day_tag}] 시뮬레이션 가동 중...")
        print(f"{'#' * 85}")

        # 1. 10개 외부 제휴 사이트 5분 동기화 모의 (일부 슬롯 추가/갱신)
        sync_payload = {
            "site_code": f"agency_partner_{((d_idx % 10) + 1):02d}",
            "target_date": date_str,
            "slots": [
                {
                    "slot_id": f"PARTNER-{((d_idx % 10) + 1):02d}-SLOT-{1000 + i}",
                    "nv_mid": mid,
                    "base_keyword": kw,
                    "product_name": f"{kw} 정품",
                    "store_name": f"제휴스토어_{i}",
                    "hits_per_slot": 20,
                    "sub_keywords": [f"{kw} 추천", f"{kw} 인기", f"{kw} 세일", f"{kw} 가성비"],
                    "is_active": 1
                }
                for i, (mid, kw) in enumerate([
                    ("57081138317", "마이크커버무지"),
                    ("89786061126", "도어체크"),
                    ("86627996631", "마라톤운동양말"),
                    ("82468173429", "늑간살")
                ], 1)
            ]
        }
        try:
            r_sync = requests.post(f"{CENTRAL_API_BASE}/api/v2/products/sync-external", json=sync_payload, timeout=10)
            if r_sync.status_code == 200:
                print(f"   ↳ 🔄 [5분 외부 사이트 동기화]: {r_sync.json().get('message')}")
        except Exception as e:
            print(f"   ↳ ⚠️ [외부 동기화 예외]: {e}")

        # 2. 일자별 시뮬레이션 API 호출
        sim_payload = {
            "target_date": date_str,
            "cycles": cycles_per_day,
            "devices_count": devices_per_cycle,
            "hit_success_rate": hit_rate,
            "drop_rank_failure_prob": 0.06
        }
        try:
            r_sim = requests.post(f"{CENTRAL_API_BASE}/api/v2/simulation/run-day", json=sim_payload, timeout=60)
            if r_sim.status_code == 200:
                sim_res = r_sim.json()
                q_stat = sim_res.get("quota_status") or {}
                allocated = sim_res.get("total_allocated", 0)
                success = sim_res.get("total_success", 0)
                dropped = sim_res.get("total_dropped_keywords", 0)
                rate = sim_res.get("success_rate", 0.0)

                total_sim_allocated += allocated
                total_sim_success += success

                print(f"   ↳ ⚡ [시뮬레이션 완료] {sim_res.get('simulated_cycles')}회차 구동 | {allocated}타 할당 -> {success}타 성공 ({rate}%) | 소멸 키워드: {dropped}개")
                print(f"   ↳ 📊 [당일 쿼터 현황] 목표 {q_stat.get('total_target_hits')}타 중 {q_stat.get('total_current_hits')}타 달성 ({q_stat.get('overall_completion_rate')}%)")
                print(f"   ↳ 🎯 [상품 마감 상태] 마감 완료(COMPLETED): {q_stat.get('completed_products')}개 | 진행 중(IN_PROGRESS): {q_stat.get('in_progress_products')}개")
                day_reports.append({
                    "day": d_idx + 1,
                    "date": date_str,
                    "allocated": allocated,
                    "success": success,
                    "dropped": dropped,
                    "rate": rate,
                    "quota": q_stat
                })
            else:
                print(f"   ↳ ❌ 시뮬레이션 실패: HTTP {r_sim.status_code} - {r_sim.text}")
        except Exception as e:
            print(f"   ↳ ⚠️ 시뮬레이션 통신 예외: {e}")

    # 최종 다일 종합 평가 리포트 출력
    print("\n" + "=" * 85)
    print("🏆 [v2 다일 시뮬레이션 최종 종합 평가 리포트]")
    print("=" * 85)
    print(f"• 총 시뮬레이션 일수 : {days}일")
    print(f"• 총 모의 할당 타수 : {total_sim_allocated}타")
    print(f"• 총 모의 유효타    : {total_sim_success}타 ({total_sim_success/total_sim_allocated*100:.1f}%)" if total_sim_allocated else "")
    print("-" * 85)
    print(f"{'일차':<6} | {'일자':<12} | {'할당 타수':<10} | {'유효타':<10} | {'성공률':<8} | {'소멸 키워드':<12} | {'당일 쿼터 달성률'}")
    print("-" * 85)
    for rep in day_reports:
        q = rep["quota"]
        q_rate = f"{q.get('total_current_hits')}/{q.get('total_target_hits')} ({q.get('overall_completion_rate')}%)"
        print(f"Day {rep['day']:<2} | {rep['date']:<12} | {rep['allocated']:<10} | {rep['success']:<10} | {rep['rate']:>5.1f}%  | {rep['dropped']:>2}개 소멸     | {q_rate}")
    print("=" * 85)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="v2 일자별 가상 사이트 · 슬롯 쿼터 · 키워드 시뮬레이터")
    parser.add_argument("--days", type=int, default=3, help="시뮬레이션 일수 (기본: 3일)")
    parser.add_argument("--cycles", type=int, default=5, help="일별 사이클 수 (기본: 5회)")
    parser.add_argument("--devices", type=int, default=20, help="회차당 단말기 수 (기본: 20대)")
    parser.add_argument("--hit-rate", type=float, default=0.75, help="모의 성공률 (기본: 0.75)")
    args = parser.parse_args()

    simulate_multi_day(days=args.days, cycles_per_day=args.cycles, devices_per_cycle=args.devices, hit_rate=args.hit_rate)
