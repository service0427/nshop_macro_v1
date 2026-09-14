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
import os
import re
import json
import time
import random
import logging
from datetime import datetime
import xml.etree.ElementTree as ET
from typing import Optional, Tuple, Dict, Any, List

from src.modules.macro.ui_inspector import UIInspector, parse_bounds
from src.modules.macro.shopping_xml_parser import ShoppingXMLParser

logger = logging.getLogger("NaverMacroCore.PriceWarpNavigator")

KNOWN_STORE_MIDS = {
    "91229936175", "91230953977", "91246920570", "91246933437", "91246946583",
    "91246954360", "91246992080", "91246999969", "91247010626", "91247019083"
}


class PriceWarpNavigator:
    """네이버 가격비교 섹션 2단계 게이트 판별 및 초고속 워프/슬라이더 탐색 전담 모듈"""

    def __init__(self, device_id: str, inspector: UIInspector):
        self.device_id = device_id
        self.inspector = inspector
        self.session_exposed_products: Dict[str, Dict[str, Any]] = {}
        self.session_passes: List[Dict[str, Any]] = []
        self.session_start_time: Optional[datetime] = None

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
        [페이지 내 검색을 통한 가격비교 초고속 핀포인트 워프 (1.5s)]
        - 우측 하단 메뉴 더보기(≡) 탭
        - 바텀시트에서 '페이지 내 검색' 노드를 동적으로 정확히 찾아 탭 (오클릭/언어변경 방지)
        - '다른 사이트 더보기' 입력 후 엔터 ➔ 가격비교 섹션 상단 앵커로 0.001s 워프
        - 상단 좌측 뒤로가기(60, 180) 탭 ➔ 검색바 및 하이라이트 잔상 100% 완전 삭제
        """
        logger.info(f"[{self.device_id}] ⚡ [초고속 핀포인트 워프] 메뉴 ➔ '페이지 내 검색'('{query}') ➔ 상단 뒤로가기 탭 실행...")
        try:
            self.inspector.ensure_naver_foreground()

            # 1. 화면 하단 툴바의 '메뉴 더보기' 버튼 탐색 및 탭
            root = self.inspector.get_ui_tree("toolbar_find")
            menu_tap_coords = (990, 2374)
            if root is not None:
                for elem in root.iter("node"):
                    desc = elem.attrib.get("content-desc", "").strip() or elem.attrib.get("text", "").strip()
                    rid = elem.attrib.get("resource-id", "").strip()
                    b = elem.attrib.get("bounds", "").strip()
                    if ("메뉴" in desc or "더보기" in desc or "btn_menu" in rid or "tail_menu" in rid) and b:
                        parsed = parse_bounds(b)
                        if parsed:
                            x1, y1, x2, y2 = parsed
                            if y1 > 2200 and x1 > 800:
                                menu_tap_coords = ((x1 + x2) // 2, (y1 + y2) // 2)
                                break

            self.inspector.run_adb(f"input tap {menu_tap_coords[0]} {menu_tap_coords[1]}")
            time.sleep(0.35)

            # 2. 열린 바텀시트에서 '페이지 내 검색' 텍스트/desc 노드 탐색 및 정확한 좌표 탭 (오클릭 방지)
            find_btn_coords = None
            for _ in range(3):
                time.sleep(0.3)
                sheet_root = self.inspector.get_ui_tree("sheet_find")
                if sheet_root is not None:
                    for elem in sheet_root.iter("node"):
                        t = elem.attrib.get("text", "").strip() or elem.attrib.get("content-desc", "").strip()
                        b = elem.attrib.get("bounds", "").strip()
                        if "페이지 내 검색" in t and b:
                            parsed_sheet = parse_bounds(b)
                            if parsed_sheet:
                                x1, y1, x2, y2 = parsed_sheet
                                find_btn_coords = ((x1 + x2) // 2, (y1 + y2) // 2)
                                break
                if find_btn_coords:
                    break

            if not find_btn_coords:
                logger.warning(f"[{self.device_id}] [!] '페이지 내 검색' 버튼 미감지 -> 오클릭 방지를 위해 바텀시트를 안전하게 닫습니다 (Back Key).")
                self.inspector.run_adb("input keyevent 4")  # 시트 안전 닫기
                return False

            logger.info(f"[{self.device_id}] [✓] '페이지 내 검색' 버튼 정밀 포착 ({find_btn_coords[0]}, {find_btn_coords[1]}) 탭")
            self.inspector.run_adb(f"input tap {find_btn_coords[0]} {find_btn_coords[1]}")
            time.sleep(0.4)

            # 3. 검색어 입력 & 엔터
            self.inspector.ensure_adb_keyboard_active()
            escaped_q = query.replace('"', '\\"')
            self.inspector.run_adb(f"am broadcast -a ADB_INPUT_TEXT --es msg \"{escaped_q}\" 2>/dev/null; input keyevent 66")
            time.sleep(0.4)

            # 4. 물리 뒤로가기(Back Key)로 검색바 닫기 (화면 오클릭 100% 차단)
            self.inspector.run_adb("input keyevent 4")
            time.sleep(0.4)
            logger.info(f"[{self.device_id}] [✓] '다른 사이트 더보기' 앵커링 점프 및 클린 검색창 정리 완료 (1.5s)!")
            return True
        except Exception as e:
            logger.warning(f"[{self.device_id}] 페이지 내 검색 점프 중 예외: {e}")
            return False

    def _extract_all_products_from_dom(self, root: ET.Element) -> List[Dict[str, Any]]:
        """
        검색 결과 DOM 트리 내 모든 상품 카드(타겟/비타겟, 자사/경쟁사 전수) 무필터 추출
        """
        items = []
        seen_mids = set()
        parent_map = {c: p for p in root.iter() for c in p}

        # 1차: view_type_guide_<mid> 네이버 쇼핑 표준 카드 노드
        for elem in root.iter("node"):
            rid = elem.attrib.get("resource-id", "").strip()
            m = re.search(r"view_type_guide_(\d{9,14})", rid)
            if m:
                mid = m.group(1)
                if mid in seen_mids:
                    continue
                seen_mids.add(mid)

                b = elem.attrib.get("bounds", "").strip()
                p = parent_map.get(elem)
                gp = parent_map.get(p) if p is not None else None
                container = gp if gp is not None else p

                title = ""
                mall_name = ""
                is_ad = False
                all_text_list = []

                if container is not None:
                    for c in container.iter("node"):
                        t = c.attrib.get("text", "").strip() or c.attrib.get("content-desc", "").strip()
                        if t:
                            all_text_list.append(t)
                            if any(ad_kw in t for ad_kw in ["광고", "파워링크", "ad_view", "sponsor", "coupang.com", "쿠팡"]):
                                is_ad = True

                    for t in all_text_list:
                        if len(t) > 3 and not any(k in t for k in ["할인", "원", "%", "배송", "출발", "포인트", "리뷰", "평점", "네이버페이"]):
                            if not title:
                                title = t
                            elif not mall_name and t != title and len(t) <= 15:
                                mall_name = t

                vis = "UNKNOWN"
                if b:
                    m_b = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
                    if m_b:
                        x1, y1, x2, y2 = map(int, m_b.groups())
                        h = y2 - y1
                        if 340 <= y1 and y2 <= 2260 and h >= 40:
                            vis = "VIEWPORT_FULL"
                        elif y1 < 2260 and y2 > 340 and h >= 40:
                            vis = "VIEWPORT_PARTIAL"
                        elif y1 >= 2200:
                            vis = "OFFSCREEN_BOTTOM"
                        elif y2 <= 340:
                            vis = "OFFSCREEN_TOP"
                        else:
                            vis = "COLLAPSED"

                items.append({
                    "mid": mid,
                    "title": title[:70],
                    "mall": mall_name,
                    "bounds": b,
                    "visibility": vis,
                    "is_ad": is_ad
                })

        # 2차: 기타 상품 마커 (nstore_productId 등)
        for elem in root.iter("node"):
            rid = elem.attrib.get("resource-id", "").strip()
            t = elem.attrib.get("text", "").strip() or elem.attrib.get("content-desc", "").strip()
            b = elem.attrib.get("bounds", "").strip()
            mids = re.findall(r"(?:nstore_productId_|mid=|id=)(\d{9,14})", f"{rid} {t}")
            for mid in mids:
                if mid not in seen_mids:
                    seen_mids.add(mid)
                    items.append({
                        "mid": mid,
                        "title": t[:70],
                        "mall": "",
                        "bounds": b,
                        "visibility": "SECONDARY_MATCH",
                        "is_ad": any(ad_kw in f"{rid} {t}" for ad_kw in ["광고", "파워링크", "sponsor", "쿠팡"])
                    })

        return items

    def record_raw_impressions(
        self,
        root: ET.Element,
        keyword: Optional[str],
        target_mid: Optional[str],
        pass_num: int
    ) -> List[Dict[str, Any]]:
        """
        [무필터 전수 노출 수집]
        - 타겟/비타겟, 자사/타사(경쟁사) 불문 화면 및 DOM에 잡힌 모든 상품 카드 전수 추출
        - 현재 검색 액션의 패스별 및 고유 상품 목록에 실시간 누적
        """
        products = self._extract_all_products_from_dom(root)
        if not products:
            return []

        pass_products = []
        for idx, prod in enumerate(products):
            mid = prod["mid"]
            is_target = (mid == str(target_mid).strip()) if target_mid else False
            is_ours = (mid in KNOWN_STORE_MIDS) or ("디테일애드" in (prod.get("mall") or "") or "디테일애드" in (prod.get("title") or ""))

            p_entry = {
                "rank": idx + 1,
                "mid": mid,
                "title": prod["title"],
                "mall": prod["mall"],
                "bounds": prod["bounds"],
                "visibility": prod["visibility"],
                "is_ad": prod["is_ad"],
                "is_target": is_target,
                "is_ours": is_ours
            }
            pass_products.append(p_entry)

            if mid not in self.session_exposed_products:
                self.session_exposed_products[mid] = {
                    **p_entry,
                    "first_seen_pass": pass_num
                }

        self.session_passes.append({
            "pass_num": pass_num,
            "pass_name": "search_initial_check" if pass_num == 0 else f"focus_pass_{pass_num}",
            "count": len(pass_products),
            "products": pass_products
        })

        return products

    def get_session_exposed_products(self) -> List[Dict[str, Any]]:
        """현재 검색 세션에서 화면/DOM에 감지된 모든 상품 목록 반환"""
        return list(self.session_exposed_products.values())

    def save_raw_impressions_action_dump(
        self,
        keyword: Optional[str],
        target_mid: Optional[str],
        alloc_id: Optional[str] = None,
        status: Optional[str] = None,
        is_searched: bool = True,
        is_exposed: bool = False,
        is_clicked: bool = False,
        error_reason: Optional[str] = None
    ) -> str:
        """
        [액션 단위 개별 노출 덤프 저장]
        - 저장 경로: logs/raw_impressions/YYYY-MM-DD/raw_impressions_{YYYYMMDD_HHMMSS}_{mid}_{safe_kw}_{device_id}.json
        - unexposed_dumps / exposed_dumps 와 100% 동일한 개별 액션 상세 저장 규격
        - 검색 시 화면에 잡힌 모든 상품(자사+타사 전수) 및 패스별 상세 상태를 개별 액션 파일로 영구 보관
        """
        from src.config import RAW_IMPRESSIONS_DIR, get_dated_dir, prune_dir_by_age, LOG_RETENTION_DAYS

        now = self.session_start_time or datetime.now()
        time_str = now.strftime("%Y%m%d_%H%M%S")
        date_str = now.strftime("%Y-%m-%d")
        dated_dir = get_dated_dir(RAW_IMPRESSIONS_DIR, date_str)

        safe_kw = re.sub(r'[\s/\\:*?"<>|]+', '_', (keyword or "UNKNOWN").strip()).strip('_')
        target_mid_str = str(target_mid or "0").strip()
        base_name = f"raw_impressions_{time_str}_{target_mid_str}_{safe_kw}_{self.device_id}.json"
        dump_path = os.path.join(dated_dir, base_name)

        distinct_prods = list(self.session_exposed_products.values())
        target_found = any(p.get("is_target") for p in distinct_prods)

        action_data = {
            "timestamp": now.isoformat(),
            "device_id": self.device_id,
            "alloc_id": alloc_id,
            "keyword": keyword,
            "target_mid": target_mid_str,
            "status": status or ("SUCCESS" if is_searched and not error_reason else "FAILED"),
            "is_searched": is_searched,
            "is_exposed": is_exposed,
            "is_clicked": is_clicked,
            "error_reason": error_reason,
            "total_products_exposed": len(distinct_prods),
            "target_found": target_found,
            "all_exposed_products": distinct_prods,
            "pass_breakdown": self.session_passes
        }

        try:
            with open(dump_path, "w", encoding="utf-8") as f:
                json.dump(action_data, f, ensure_ascii=False, indent=2)
            logger.info(f"[{self.device_id}] 📝 [개별 액션 노출 덤프 저장 완료] -> {dump_path} (총 {len(distinct_prods)}개 상품 노출)")
            prune_dir_by_age(RAW_IMPRESSIONS_DIR, retention_days=LOG_RETENTION_DAYS)
            return dump_path
        except Exception as e:
            logger.warning(f"[{self.device_id}] 개별 노출 덤프 파일 저장 실패: {e}")
            return ""

    def _find_matching_candidates(self, root: ET.Element, target_mid_str: str) -> List[Tuple[int, int, int, int, int, str]]:
        """DOM 트리 내 타겟 MID 매칭 카드 노드 후보군 추출 및 면적 오름차순 정렬"""
        matching_candidates = []
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
                    w = x2 - x1
                    h = y2 - y1
                    # 2열 그리드(w~500px) 및 1열 리스트(w~1000px) 실제 가시 카드만 선별 (최소 높이 40px 이상, h==0 은 뷰포트 미진입 노드이므로 배제)
                    if 40 <= h <= 850 and 100 <= w <= 1080 and y1 < 2400 and y2 > 100:
                        matching_candidates.append((w * h, x1, y1, x2, y2, t or rid))
        matching_candidates.sort(key=lambda item: item[0])
        return matching_candidates

    def _extract_title_click_coords(self, root, x1: int, y1: int, x2: int, y2: int) -> Tuple[int, int]:
        """카드 내 타이틀 텍스트 노드를 핀포인트 조준 (비링크 텍스트 오탭 방지)"""
        h = y2 - y1
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        if h > 180 and root is not None:
            title_candidates = []
            for node in root.iter("node"):
                nb = node.attrib.get("bounds", "")
                nt = node.attrib.get("text", "").strip() or node.attrib.get("content-desc", "").strip()
                if nb and nt:
                    n_coords = nb.replace("][", ",").replace("[", "").replace("]", "").split(",")
                    if len(n_coords) == 4:
                        nx1, ny1, nx2, ny2 = map(int, n_coords)
                        if x1 <= nx1 and nx2 <= x2 + 20 and y1 <= ny1 and ny2 <= y1 + int(h * 0.55):
                            if not any(k in nt for k in ["할인", "원", "%", "배송", "출발", "포인트", "리뷰", "평점", "쿠팡", "광고"]):
                                title_candidates.append((ny1, (nx1 + nx2) // 2, (ny1 + ny2) // 2, nt))
            if title_candidates:
                title_candidates.sort(key=lambda item: item[0])
                _, t_cx, t_cy, t_text = title_candidates[0]
                logger.info(f"[{self.device_id}] 🎯 [타이틀 텍스트 노드 적중] '{t_text[:30]}' ➔ ({t_cx}, {t_cy})")
                return (t_cx, t_cy)
            else:
                return (cx, y1 + max(40, int(h * 0.18)))
        return (cx, cy)

    def _save_target_evidence(self, x1: int, y1: int, x2: int, y2: int, target_mid_str: str, keyword: Optional[str], click_x: int, click_y: int):
        """타겟 상품 노출 증적 크롭, 디버그 이미지, 노출 XML 덤프 저장"""
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

    def navigate_and_focus_target_card(self, target_mid: str, keyword: Optional[str] = None, max_scroll_passes: int = 16) -> Optional[Tuple[int, int]]:
        """
        [STEP 3: 초기 화면 사전 검증 ➔ 자연스러운 순차 스크롤 ➔ 슬라이더 안착 ➔ 타이틀 좌표 계산]
        """
        target_mid_str = str(target_mid).strip()
        self.session_exposed_products.clear()
        self.session_passes.clear()
        self.session_start_time = datetime.now()
        logger.info(f"[{self.device_id}] ========================================================")
        logger.info(f"[{self.device_id}] 🎯 [STEP 3] 타겟 상품 mid({target_mid_str}) 탐색 및 포커싱")
        logger.info(f"[{self.device_id}] ========================================================")

        self.inspector.ensure_naver_foreground()

        # [🛡️ 0단계: 네이버 검색 결과 페이지(m.search.naver.com) 진입 상태 엄격 검증]
        if not self.inspector.is_on_search_page():
            logger.warning(f"[{self.device_id}] [⚠️ 비정상 페이지 감지] 현재 페이지가 m.search.naver.com 이 아님 -> 탐색 즉시 중단 (Fail-Fast)")
            try: self.inspector.save_unexposed_dump(target_mid=target_mid_str, keyword=keyword)
            except Exception: pass
            return None

        # [🔍 1단계: 검색 직후 초기 화면(스크롤 0회)에서 타겟 상품 및 쇼핑 섹션 사전 검증]
        SAFE_Y_MIN = 340
        SAFE_Y_MAX = 2260
        init_root = self.inspector.get_ui_tree("search_initial_check")
        if init_root is not None:
            # 초기 화면에 노출된 모든 상품(자사/타사 전수) 무필터 로컬 스트림 기록
            self.record_raw_impressions(init_root, keyword=keyword, target_mid=target_mid_str, pass_num=0)

            # 1-1. 최상단 화면에 이미 타겟 MID 카드가 존재하는지 즉시 검사!
            init_matches = self._find_matching_candidates(init_root, target_mid_str)
            if init_matches:
                _, x1, y1, x2, y2, desc = init_matches[0]
                h = y2 - y1
                w = x2 - x1
                logger.info(f"[{self.device_id}] 🎯 [초기 화면 즉시 포착] 스크롤 없이 검색 결과 상단에서 타겟 카드 바로 발견! [{x1}, {y1}][{x2}, {y2}] ({w}x{h}px)")
                if SAFE_Y_MIN <= y1 and y2 <= SAFE_Y_MAX and h >= 40:
                    click_x, click_y = self._extract_title_click_coords(init_root, x1, y1, x2, y2)
                    click_x += random.randint(-10, 10)
                    click_y += random.randint(-5, 5)
                    dwell_gaze = round(random.uniform(0.6, 1.1), 2)
                    logger.info(f"[{self.device_id}] 🎯 [초기 화면 발견] 시선 확인 체류({dwell_gaze}s) 후 정밀 탭: ({click_x}, {click_y})")
                    time.sleep(dwell_gaze)
                    self._save_target_evidence(x1, y1, x2, y2, target_mid_str, keyword, click_x, click_y)
                    return (click_x, click_y)

        # [📜 2단계: '페이지 내 검색' 인위적 워프 전면 폐기 ➔ 인간형 자연스러운 순차 스크롤(Natural Progressive Scroll)]
        logger.info(f"[{self.device_id}] 📜 [인간형 순차 탐색] '페이지 내 검색' 워프 배제 ➔ 자연스러운 가변 스크롤 탐색 시작 (최대 {max_scroll_passes}패스)...")
        time.sleep(random.uniform(0.3, 0.6))  # 자연스러운 탐색 전 시선 대기

        # [🎯 3단계: 자연스러운 인간 스크롤(Natural Scroll)을 통한 타겟 상품 탐색 및 포커싱]
        slider_tap_count = 0
        for pass_num in range(1, max_scroll_passes + 1):
            root = self.inspector.get_ui_tree(f"focus_pass_{pass_num}")
            if root is None:
                time.sleep(0.4)
                continue

            # 해당 스크롤 패스에 노출된 모든 상품(자사/타사 전수) 무필터 로컬 스트림 기록
            self.record_raw_impressions(root, keyword=keyword, target_mid=target_mid_str, pass_num=pass_num)

            matching_candidates = self._find_matching_candidates(root, target_mid_str)
            if matching_candidates:
                _, x1, y1, x2, y2, desc = matching_candidates[0]
                h = y2 - y1
                w = x2 - x1
                logger.info(f"[{self.device_id}] [Pass #{pass_num}] 타겟 핀포인트 단일 카드 포착: [{x1}, {y1}][{x2}, {y2}] ({w}x{h}px)")

                # 상단 고정바 침범 검사 및 미세 조정
                if y1 < SAFE_Y_MIN and h >= 40:
                    shift = min(650, (SAFE_Y_MIN - y1) + 350)
                    self.natural_scroll_adjust(shift, direction_down=False)
                    continue

                # 하단 고정바 침범 검사 및 화면 중앙 당김 조정
                elif y2 > SAFE_Y_MAX:
                    shift = min(650, (y2 - SAFE_Y_MAX) + 300)
                    logger.info(f"[{self.device_id}] 🎯 [타겟 하단 감지] 화면 하단({y1}~{y2}, h={h}) 타겟 감지 -> 화면 중앙으로 스크롤 당김({shift}px)")
                    self.natural_scroll_adjust(shift, direction_down=True)
                    continue

                # 온전한 안전 가시 영역 안착
                else:
                    click_x, click_y = self._extract_title_click_coords(root, x1, y1, x2, y2)
                    click_x += random.randint(-10, 10)
                    click_y += random.randint(-5, 5)
                    # 🛡️ 타겟 발견 후 사람이 상품명과 가격을 확인하고 누르는 시선 체류(0.6~1.1s)
                    dwell_gaze = round(random.uniform(0.6, 1.1), 2)
                    logger.info(f"[{self.device_id}] [🎉 100% 핀포인트 조준] 타겟 상품 포착! 시선 확인 체류({dwell_gaze}s) 후 정밀 탭: ({click_x}, {click_y}) [영역: {x1}~{x2}, {y1}~{y2}]")
                    time.sleep(dwell_gaze)
                    self._save_target_evidence(x1, y1, x2, y2, target_mid_str, keyword, click_x, click_y)
                    return (click_x, click_y)

            # 🎯 가로 슬라이더(현재1전체5 / 다음 페이지 / 히든 카드) 정밀 감지 (하단 브라우저 네비게이션 바 '다음 페이지 버튼' 오매칭 원천 차단)
            has_slider_indicator = any(
                ("현재1전체" in e.attrib.get("text", "") or "현재 1/" in e.attrib.get("text", "") or "shp_lis_root" in e.attrib.get("resource-id", ""))
                for e in root.iter("node")
            )

            shop_block_y = None
            next_btn_coords = None

            for elem in root.iter("node"):
                t_e = elem.attrib.get("text", "").strip() or elem.attrib.get("content-desc", "").strip()
                rid_e = elem.attrib.get("resource-id", "").strip()
                b_e = elem.attrib.get("bounds", "").strip()
                is_enabled = elem.attrib.get("enabled", "true").lower() != "false"

                # 브라우저 하단 툴바(content-desc="다음 페이지 버튼", Y > 2200) 완전 배제
                if "다음 페이지" in t_e and "다음 페이지 버튼" not in t_e and is_enabled and b_e:
                    parsed_next = parse_bounds(b_e)
                    if parsed_next:
                        nx1, ny1, nx2, ny2 = parsed_next
                        if SAFE_Y_MIN < ny1 and ny2 < SAFE_Y_MAX and (ny2 - ny1) > 20:
                            next_btn_coords = ((nx1 + nx2) // 2, (ny1 + ny2) // 2)

                if ("shp_lis_root" in rid_e or any(kw in t_e for kw in ["가격비교", "네이버 쇼핑", "네이버쇼핑", "쇼핑", "스마트스토어"])) and b_e:
                    parsed_be = parse_bounds(b_e)
                    if parsed_be:
                        _, y1_b, _, y2_b = parsed_be
                        if y2_b > 300 and y1_b < 2200:
                            shop_block_y = min(1800, max(500, (y1_b + y2_b) // 2))

            # 가로 슬라이더 탭은 최대 2회까지만 허용하고, 이후에는 무조건 수직 스크롤로 하향 탐색
            if has_slider_indicator and next_btn_coords and slider_tap_count < 2:
                slider_tap_count += 1
                logger.info(f"[{self.device_id}] ⚡ [가로 슬라이더 감지 #{slider_tap_count}] 슬라이더 '다음 페이지' 버튼 직접 탭: {next_btn_coords}")
                self.inspector.run_adb(f"input tap {next_btn_coords[0]} {next_btn_coords[1]}")
                time.sleep(random.uniform(0.7, 1.1))
                continue

            # 📜 자연스러운 인간 플릭 스크롤 (화면 중앙 안전 영역 스크롤)
            self.natural_scroll_down()

        logger.warning(f"[{self.device_id}] [!] 가격비교 섹션 내 타겟 MID({target_mid_str}) {max_scroll_passes}패스 자연 탐색 후 미노출 ➔ 즉시 조기 종료 (Fail-Fast)")
        try: self.inspector.save_unexposed_dump(target_mid=target_mid_str, keyword=keyword)
        except Exception: pass
        return None

    def natural_scroll_down(self) -> None:
        """
        [인간적인 가변 플릭 스크롤]
        - 화면 중앙 안전 여백 내 가변 X, Y 좌표 및 플릭 속도(280~360ms)
        - 우측 카드 상호작용 요소(버튼, 링크) 오터치 원천 방지
        - DOM touchstart, touchmove, scroll 이벤트 및 뷰포트 노출 누적
        """
        start_x = random.randint(480, 600)
        start_y = random.randint(1550, 1750)
        end_x = start_x + random.randint(-15, 15)
        scroll_dist = random.randint(500, 750)
        end_y = start_y - scroll_dist
        duration = random.randint(280, 360)

        logger.info(f"[{self.device_id}] 📜 [자연스러운 스크롤] ({start_x}, {start_y}) -> ({end_x}, {end_y}) | {duration}ms (이동: {scroll_dist}px)")
        self.inspector.run_adb(f"input swipe {start_x} {start_y} {end_x} {end_y} {duration}")
        time.sleep(random.uniform(0.6, 1.0))

    def natural_scroll_adjust(self, shift: int, direction_down: bool = True) -> None:
        """[타겟 카드를 시야 중심으로 부드럽게 가져오는 미세 조정 스크롤 (화면 중앙)]"""
        start_x = random.randint(480, 600)
        end_x = start_x + random.randint(-10, 10)
        duration = random.randint(240, 320)
        if direction_down:
            start_y = 1500
            end_y = max(800, start_y - shift)
        else:
            start_y = 700
            end_y = min(1600, start_y + shift)
        self.inspector.run_adb(f"input swipe {start_x} {start_y} {end_x} {end_y} {duration}")
        time.sleep(random.uniform(0.5, 0.8))
