# ==============================================================================
# src/monitor/dom_stabilization_auditor.py
#
# [DOM 레이아웃 안정화 & 물리 터치 안전 감사 분석기]
# - logs/dom_stabilization.jsonl 전수 파싱
# - 레이아웃 시프트(CLS) 발생 빈도, 재계측 정착 성공률, 오조준/가림 원천 차단율 정량 분석
# ==============================================================================

import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_FILE = PROJECT_ROOT / "logs" / "dom_stabilization.jsonl"


def load_stabilization_records(since_hours: float = None, limit: int = None) -> List[Dict[str, Any]]:
    if not LOG_FILE.exists():
        return []

    cutoff_ts = None
    if since_hours is not None:
        cutoff_ts = (datetime.now() - timedelta(hours=since_hours)).isoformat()

    records = []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if cutoff_ts and data.get("timestamp", "") < cutoff_ts:
                        continue
                    records.append(data)
                except Exception:
                    continue
    except Exception as e:
        print(f"⚠️ 로그 로드 실패: {e}")
        return []

    if limit and len(records) > limit:
        return records[-limit:]
    return records


def analyze_stabilization(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(records)
    if total == 0:
        return {"total": 0}

    by_action = {}
    by_status = {}
    shift_count = 0
    occluded_prevented = 0
    immediate_count = 0
    settled_after_shift = 0
    max_deltas = []
    durations = []

    for r in records:
        act = r.get("action_label", "UNKNOWN")
        by_action[act] = by_action.get(act, 0) + 1

        st = r.get("status", "UNKNOWN")
        by_status[st] = by_status.get(st, 0) + 1

        if r.get("layout_shifted"):
            shift_count += 1

        if st == "OCCLUDED_OR_MISALIGNED":
            occluded_prevented += 1
        elif st == "SETTLED_IMMEDIATE":
            immediate_count += 1
        elif st == "SETTLED_AFTER_SHIFT":
            settled_after_shift += 1

        d_max = r.get("max_delta_px", 0.0)
        if d_max > 0:
            max_deltas.append(d_max)

        dur = r.get("duration_sec", 0.0)
        if dur > 0:
            durations.append(dur)

    success_settled = sum(1 for r in records if r.get("success"))
    shift_rate = (shift_count / total * 100) if total > 0 else 0.0
    settle_rate = (success_settled / total * 100) if total > 0 else 0.0
    avg_max_delta = (sum(max_deltas) / len(max_deltas)) if max_deltas else 0.0
    overall_max_delta = max(max_deltas) if max_deltas else 0.0
    avg_duration = (sum(durations) / len(durations)) if durations else 0.0

    return {
        "total": total,
        "success_settled": success_settled,
        "settle_rate": settle_rate,
        "shift_count": shift_count,
        "shift_rate": shift_rate,
        "immediate_count": immediate_count,
        "settled_after_shift": settled_after_shift,
        "occluded_prevented": occluded_prevented,
        "by_action": by_action,
        "by_status": by_status,
        "avg_max_delta_px": avg_max_delta,
        "overall_max_delta_px": overall_max_delta,
        "avg_duration_sec": avg_duration,
        "records": records
    }


def print_report(summary: Dict[str, Any], hours: float = None):
    print("\n" + "=" * 76)
    title_suffix = f" (최근 {hours}시간)" if hours else " (전체 누적)"
    print(f"📊 [DOM 레이아웃 안정화 & 물리 터치 안전성 정밀 진단]{title_suffix}")
    print("=" * 76)

    total = summary.get("total", 0)
    if total == 0:
        print("ℹ️ 기록된 레이아웃 안정화 데이터가 아직 없습니다. (현재 구동 중인 사이클에서 축적 진행 중)")
        print("=" * 76 + "\n")
        return

    print(f"• 총 검증 횟수: {total:,}회")
    print(f"• 최종 안전 정착 성공률: {summary['settle_rate']:.1f}% ({summary['success_settled']:,}/{total:,})")
    print(f"• 동적 레이아웃 변위(Shift) 감지율: {summary['shift_rate']:.1f}% ({summary['shift_count']:,}/{total:,})")
    print(f"  └ 즉시 안정(변위 없음): {summary['immediate_count']:,}회 ({summary['immediate_count']/total*100:.1f}%)")
    print(f"  └ 변위 감지 후 재계측 정착: {summary['settled_after_shift']:,}회 ({summary['settled_after_shift']/total*100:.1f}%)")
    print(f"• 오조준/타겟 가림 감지 원천 차단(Misclick 방어): {summary['occluded_prevented']:,}회")
    print(f"• 평균 관측 최대 변위: {summary['avg_max_delta_px']:.1f}px (순간 최대 변위: {summary['overall_max_delta_px']:.1f}px)")
    print(f"• 평균 안정화 대기 시간: {summary['avg_duration_sec']:.2f}초")

    print("\n[인터랙션 액션별 분포]")
    for act, cnt in sorted(summary.get("by_action", {}).items(), key=lambda x: x[1], reverse=True):
        print(f"  - {act:<24}: {cnt:>5,}회 ({cnt/total*100:>5.1f}%)")

    print("\n[정착 상태별 판정 결과]")
    for st, cnt in sorted(summary.get("by_status", {}).items(), key=lambda x: x[1], reverse=True):
        print(f"  - {st:<26}: {cnt:>5,}회 ({cnt/total*100:>5.1f}%)")

    # 최근 5건 상세 내역
    recs = summary.get("records", [])
    if recs:
        print("\n[최근 계측/정착 이벤트 로그 (최대 5건)]")
        for r in recs[-5:]:
            ts = r.get("timestamp", "")[11:19]
            act = r.get("action_label", "")
            dev = r.get("device_id", "")
            kw = r.get("keyword", "")
            st = r.get("status", "")
            att = r.get("attempts", 0)
            shifted = "⚠️변위" if r.get("layout_shifted") else "정상"
            max_d = r.get("max_delta_px", 0.0)
            coord = r.get("final_coord") or {}
            cx, cy = coord.get("x", 0), coord.get("y", 0)
            print(f"  [{ts}] {dev} | {act:<18} | {kw:<12} | {st:<22} | {att}회시도 | {shifted}(Δ{max_d:.1f}px) | ({cx}, {cy})")

    print("=" * 76 + "\n")


def main():
    parser = argparse.ArgumentParser(description="DOM 레이아웃 안정화 전용 감사 분석기")
    parser.add_argument("--hours", type=float, default=None, help="분석 대상 시간 범위 (기본: 전체)")
    parser.add_argument("--limit", type=int, default=None, help="분석 대상 최대 레코드 수")
    args = parser.parse_args()

    recs = load_stabilization_records(since_hours=args.hours, limit=args.limit)
    summary = analyze_stabilization(recs)
    print_report(summary, hours=args.hours)


if __name__ == "__main__":
    main()
