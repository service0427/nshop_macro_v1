# -*- coding: utf-8 -*-
"""
========================================================================================
[모듈명] 네이버 쇼핑/가격비교 UI XML 정밀 분석 및 분류 파서 (ShoppingXMLParser)
(src/modules/macro/shopping_xml_parser.py)
========================================================================================
- 기능:
    1. 가격비교 및 네이버 쇼핑 섹션 자동 검출
    2. 상품 카드 트리(Parent-Child) 단위 정밀 탐색으로 MID, 상품명, 가격, 스토어 100% 매칭
    3. 광고(AD) vs 오가닉(Organic) 100% 정밀 분류
    4. 가로 1페이지(기본 노출 화면) vs 가로 2페이지 이상(슬라이더 숨김 화면) 구분
    5. 세로 스크롤 필요 영역(Off-Screen Bottom) 식별
========================================================================================
"""

import os
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional, Tuple


class ShoppingXMLParser:
    """네이버 통합검색 화면 UI XML 내 쇼핑/가격비교 상품 분류기"""

    SAFE_Y_MIN = 340
    SAFE_Y_MAX = 2260

    @classmethod
    def parse_xml_string_or_file(cls, xml_data_or_path: str) -> Dict[str, Any]:
        """XML 문자열 또는 파일 경로를 입력받아 쇼핑 분석 메타데이터 반환"""
        if os.path.exists(xml_data_or_path):
            tree = ET.parse(xml_data_or_path)
            root = tree.getroot()
            source_name = os.path.basename(xml_data_or_path)
        else:
            root = ET.fromstring(xml_data_or_path)
            source_name = "RAW_XML_STRING"

        all_nodes = list(root.iter("node"))

        # 1. 쇼핑/가격비교 헤더 노드 인덱스 위치 탐색
        shop_header_idx = -1
        section_type = "UNKNOWN"
        section_title = ""

        for idx, node in enumerate(all_nodes):
            t = node.get("text", "").strip() or node.get("content-desc", "").strip()
            if any(h in t for h in ["네이버 가격비교", "가격비교", "네이버 쇼핑", "네이버쇼핑", "쇼핑베스트", "스마트스토어", "브랜드스토어"]):
                shop_header_idx = idx
                section_type = "PRICE_COMPARISON" if "가격비교" in t else "NAVER_SHOPPING"
                section_title = t
                break

        # 2. 상품 카드 컨테이너 트리 탐색 및 MID / 메타데이터 매칭
        items: List[Dict[str, Any]] = []
        seen_mids = set()

        for node in all_nodes:
            children = list(node.iter("node"))
            if len(children) < 2 or len(children) > 40:
                continue

            combined_text = " ".join([n.get("text", "") for n in children]).strip()
            combined_desc = " ".join([n.get("content-desc", "") for n in children]).strip()
            combined_rid = " ".join([n.get("resource-id", "") for n in children]).strip()
            full_sub = f"{combined_text} {combined_desc} {combined_rid}".strip()

            has_price = ("원" in full_sub or "최저" in full_sub)
            has_meta = any(m in full_sub for m in ["배송비", "스토어", "몰", "판매처", "구매", "리뷰", "개인", "공식", "도착", "출발"])

            # view_type_guide_MID, nstore_productId_MID, mid=MID, id=MID 또는 9~14자리 숫자 추출
            mids = re.findall(r"(?:view_type_guide_|nstore_productId_|mid=|id=)?(\d{9,14})", combined_rid)
            if not mids:
                mids = re.findall(r"(?:view_type_guide_|nstore_productId_|mid=|id=)?(\d{9,14})", full_sub)

            if has_price and has_meta and mids:
                main_mid = mids[0]
                if main_mid in seen_mids:
                    continue
                seen_mids.add(main_mid)

                b = node.get("bounds", "").strip()

                # 광고(AD) 판별: 텍스트/ID에 광고, 파워링크, sponsor, ad_view, 외부 쿠팡 배너 등 포함 여부
                is_ad = any(ad_kw in full_sub for ad_kw in ["광고", "파워링크", "ad_view", "sponsor", "coupang.com", "쿠팡"])

                # 가로 1페이지 (Slide 1 가시 영역) vs 가로 2페이지 이상 (오프스크린 숨김)
                is_slide_1 = False
                vis_type = "HIDDEN_SLIDE_2_PLUS"
                coords = None

                if b == "[0,0][0,0]":
                    is_slide_1 = False
                    vis_type = "HIDDEN_SLIDE_2_PLUS"
                elif b:
                    m_b = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
                    if m_b:
                        coords = list(map(int, m_b.groups()))
                        x1, y1, x2, y2 = coords
                        # 현재 뷰포트 내 가시 영역 안착 여부
                        if y1 < cls.SAFE_Y_MAX and y2 > cls.SAFE_Y_MIN and (y2 - y1) >= 40 and x1 >= 0 and x2 <= 1080:
                            is_slide_1 = True
                            vis_type = "VISIBLE_SLIDE_1"
                        elif y1 >= cls.SAFE_Y_MAX:
                            is_slide_1 = False
                            vis_type = "OFFSCREEN_BOTTOM"
                        else:
                            is_slide_1 = False
                            vis_type = "OFFSCREEN_OTHER"

                slide_page = 1 if is_slide_1 else (len(items) // 4 + 1)

                # 가격 텍스트 추출
                m_price = re.search(r"([\d,]+ ?원|최저 ?[\d,]+ ?원)", full_sub)
                price_str = m_price.group(1) if m_price else "N/A"

                title_cand = (node.get("content-desc") or node.get("text") or combined_desc or combined_text).strip()
                # 불필요한 마크업/헤더 정리
                clean_title = re.sub(r"\s+", " ", title_cand)[:75]

                items.append({
                    "item_index": len(items) + 1,
                    "mid": main_mid,
                    "all_mids": mids,
                    "title": clean_title,
                    "price": price_str,
                    "is_ad": is_ad,
                    "is_slide_1": is_slide_1,
                    "slide_page": slide_page,
                    "visibility_type": vis_type,
                    "bounds": b,
                    "coords": coords,
                    "raw_text": full_sub
                })

        return {
            "source": source_name,
            "has_shopping_section": (shop_header_idx != -1 or len(items) > 0),
            "section_type": section_type,
            "section_title": section_title,
            "total_items_count": len(items),
            "slide_1_items_count": sum(1 for x in items if x["is_slide_1"]),
            "slide_2_plus_items_count": sum(1 for x in items if not x["is_slide_1"]),
            "ad_items_count": sum(1 for x in items if x["is_ad"]),
            "organic_items_count": sum(1 for x in items if not x["is_ad"]),
            "slide_1_mids": [x["mid"] for x in items if x["is_slide_1"] and x["mid"]],
            "slide_2_plus_mids": [x["mid"] for x in items if not x["is_slide_1"] and x["mid"]],
            "items": items
        }
