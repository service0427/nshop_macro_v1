#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
⚡ PRICE COMPARISON 2-GATE WARP & TARGET NAVIGATOR (PriceWarpNavigator)
========================================================================================
1. [Gate 1 판별] '네이버 가격비교' 섹션 DOM 존재 검증 -> 없으면 0회 스크롤 즉시 종료
2. [Gate 2 판별] 가격비교 내 타겟 상품(MID) DOM 존재 검증 -> 없으면 0회 스크롤 즉시 종료
3. [초고속 워프] '다른 사이트 더보기' 페이지 내 검색 0.7초 원자적 앵커링 점프
4. [슬라이더 & 조준] Slide 1/2 감지 시 자동 가로 스와이프 후 상품 타이틀 정밀 좌표 산출
========================================================================================
"""

import time
import re
import random
import logging
import xml.etree.ElementTree as ET
from typing import Optional, Tuple, Dict, Any, List

from src.modules.macro.ui_inspector import UIInspector
from src.modules.macro.shopping_xml_parser import ShoppingXMLParser

logger = logging.getLogger("NaverMacroCore.PriceWarpNavigator")


class PriceWarpNavigator:
    """네이버 가격비교 섹션 2단계 게이트 판별 및 초고속 워프/슬라이더 탐색 전담 모듈"""

    def __init__(self, device_id: str, inspector: UIInspector):
        self.device_id = device_id
        self.inspector = inspector

    def check_two_gates(self, root: ET.Element, target_mid_str: str) -> Tuple[bool, bool]:
        """
        [2단계 게이트 무결성 판별]
        - Gate 1: DOM 상 '네이버 가격비교' 섹션 존재 여부
        - Gate 2: DOM 상 타겟 상품(MID) 존재 여부
        """
        all_texts = [(e.attrib.get("text", "") or e.attrib.get("content-desc", "")) for e in root.iter("node")]
        combined_dom_text = " ".join(all_texts)
        has_price_comp = any(kw in combined_dom_text for kw in ["네이버 가격비교", "가격비교", "네이버 쇼핑", "네이버쇼핑"])

        has_target = any(
            target_mid_str in e.attrib.get("resource-id", "")
            or target_mid_str in e.attrib.get("text", "")
            or target_mid_str in e.attrib.get("content-desc", "")
            for e in root.iter("node")
        )
        return (has_price_comp, has_target)

    def jump_to_section_via_find_in_page(self, query: str = "다른 사이트 더보기") -> bool:
        """
        [페이지 내 검색을 통한 가격비교 초고속 0.7초 원자적 점프]
        - 우측 하단 더보기(1008, 2356) ➔ [페이지 내 검색](135, 1950) ➔ '다른 사이트 더보기' 타이핑 ➔ 엔터 ➔ 툴바 닫기
        - 불필요한 UI 덤프를 배제하고 단일 원자적 셸 스크립트로 0.7초 만에 실행
        """
        logger.info(f"[{self.device_id}] ⚡ [초고속 워프] 우측 하단 메뉴 ➔ '페이지 내 검색'('{query}') 원자적 실행...")
        try:
            self.inspector.ensure_naver_foreground()
            escaped_q = query.replace('"', '\\"')
            atomic_cmd = (
                f"input tap 1008 2356; "
                f"sleep 0.25; "
                f"input tap 135 1950; "
                f"sleep 0.25; "
                f"am broadcast -a ADB_INPUT_TEXT --es msg \"{escaped_q}\" 2>/dev/null; "
                f"input keyevent 66; "
                f"sleep 0.2; "
                f"input keyevent 4"
            )
            self.inspector.run_adb(atomic_cmd)
            time.sleep(0.3)
            logger.info(f"[{self.device_id}] [✓] 페이지 내 검색('{query}') 초고속 워프 완료 (0.7s)!")
            return True
        except Exception as e:
            logger.warning(f"[{self.device_id}] 페이지 내 검색 점프 중 예외: {e}")
            return False

    def navigate_and_focus_target_card(self, target_mid: str, keyword: Optional[str] = None) -> Optional[Tuple[int, int]]:
        """
        [STEP 3: 2단계 게이트 검증 ➔ '다른 사이트 더보기' 워프 ➔ 슬라이더 안착 ➔ 타이틀 좌표 계산]
        """
        target_mid_str = str(target_mid).strip()
        logger.info(f"[{self.device_id}] ========================================================")
        logger.info(f"[{self.device_id}] 🎯 [STEP 3] 타겟 상품 mid({target_mid_str}) 2단계 게이트 판별 및 포커싱")
        logger.info(f"[{self.device_id}] ========================================================")

        self.inspector.ensure_naver_foreground()
        root = self.inspector.get_ui_tree("safe_focus_init")
        if root is None:
            logger.warning(f"[{self.device_id}] [!] 화면 덤프 실패 ➔ 조기 종료")
            return None

        # 🚪 1차 & 2차 게이트 검증
        has_price_comp, has_target_in_dom = self.check_two_gates(root, target_mid_str)

        if not has_price_comp:
            logger.warning(f"[{self.device_id}] 🚫 [Gate 1 실패] '네이버 가격비교' 섹션 없음 ➔ 스크롤 0회, 즉시 종료 (Fail-Fast)")
            try: self.inspector.save_unexposed_dump(target_mid=target_mid_str, keyword=keyword)
            except Exception: pass
            return None
        logger.info(f"[{self.device_id}] [Gate 1 통과 ✓] '네이버 가격비교' 섹션 DOM 존재 확인")

        if not has_target_in_dom:
            logger.warning(f"[{self.device_id}] 🚫 [Gate 2 실패] 가격비교 내 타겟 상품({target_mid_str}) 없음 ➔ 스크롤 0회, 즉시 종료 (Fail-Fast)")
            try: self.inspector.save_unexposed_dump(target_mid=target_mid_str, keyword=keyword)
            except Exception: pass
            return None
        logger.info(f"[{self.device_id}] [Gate 2 통과 ✓] 타겟 상품({target_mid_str}) DOM 존재 확인 ➔ '다른 사이트 더보기'로 즉시 이동")

        # ⚡ 3단계: '다른 사이트 더보기' 초고속 워프 (0.7s)
        self.jump_to_section_via_find_in_page("다른 사이트 더보기")
        time.sleep(0.6)

        # 🎯 4단계: 가로 슬라이더 및 안전 영역 안착
        SAFE_Y_MIN = 340
        SAFE_Y_MAX = 2260

        for pass_num in range(1, 4):
            root = self.inspector.get_ui_tree(f"focus_pass_{pass_num}")
            if root is None:
                time.sleep(0.5)
                continue

            matched_card_bounds = None
            for elem in root.iter("node"):
                rid = elem.attrib.get("resource-id", "").strip()
                b = elem.attrib.get("bounds", "").strip()
                t = elem.attrib.get("text", "").strip() or elem.attrib.get("content-desc", "").strip()

                if any(ad_kw in t or ad_kw in rid for ad_kw in ["파워링크", "광고", "coupang.com", "쿠팡", "ad_view", "sponsor"]):
                    continue

                card_mids = re.findall(r"(?:view_type_guide_|nstore_productId_|mid=|id=)?(\d{9,14})", f"{rid} {t}")
                if (target_mid_str in card_mids or target_mid_str in rid or target_mid_str in t) and b:
                    coords = b.replace("][", ",").replace("[", "").replace("]", "").split(",")
                    if len(coords) == 4:
                        x1, y1, x2, y2 = map(int, coords)
                        if (y2 - y1) > 30 and y1 < 2340 and y2 > 100:
                            matched_card_bounds = (x1, y1, x2, y2, t or rid)
                            break

            if matched_card_bounds:
                x1, y1, x2, y2, desc = matched_card_bounds
                h = y2 - y1
                logger.info(f"[{self.device_id}] [Pass #{pass_num}] 타겟 상품 카드 포착: [{x1}, {y1}][{x2}, {y2}] (높이: {h}px)")

                # 상단 고정바 침범 검사
                if y1 < SAFE_Y_MIN:
                    shift = min(650, (SAFE_Y_MIN - y1) + 350)
                    self.inspector.run_adb(f"input swipe 500 700 500 {700 + shift} 320")
                    time.sleep(0.5)
                    continue

                # 하단 고정바 침범 검사
                elif y2 > SAFE_Y_MAX:
                    shift = min(650, (y2 - SAFE_Y_MAX) + 350)
                    self.inspector.run_adb(f"input swipe 500 {1400 + shift} 500 1400 350")
                    time.sleep(0.5)
                    continue

                # 온전한 안전 가시 영역 안착
                elif h >= 150:
                    pad_x = max(30, int((x2 - x1) * 0.15))
                    click_x = random.randint(x1 + pad_x, x2 - pad_x)
                    title_y_min = y1 + int(h * 0.18)
                    title_y_max = y1 + int(h * 0.35)
                    click_y = random.randint(title_y_min, max(title_y_min + 10, title_y_max))
                    logger.info(f"[{self.device_id}] [🎉 100% 안전 안착] 상품 타이틀 안전 터치 좌표: ({click_x}, {click_y})")

                    try:
                        self.inspector.crop_and_save_target_screenshot(
                            target_bounds=(x1, y1, x2, y2),
                            target_mid=target_mid_str,
                            keyword=keyword,
                            click_coords=(click_x, click_y)
                        )
                    except Exception: pass

                    try:
                        self.inspector.draw_and_save_click_debug_image(
                            click_x, click_y,
                            target_mid=target_mid_str
                        )
                    except Exception: pass

                    try:
                        self.inspector.save_exposed_dump(
                            target_mid=target_mid_str,
                            keyword=keyword,
                            slide_page=1
                        )
                    except Exception: pass

                    return (click_x, click_y)

            # 🎯 가로 슬라이더 2페이지 감지 시 1회 가로 스와이프
            shop_block_y = None
            for elem in root.iter("node"):
                t_e = elem.attrib.get("text", "").strip() or elem.attrib.get("content-desc", "").strip()
                b_e = elem.attrib.get("bounds", "").strip()
                if any(kw in t_e for kw in ["가격비교", "네이버 쇼핑", "네이버쇼핑", "쇼핑", "스마트스토어"]) and b_e:
                    m_be = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b_e)
                    if m_be:
                        _, y1_b, _, y2_b = map(int, m_be.groups())
                        if y2_b > 200 and y1_b < 2100:
                            shop_block_y = min(1800, max(600, (y1_b + y2_b) // 2 + 350))
                            break

            has_hidden_target = any(
                (target_mid_str in e.attrib.get("resource-id", "") or target_mid_str in e.attrib.get("text", "") or target_mid_str in e.attrib.get("content-desc", "")) and e.attrib.get("bounds") in ["[0,0][0,0]", ""]
                for e in root.iter("node")
            )

            if has_hidden_target and shop_block_y:
                logger.info(f"[{self.device_id}] ⚡ [가로 슬라이더 감지] 타겟 상품이 가로 2페이지에 위치함 ➔ 가로 스와이프 수행 (Y: {shop_block_y})")
                self.inspector.run_adb(f"input swipe 950 {shop_block_y} 130 {shop_block_y} 350")
                time.sleep(0.8)
                continue

            # 미세 보정 스크롤 1회
            if pass_num == 1:
                self.inspector.run_adb("input swipe 500 1700 500 1100 350")
                time.sleep(0.6)

        logger.warning(f"[{self.device_id}] [!] 가격비교 섹션 내 타겟 MID({target_mid_str}) 최종 미노출 ➔ 즉시 종료 (Fail-Fast)")
        try: self.inspector.save_unexposed_dump(target_mid=target_mid_str, keyword=keyword)
        except Exception: pass
        return None
