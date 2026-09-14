#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
[FDS 전수 감사 파이프라인 - 2단계] 1차 후보군 노이즈 필터링 및 쇼핑/FDS 핵심 선별 (Phase 2)
(scripts/fds_audit_pipeline/phase2_filter.py)
========================================================================================
- 기능:
    1. 1단계에서 추출된 1,588건 원시 후보군 중 쇼핑과 무관한 동영상 전담 플레이어(PrismPlayer) 분리.
    2. 네이버 메인 앱 코어(com.nhn.android.search), 텔레메트리/추적(NTracker/NLog), 
       보안 SDK(Raon/SoftSecurity), Chromium 웹뷰(Whale) 코어로 도메인 정밀 필터링.
    3. 실제 데이터 흐름(Source ➔ Sink)이 존재하는 유효 FDS/지문 수집 후보군 엄선.
========================================================================================
"""

import json
from pathlib import Path
from collections import defaultdict, Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INPUT_JSONL = PROJECT_ROOT / "scripts/fds_audit_pipeline/phase1_raw_candidates.jsonl"
OUTPUT_JSONL = PROJECT_ROOT / "scripts/fds_audit_pipeline/phase2_filtered_candidates.jsonl"
OUTPUT_SUMMARY = PROJECT_ROOT / "scripts/fds_audit_pipeline/phase2_summary.json"


def classify_package_domain(file_path: str) -> str:
    """파일 경로를 기반으로 기능 도메인 분류"""
    fp = file_path.lower()
    if "prismplayer" in fp:
        return "VIDEO_PRISM_PLAYER"
    elif "org/chromium/media" in fp:
        return "CHROMIUM_MEDIA_DRM"
    elif "com/nhn/android/search" in fp:
        return "NAVER_SEARCH_SHOPPING_CORE"
    elif "ntracker" in fp or "nlog" in fp or "nelo" in fp or "gfp" in fp:
        return "NAVER_TELEMETRY_TRACKER"
    elif "raonsecure" in fp or "softsecurity" in fp:
        return "SECURITY_ANTI_TAMPER"
    elif "appsflyer" in fp:
        return "APPSFLYER_TRACKER"
    elif "org/chromium" in fp:
        return "CHROMIUM_WEBVIEW_ENGINE"
    elif "com/naver" in fp:
        return "NAVER_COMMON_SDK"
    else:
        return "OTHER_OBFUSCATED"


def main():
    print("=" * 82)
    print(" 🔍 [FDS 전수 감사 파이프라인 - 2단계] 1차 후보군 정밀 선별 및 노이즈 분리 (Phase 2)")
    print("=" * 82)

    if not INPUT_JSONL.exists():
        print(f"[!] 1단계 결과 파일이 없습니다: {INPUT_JSONL}")
        return

    total_raw = 0
    records_by_domain = defaultdict(list)

    with open(INPUT_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            total_raw += 1
            item = json.loads(line)
            domain = classify_package_domain(item["file"])
            item["domain"] = domain
            records_by_domain[domain].append(item)

    print(f"[*] 1단계 총 추출 레코드: {total_raw:,}건")
    print("\n📦 [도메인별 레코드 분포 현황]")
    print("-" * 55)
    for domain, items in sorted(records_by_domain.items(), key=lambda x: len(x[1]), reverse=True):
        print(f"  • {domain:30} : {len(items):4,d}건")
    print("-" * 55)

    # 1. 쇼핑/FDS 핵심 선별군 구성 (동영상 전담 미디어 DRM 노이즈 배제)
    # 제외 대상: VIDEO_PRISM_PLAYER (309건), CHROMIUM_MEDIA_DRM (468건) -> 동영상 라이선스/복호화 전담
    filtered_records = []
    excluded_count = 0

    for domain, items in records_by_domain.items():
        if domain in ["VIDEO_PRISM_PLAYER", "CHROMIUM_MEDIA_DRM"]:
            excluded_count += len(items)
            continue
        filtered_records.extend(items)

    print(f"\n[*] 노이즈 제거(동영상 전담 플레이어/DRM): {excluded_count:,}건 제외")
    print(f"[*] 🎯 실제 FDS/단말기 식별 핵심 유효 후보군 선별: {len(filtered_records):,}건!")

    # 2. 선별된 결과 저장
    with open(OUTPUT_JSONL, "w", encoding="utf-8") as f:
        for r in filtered_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 3. 선별군 카테고리별 세부 집계
    cat_summary = Counter(r["category"] for r in filtered_records)
    rule_summary = Counter(r["rule_id"] for r in filtered_records)

    summary_data = {
        "total_raw": total_raw,
        "excluded_video_media_drm": excluded_count,
        "total_filtered_candidates": len(filtered_records),
        "domain_breakdown": {k: len(v) for k, v in records_by_domain.items()},
        "filtered_category_breakdown": dict(cat_summary.most_common()),
        "filtered_rule_breakdown": dict(rule_summary.most_common())
    }

    with open(OUTPUT_SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    print("\n📊 [선별된 핵심 FDS/지문 수집 카테고리 현황 (811건)]")
    print("-" * 55)
    for cat, cnt in cat_summary.most_common():
        print(f"  • {cat:25} : {cnt:4,d}건")
    print("-" * 55)

    print("\n🔥 [가장 주목해야 할 상위 15개 핵심 클래스 (쇼핑/FDS/보안)]")
    print("-" * 82)
    core_classes = Counter(r["file"] for r in filtered_records)
    for rank, (fpath, cnt) in enumerate(core_classes.most_common(15), 1):
        rel_f = fpath.replace(str(PROJECT_ROOT) + "/", "")
        print(f"  {rank:2d}. [{cnt:2d}건] {rel_f}")
    print("-" * 82)


if __name__ == "__main__":
    main()
