#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/tools/extract_single_tail_products.py

새로운 사용자 기준 반영 추출 스크립트:
- 대상: 30위 ~ 40위 사이 순수 오가닉 상품
- 조건: 판매처로 묶여 있지 않은 순수 단일 상품 (is_catalog=False, mallCount <= 1, catalogMatchingId 없음, 몰 이름 명확)
- 우선순위: 40등에 가장 가까운 것 (순위 내림차순: 40위 우선 -> 39위 -> ... -> 30위)
"""

import os
import sys
import glob
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

RAW_DIR = PROJECT_ROOT / "logs" / "harvest" / "raw"
OUTPUT_FILE = PROJECT_ROOT / "logs" / "harvest" / "single_tail_targets_30_40.json"


def is_canonical_pure_organic(card: Dict[str, Any]) -> bool:
    """
    순수 오가닉 단일 상품의 양성(Positive) 식별자 기준 엄격 판정:
    - 네거티브(블랙리스트) 제외 방식이 아닌, 순수 오가닉 상품 고유의 필수 스키마 속성만을 100% 매칭
    1. 최상위 엔트리 타입: type == 'product' (supersaving, ad, powerlink 등 원천 배제)
    2. 컬렉션: collection == 'product'
    3. 순수 단일 상품: parentId == id (카탈로그 묶음 하위 입점처 및 가격비교 배제)
    4. 단일 판매처: mallCount <= 1, lowMallList/lowPriceByMallNo 부재
    5. 정규 몰 명칭: mallNo 및 mallName 필수 존재 (하이픈, 판매처 등 임의명칭 배제)
    6. 광고/프로모션 태그 부재: ad/isAd/adcrUrl/adProductInfoEnabled/SUPER_POINT 0건
    """
    if not isinstance(card, dict):
        return False
    if card.get("type") != "product":
        return False

    it = card.get("item", {})
    if not isinstance(it, dict) or not it:
        return False

    if it.get("collection") != "product":
        return False

    it_id = str(it.get("id") or it.get("nvMid") or "")
    if not it_id:
        return False

    parent_id = str(it.get("parentId") or "")
    if parent_id and parent_id != it_id:
        return False

    if it.get("lowMallList") or it.get("lowPriceByMallNo") or (it.get("mallCount") and it.get("mallCount") > 1):
        return False

    mall_name = str(it.get("mallName") or it.get("channelName") or "").strip()
    mall_no = str(it.get("mallNo") or "")
    if not mall_name or mall_name == "-" or mall_name.startswith("판매처") or not mall_no:
        return False

    if it.get("adProductInfoEnabled") or it.get("adcrUrl") or it.get("ad") or it.get("isAd"):
        return False

    if it.get("promotion") and "SUPER_POINT" in str(it.get("promotion")):
        return False

    return True


is_pure_single_product = is_canonical_pure_organic


def extract_single_tail_products(
    target_kws: Optional[List[str]] = None,
    min_rank: int = 30,
    max_rank: int = 40
) -> List[Dict[str, Any]]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_files = sorted(glob.glob(str(RAW_DIR / "*.json")))
    
    # 키워드별 후보군 맵
    candidates_by_kw: Dict[str, List[Dict[str, Any]]] = {}

    for fpath in raw_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                d = json.load(f)

            fname = Path(fpath).name
            kw = d.get("query") or (fname.split("_R")[0] if "_R" in fname else fname.replace(".json", ""))
            kw = kw.strip()

            if target_kws and kw not in target_kws:
                continue

            items = d.get("list", [])
            org_rank = 0

            for card in items:
                it = card.get("item", card)
                if card.get("type") == "product" and not it.get("adProductInfoEnabled") and not it.get("adcrUrl") and not it.get("ad") and not it.get("isAd"):
                    org_rank += 1
                    if min_rank <= org_rank <= max_rank:
                        if is_canonical_pure_organic(card):
                            it_id = str(it.get("id") or it.get("nvMid") or it.get("channelProductId") or "")
                            clean_title = (it.get("productTitle") or it.get("productName") or it.get("title") or "")
                            clean_title = clean_title.replace("<mark>", "").replace("</mark>", "").strip()
                            mall_name = (it.get("mallName") or it.get("channelName") or "").strip()
                            price = it.get("lowPrice") or it.get("price") or 0

                            prod_dict = {
                                "keyword": kw,
                                "rank": org_rank,
                                "nv_mid": it_id,
                                "product_title": clean_title,
                                "mall_name": mall_name,
                                "price": price,
                                "source_file": fname
                            }

                            if kw not in candidates_by_kw:
                                candidates_by_kw[kw] = []
                            candidates_by_kw[kw].append(prod_dict)

        except Exception as e:
            continue

    # 각 키워드별로 "40등에 가장 가까운 것" (순위 숫자가 가장 큰 것: max rank) 선별
    selected_targets = []
    for kw, prod_list in candidates_by_kw.items():
        # 중복 MID 제거 및 가장 최근 파일 또는 최고 순위(40에 가까운) 선택
        # 40에 가장 가까운 것 = rank 내림차순(40 -> 39 -> 38 ...)
        prod_list.sort(key=lambda x: x["rank"], reverse=True)
        best = prod_list[0]
        selected_targets.append(best)

    # 키워드 가나다순 정렬
    selected_targets.sort(key=lambda x: x["keyword"])

    # 파일 저장
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f_out:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "criteria": "30~40위 오가닉 상품 중 판매처 미묶음 순수 단일 상품 (40위 우선 선별)",
            "total_targets": len(selected_targets),
            "targets": selected_targets
        }, f_out, ensure_ascii=False, indent=2)

    return selected_targets


if __name__ == "__main__":
    from src.tools.harvest_fleet_35 import MAJOR_ECOMMERCE_KEYWORDS_50
    
    print("=" * 110)
    print("🔍 [신규 기준 검증: 30~40위 사이 판매처 묶이지 않은 순수 단일 상품 (40등에 가장 가까운 것)]")
    print("=" * 110)
    
    targets = extract_single_tail_products()
    print(f"📊 총 {len(targets)}개 키워드에서 40등 인근 순수 단일 상품 선별 완료!\n")
    
    print(f"{'순위':<6} | {'키워드':<20} | {'MID':<13} | {'스토어/몰명':<18} | {'가격':>10}원 | 상품명")
    print("-" * 110)
    for t in targets[:30]:
        title = t["product_title"]
        if len(title) > 30:
            title = title[:28] + ".."
        print(f"{t['rank']:2d}위   | {t['keyword']:<20} | {t['nv_mid']:<13} | {t['mall_name']:<18} | {t['price']:10,d}원 | {title}")
