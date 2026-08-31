# -*- coding: utf-8 -*-
"""
========================================================================================
[모듈명] 네이버 쇼핑/가격비교 UI XML 정밀 분석 및 분류 파서 (ShoppingXMLParser)
(src/modules/macro/shopping_xml_parser.py)
========================================================================================
- 기능:
    1. 가격비교 및 네이버 쇼핑 섹션 자동 검출
    2. 상품 카드 리스트 순차 파싱 (상품명, 가격, 스토어, mid)
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

        # 2. 상품 카드 순차 추출 및 분류
        items: List[Dict[str, Any]] = []
        seen_keys = set()
        candidate_nodes = all_nodes[shop_header_idx:] if shop_header_idx != -1 else all_nodes

        for node in candidate_nodes:
            t = node.get("text", "").strip() or node.get("content-desc", "").strip()
            r = node.get("resource-id", "").strip()
            b = node.get("bounds", "").strip()

            if not t or len(t) < 15:
                continue

            # UI 네비게이션 제어 텍스트 및 안내 문구 배제
            if any(w in t for w in ["네이버는 상품 판매의 당사자가", "다른 사이트 더보기", "배송지 설정", "필터", "정렬", "검색결과 더보기", "로그인하고"]):
                continue

            has_price = ("원" in t or "최저" in t or "할인" in t)
            has_meta = any(m in t for m in ["배송비", "스토어", "몰", "판매처", "구매", "리뷰", "평점", "출발", "무료", "개인", "공식"])
            mids = re.findall(r"(?:view_type_guide_|mid=|id=)?(\d{9,14})", f"{r} {t}")

            if (has_price and has_meta) or (mids and has_price):
                short_key = t[:35]
                if short_key in seen_keys:
                    continue
                seen_keys.add(short_key)

                # 광고(AD) 판별: 텍스트/ID에 광고, 파워링크, sponsor, ad_view, 외부 쿠팡 배너 등 포함 여부
                is_ad = any(ad_kw in t or ad_kw in r for ad_kw in ["광고", "파워링크", "ad_view", "sponsor", "coupang.com", "쿠팡"])

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
                m_price = re.search(r"([\d,]+ ?원|최저 ?[\d,]+ ?원)", t)
                price_str = m_price.group(1) if m_price else "N/A"

                items.append({
                    "item_index": len(items) + 1,
                    "mid": mids[0] if mids else None,
                    "all_mids": mids,
                    "title": t[:70],
                    "price": price_str,
                    "is_ad": is_ad,
                    "is_slide_1": is_slide_1,
                    "slide_page": slide_page,
                    "visibility_type": vis_type,
                    "bounds": b,
                    "coords": coords,
                    "raw_text": t
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
