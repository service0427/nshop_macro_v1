#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/tools/aggregate_candidates.py

logs/harvest/raw/ 디렉토리 내의 __NEXT_DATA__ raw json 파일들을 전수 스캔하여
광고(AD)를 배제한 순수 오가닉 35위 ~ 40위 비인기 꼬리 상품들을 선별 및 집계
"""

import os
import sys
import glob
import json
import time
from pathlib import Path
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

RAW_DIR = PROJECT_ROOT / "logs" / "harvest" / "raw"
OUTPUT_FILE = PROJECT_ROOT / "logs" / "harvest" / "candidates_35_40.json"


def aggregate_candidates() -> List[Dict[str, Any]]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_files = sorted(glob.glob(str(RAW_DIR / "*.json")))
    print(f"📂 [수집 데이터 스캔] {len(raw_files)}개 원본 JSON 파일 발견")

    seen_keys = set()
    candidates = []

    for fpath in raw_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                d = json.load(f)

            # 파일명 또는 데이터 내부에서 키워드 추출
            fname = Path(fpath).stem
            kw = d.get("query") or (fname.split("_R")[0] if "_R" in fname else fname)
            items = d.get("list", [])
            org_rank = 0

            for card in items:
                it = card.get("item", card)
                # CPC / 쇼핑검색광고 완전 배제
                if it.get("ad") or it.get("isAd") or it.get("cardType") == "AD_CARD":
                    continue

                org_rank += 1
                if 35 <= org_rank <= 40:
                    it_id = str(it.get("id") or it.get("nvMid") or it.get("channelProductId") or "")
                    cat_id = str(it.get("catalogMatchingId") or "")
                    uniq_key = (kw, it_id)

                    if uniq_key in seen_keys:
                        continue
                    seen_keys.add(uniq_key)

                    clean_title = (it.get("productTitle") or it.get("productName") or it.get("title") or "")
                    clean_title = clean_title.replace("<mark>", "").replace("</mark>", "").strip()
                    mall = it.get("mallName") or it.get("channelName") or "-"
                    price = it.get("lowPrice") or it.get("price") or 0
                    is_cat = bool((it.get("mallCount", 0) > 1) or cat_id)

                    candidates.append({
                        "keyword": kw,
                        "initial_rank": org_rank,
                        "nv_mid": it_id,
                        "catalog_id": cat_id,
                        "is_catalog": is_cat,
                        "product_title": clean_title,
                        "mall_name": mall,
                        "price": price,
                        "source_file": Path(fpath).name,
                        "harvested_at": time.strftime("%Y-%m-%d %H:%M:%S")
                    })
        except Exception as e:
            print(f"⚠️ [{fpath}] 파싱 예외: {e}")

    # 결과 저장
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f_out:
        json.dump({
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_raw_files": len(raw_files),
            "total_candidates": len(candidates),
            "candidates": candidates
        }, f_out, ensure_ascii=False, indent=2)

    print(f"✅ [집계 완료] 총 {len(candidates)}개 순수 오가닉 35~40위 비인기 꼬리 상품 저장 완료 -> {OUTPUT_FILE}")
    return candidates


if __name__ == "__main__":
    cands = aggregate_candidates()
    print("\n" + "=" * 90)
    print(f"{'순위':<6} | {'키워드':<15} | {'MID':<13} | {'스토어명':<15} | {'가격':>8}원 | 상품명")
    print("-" * 90)
    for c in cands:
        print(f"{c['initial_rank']:<2}위    | {c['keyword'][:14]:<15} | {c['nv_mid']:<13} | {c['mall_name'][:14]:<15} | {c['price']:>8}원 | {c['product_title'][:25]}")
    print("=" * 90)
