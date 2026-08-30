#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
🧭 NAVER SEARCH & SHOPPING TARGET NAVIGATOR (SearchNavigator)
========================================================================================
- 검색창 및 검색 결과 페이지 완전 로딩 판별 (최대 30초 타임아웃)
- 쇼핑 섹션 감지, mid 식별 및 무결성 판정 (광고/쿠팡 배제)
- 타겟 상품 카드 안전 포커싱 & 상품 타이틀(Title) 정밀 조준 탭
- 스마트스토어 상세페이지 30초 다중 지표 검증 및 봇 탐지 방어
========================================================================================
"""

import os
import re
import time
import random
import logging
import subprocess
import xml.etree.ElementTree as ET
from typing import Dict, Any, Optional, Tuple, List

from src.config import HOME_ACTIVITY
from src.modules.macro.ui_inspector import UIInspector

logger = logging.getLogger("NaverMacroCore.SearchNavigator")


class SearchNavigator:
    def __init__(self, device_id: str, inspector: UIInspector):
        self.device_id = device_id
        self.inspector = inspector

    def wait_for_home_fully_loaded(self, timeout_sec: float = 8.0) -> bool:
        """[완전한 메인 홈 로딩 다중 지표 검증 및 팝업/온보딩 자동 바이패스]"""
        logger.info(f"[{self.device_id}] 홈 화면 동적 콘텐츠(피드/날씨/배너) 완전 로딩 대기 중...")
        start_t = time.time()
        feed_indicators = [
            "weatherText", "temperature", "priceTextView", "nameTextView",
            "content1", "content2", "channelTitle", "광고 이미지", "광고"
        ]

        for poll_i in range(1, int(timeout_sec * 4) + 1):
            time.sleep(0.35)
            elapsed = time.time() - start_t

            xml_str = self.inspector.run_adb("uiautomator dump /sdcard/home_chk.xml >/dev/null 2>&1 && cat /sdcard/home_chk.xml || true")

            # 1. '나중에 할게요' 로그인 건너뛰기 감지 시 즉시 탭
            if "laterLoginBtn" in xml_str or "나중에 할게요" in xml_str:
                logger.info(f"[{self.device_id}] ⚡ [온보딩 감지] '나중에 할게요' 로그인 건너뛰기 자동 탭")
                m = re.search(r'resource-id="[^"]*laterLoginBtn"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml_str)
                if m:
                    x1, y1, x2, y2 = map(int, m.groups())
                    self.inspector.run_adb(f"input tap {(x1+x2)//2} {(y1+y2)//2}")
                else:
                    self.inspector.run_adb("input tap 540 2379")
                time.sleep(0.6)
                continue

            # 2. '네이버 시작하기' 시작 버튼 감지 시 즉시 탭
            if "locationStartBtn" in xml_str or "startNaverBtnLayout" in xml_str or "네이버 시작하기" in xml_str:
                logger.info(f"[{self.device_id}] ⚡ [온보딩 감지] '네이버 시작하기' 시작 버튼 자동 탭")
                m = re.search(r'resource-id="[^"]*(?:locationStartBtn|startNaverBtnLayout|startNaver)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml_str)
                if m:
                    x1, y1, x2, y2 = map(int, m.groups())
                    self.inspector.run_adb(f"input tap {(x1+x2)//2} {(y1+y2)//2}")
                else:
                    self.inspector.run_adb("input tap 540 2345")
                time.sleep(0.6)
                continue

            # 2. 네트워크 오류 화면 감지
            if any(k in xml_str for k in ["네트워크에 연결할 수 없습니다", "네트워크 오류", "인터넷 연결을 확인", "다시 시도", "ERR_INTERNET_DISCONNECTED", "ERR_NAME_NOT_RESOLVED"]):
                logger.error(f"[{self.device_id}] [❌ 네트워크 오류 감지] WireGuard 터널 단절 또는 인터넷 불통 감지 -> 무지성 대기 중단 및 즉시 조기 탈출")
                return False

            has_searchbar = "searchBarRootView" in xml_str or "searchBarContainer" in xml_str or "검색어 또는 URL 입력" in xml_str or "searchBarOverlayWrapper" in xml_str
            has_dynamic_feed = any(ind in xml_str for ind in feed_indicators)

            if has_searchbar:
                logger.info(f"[{self.device_id}] [✓] 검색창 및 홈 화면 로딩 확인 완료! (소요 시간: {elapsed:.2f}s | Poll #{poll_i})")
                return True

        logger.warning(f"[{self.device_id}] [!] 동적 피드 로딩 대기 타임아웃 ({timeout_sec}s), 기본 홈 진행...")
        return True

    def wait_for_search_input_ready(self, timeout_sec: float = 5.0) -> bool:
        """[검색어 입력 화면 완전 로딩 및 키보드 활성화 판별 + 연속 2회 실패 시 자가복구]"""
        logger.info(f"[{self.device_id}] 검색어 입력 화면 및 키보드 로딩 판별 중...")
        start_t = time.time()

        for poll_i in range(1, int(timeout_sec * 4) + 1):
            time.sleep(0.25)
            top_act = self.inspector.run_adb("dumpsys activity activities | grep topResumedActivity")
            ime_status = self.inspector.run_adb("dumpsys input_method | grep mInputShown")

            is_suggest_act = any(k in top_act for k in ["SearchWindowSuggest", "searchwindow", "InAppBrowserActivity"])
            ime_ready = "mInputShown=true" in ime_status or "mShowRequested=true" in ime_status

            if is_suggest_act or ime_ready:
                elapsed = time.time() - start_t
                self.inspector.record_action_success("search_bar")
                logger.info(f"[{self.device_id}] [✓] 검색 입력창 및 키보드 로딩 완료 확인! (소요 시간: {elapsed:.2f}s | Poll #{poll_i})")
                return True

        # 실패 시 자가복구 카운터 증가 및 2회 도달 시 자가 재스캔
        fail_cnt = self.inspector.record_action_failure("search_bar")
        logger.warning(f"[{self.device_id}] [!] 검색 입력창 전환 대기 타임아웃 ({timeout_sec}s | 연속 실패: {fail_cnt}/2)...")
        if fail_cnt >= 2:
            logger.warning(f"[{self.device_id}] 🚨 [UI 자가복구 발동] 검색창 진입 연속 {fail_cnt}회 실패 감지 ➔ 캐시 무효화 및 실시간 화면 재계측!")
            self.inspector.invalidate_cache("search_bar_safe_bounds")
            try:
                import random
                new_bounds = self.inspector.get_search_bar_safe_bounds(force_rescan=True)
                rx = random.randint(new_bounds["x_min"], new_bounds["x_max"])
                ry = random.randint(new_bounds["y_min"], new_bounds["y_max"])
                logger.info(f"[{self.device_id}] 🔄 [자가복구 재탭] 새로 계측된 검색창 좌표({rx}, {ry}) 탭 실행...")
                self.inspector.run_adb(f"input tap {rx} {ry}")
                time.sleep(1.0)
                top_act = self.inspector.run_adb("dumpsys activity activities | grep topResumedActivity")
                ime_status = self.inspector.run_adb("dumpsys input_method | grep mInputShown")
                if any(k in top_act for k in ["SearchWindowSuggest", "searchwindow", "InAppBrowserActivity"]) or "mInputShown=true" in ime_status:
                    self.inspector.record_action_success("search_bar")
                    logger.info(f"[{self.device_id}] [🎉 자가복구 성공] 검색 입력창 정상 진입 확인 완료!")
                    return True
            except Exception as e:
                logger.warning(f"[{self.device_id}] 자가복구 재시도 실패: {e}")

        return False

    def wait_for_search_results_loaded(self, timeout_sec: float = 30.0) -> bool:
        """[검색 결과 페이지 완전 로딩 판별 다중 지표 (최대 30초 타임아웃)]"""
        logger.info(f"[{self.device_id}] 검색 결과 페이지(InAppBrowser) 완전 로딩 대기 중 (최대 {timeout_sec}초)...")
        start_t = time.time()

        for poll_i in range(1, int(timeout_sec * 4) + 1):
            time.sleep(0.25)
            top_act = self.inspector.run_adb("dumpsys activity activities | grep topResumedActivity")

            if "InAppBrowserActivity" in top_act:
                xml_str = self.inspector.run_adb("uiautomator dump /sdcard/sr_chk.xml >/dev/null 2>&1 && cat /sdcard/sr_chk.xml || true")
                has_webview = "inappWebView" in xml_str or "bodyView" in xml_str or "android.webkit.WebView" in xml_str
                has_toolbar = "tailView" in xml_str or "통합검색 버튼" in xml_str or "새로고침 버튼" in xml_str or "com.nhn.android.search:id" in xml_str

                if has_webview or has_toolbar or poll_i >= 6:
                    elapsed = time.time() - start_t
                    logger.info(f"[{self.device_id}] [✓] 검색 결과 페이지 및 웹뷰/툴바 완전 로딩 확인 완료! (소요 시간: {elapsed:.2f}s | Poll #{poll_i})")
                    return True

        logger.warning(f"[{self.device_id}] [!] 검색 결과 로딩 대기 타임아웃 ({timeout_sec}s), 검색 실행 완료로 간주 후 기본 진행...")
        return True

    def detect_shopping_section_and_code(self, target_mid: Optional[str] = None) -> Dict[str, Any]:
        """
        [STEP 3-1: 쇼핑 섹션 및 타겟 상품 mid 다중 추출 & 진입 전략 수립]
        - 광고/쿠팡/파워링크 노드를 원천 배제하고 순수 쇼핑 상품만 판별
        """
        target_mid_str = str(target_mid).strip() if target_mid else ""
        res_info = {
            "has_shopping_section": False,
            "section_type": None,
            "target_found_on_page": False,
            "target_bounds": None,
            "action_strategy": "FAIL_FAST",
            "extracted_mids": []
        }

        root = self.inspector.get_ui_tree("detect_shop")
        if root is None:
            logger.warning(f"[{self.device_id}] [!] UI 계층 구조 덤프 실패 -> 탐색 생략")
            return res_info

        all_nodes = list(root.iter("node"))
        shopping_block_node = None
        target_node = None
        extracted_mids = []

        # 유효한 9~14자리 타겟 mid 형식 검사
        valid_target = bool(target_mid_str and target_mid_str != "0" and len(target_mid_str) >= 9)

        for elem in all_nodes:
            t = elem.attrib.get("text", "").strip() or elem.attrib.get("content-desc", "").strip()
            rid = elem.attrib.get("resource-id", "").strip()
            b = elem.attrib.get("bounds", "").strip()

            # 🚫 광고/쿠팡/파워링크 노드 완전 배제
            if any(ad_kw in t or ad_kw in rid for ad_kw in ["파워링크", "광고", "coupang.com", "쿠팡", "ad_view", "sponsor"]):
                continue

            if any(kw in t for kw in ["가격비교", "네이버 쇼핑", "네이버쇼핑", "쇼핑베스트", "스마트스토어", "브랜드스토어", "트렌드쇼핑", "쇼핑", "핫딜", "추천상품"]):
                shopping_block_node = elem

            m_mid = re.findall(r"(?:view_type_guide_|mid=|id=)?(\d{9,14})", rid)
            # content-desc 및 text에서도 mid 매칭 추가
            if not m_mid:
                m_mid = re.findall(r"(?:mid=|id=)?(\d{9,14})", t)

            for m in m_mid:
                if m not in extracted_mids:
                    extracted_mids.append(m)

            # 정확한 mid 속성 일치 검증
            if valid_target and target_mid_str in m_mid:
                target_node = elem

        res_info["extracted_mids"] = extracted_mids

        # 쇼핑 블록 텍스트 또는 추출된 상품 mid가 1개 이상이면 쇼핑 섹션 존재로 판정
        if shopping_block_node is not None or len(extracted_mids) > 0:
            res_info["has_shopping_section"] = True
            res_info["section_type"] = "PRICE_COMPARISON"
            sb_bounds = shopping_block_node.attrib.get("bounds", "") if shopping_block_node else "DOM"
            t_block = (shopping_block_node.attrib.get("text", "").strip() or shopping_block_node.attrib.get("content-desc", "").strip()) if shopping_block_node else "쇼핑 상품 리스트"
            logger.info(f"[{self.device_id}] [✓] 쇼핑 블록('{t_block}') 확인 완료! (Bounds: {sb_bounds})")
        else:
            logger.warning(f"[{self.device_id}] [!] 쇼핑 섹션 없음 -> 쇼핑 무관 키워드로 판정")
            return res_info

        # 순수 추출된 mid 목록에 타겟 mid가 정확히 존재하는지 확인
        if valid_target and (target_mid_str in extracted_mids or target_node is not None):
            res_info["target_found_on_page"] = True
            if target_node is not None:
                tb = target_node.attrib.get("bounds", "")
                m_tb = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", tb)
                if m_tb:
                    res_info["target_bounds"] = list(map(int, m_tb.groups()))
                logger.info(f"[{self.device_id}] [🎯 타겟 발견] 타겟 상품 mid({target_mid_str})가 현재 뷰포트 DOM에 존재함! (Bounds: {tb})")
            else:
                logger.info(f"[{self.device_id}] [🎯 타겟 발견] 타겟 상품 mid({target_mid_str})가 뷰포트 mid 목록에 존재함!")
        else:
            res_info["target_found_on_page"] = False

        logger.info(f"[{self.device_id}]  ↳ 현재 페이지 노출된 상품 mid 목록 ({len(extracted_mids)}건): {extracted_mids[:10]}")
        return res_info

    def check_target_exists_fast(self, target_mid: str) -> bool:
        """[단순 탐색 모드(allow_click=False): 추가 스크롤 없이 DOM 상 타겟 mid 존재 여부만 즉시 판정]"""
        info = self.detect_shopping_section_and_code(target_mid)
        return info.get("target_found_on_page", False)

    def navigate_and_focus_target_card(self, target_mid: str, max_scroll_passes: int = 10, keyword: Optional[str] = None) -> Optional[Tuple[int, int]]:
        """
        [STEP 3-3: 타겟 상품 mid 탐색, 고정영역 배제 안전 안착 및 상품 제목(Title) 정밀 탭 좌표 계산]
        - 쇼핑 섹션이 없으면 스크롤 없이 즉시 조기 종료(Fail-Fast)
        - 쇼핑 섹션이 있으면 최대 10~12회 스크롤 다운을 수행하며 1페이지 내 타겟 상품을 끝까지 탐색
        - 발견 시 카드를 상하단 안전 영역(340~2260)에 안착시키고, 크롭 스크린샷 저장 및 타이틀 좌표 반환
        """
        target_mid_str = str(target_mid).strip()
        logger.info(f"[{self.device_id}] ========================================================")
        logger.info(f"[{self.device_id}] 🎯 [STEP 3-3] 타겟 상품 mid({target_mid_str}) 고정영역 배제 안전 포커싱")
        logger.info(f"[{self.device_id}] ========================================================")

        # 0. 1페이지 내 타겟 상품 탐색을 위해 최대 max_scroll_passes회 스크롤 순회
        SAFE_Y_MIN = 340   # 상단 고정 헤더/탭 제외 경계선
        SAFE_Y_MAX = 2260  # 하단 고정 툴바 제외 경계선

        for pass_num in range(1, max_scroll_passes + 1):
            root = self.inspector.get_ui_tree("safe_focus")
            if root is None:
                logger.warning(f"[{self.device_id}] [!] 화면 덤프 재시도 (Pass #{pass_num})")
                time.sleep(0.5)
                continue

            matched_card_bounds = None
            for elem in root.iter("node"):
                rid = elem.attrib.get("resource-id", "").strip()
                b = elem.attrib.get("bounds", "").strip()
                t = elem.attrib.get("text", "").strip() or elem.attrib.get("content-desc", "").strip()

                # 🚫 광고/쿠팡/파워링크 배제
                if any(ad_kw in t or ad_kw in rid for ad_kw in ["파워링크", "광고", "coupang.com", "쿠팡", "ad_view", "sponsor"]):
                    continue

                card_mids = re.findall(r"(?:view_type_guide_|mid=|id=)?(\d{9,14})", rid)
                if not card_mids:
                    card_mids = re.findall(r"(?:mid=|id=)?(\d{9,14})", t)

                is_matched = target_mid_str in card_mids or target_mid_str in rid or target_mid_str in t or target_mid_str in elem.attrib.get("content-desc", "")
                if is_matched and b:
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

                # 1. 상단 고정바 침범/잘림 검사
                if y1 < SAFE_Y_MIN:
                    shift = min(650, (SAFE_Y_MIN - y1) + 350)
                    logger.warning(f"[{self.device_id}]  ↳ [상단 침범/잘림 감지] y1({y1}) < SAFE_Y_MIN({SAFE_Y_MIN}) -> 역방향으로 {shift}px 내려 온전한 카드로 복원")
                    self.inspector.run_adb(f"input swipe 500 700 500 {700 + shift} 320")
                    time.sleep(0.5)
                    continue

                # 2. 하단 고정바 침범/잘림 검사
                elif y2 > SAFE_Y_MAX:
                    shift = min(650, (y2 - SAFE_Y_MAX) + 350)
                    logger.warning(f"[{self.device_id}]  ↳ [하단 고정바 충돌/잘림 감지] y2({y2}) > SAFE_Y_MAX({SAFE_Y_MAX}) -> 위로 {shift}px 올려 온전한 카드로 복원")
                    self.inspector.run_adb(f"input swipe 500 {1400 + shift} 500 1400 350")
                    time.sleep(0.5)
                    continue

                # 3. 온전한 안전 가시 영역 안착
                elif h >= 150:
                    # ⚠️ 정확한 상품 제목(Title) 영역 탭 (하단 스토어명/리뷰/찜 버튼/광고 오클릭 원천 방지)
                    # 상품 카드의 상단 18% ~ 35% 영역이 순수 상품 타이틀 링크 영역입니다.
                    pad_x = max(30, int((x2 - x1) * 0.15))
                    click_x = random.randint(x1 + pad_x, x2 - pad_x)
                    title_y_min = y1 + int(h * 0.18)
                    title_y_max = y1 + int(h * 0.35)
                    click_y = random.randint(title_y_min, max(title_y_min + 10, title_y_max))
                    logger.info(f"[{self.device_id}] [🎉 100% 안전 안착] 상품 카드 제목 영역 확정! [{SAFE_Y_MIN} <= Y1({y1}) & Y2({y2}) <= {SAFE_Y_MAX}] ➔ 타이틀 안전 터치: ({click_x}, {click_y})")
                    
                    # 📸 [타겟 상품 영역 크롭 저장 (logs/target_screenshot)]
                    try:
                        self.inspector.crop_and_save_target_screenshot(
                            target_bounds=(x1, y1, x2, y2),
                            target_mid=target_mid_str,
                            keyword=keyword,
                            click_coords=(click_x, click_y)
                        )
                    except Exception as e:
                        logger.warning(f"[{self.device_id}] 타겟 크롭 저장 중 예외: {e}")

                    # 📸 [공통: 타겟 상품 포착 직후 조준선 시각화 스샷 저장 (logs/click_logs/click_before)]
                    try:
                        self.inspector.draw_and_save_click_debug_image(
                            click_x, click_y,
                            target_mid=target_mid_str
                        )
                    except Exception as e:
                        logger.warning(f"[{self.device_id}] click_before 저장 중 예외: {e}")

                    return (click_x, click_y)

            # 타겟 카드가 아직 가시 화면에 완전히 들어오지 않은 경우 자연스러운 하향 스크롤
            scroll_dist = random.randint(650, 950)
            x1_s = random.randint(480, 600)
            y1_s = random.randint(1650, 1850)
            x2_s = x1_s + random.randint(-15, 15)
            y2_s = y1_s - scroll_dist
            duration = random.randint(320, 400)

            logger.info(f"[{self.device_id}]  ↳ [타겟 포커싱 스크롤 Pass #{pass_num}] ({x1_s}, {y1_s}) -> ({x2_s}, {y2_s}) [이동: {scroll_dist}px | {duration}ms]")
            self.inspector.run_adb(f"input swipe {x1_s} {y1_s} {x2_s} {y2_s} {duration}")
            time.sleep(random.uniform(0.6, 0.9))

        logger.warning(f"[{self.device_id}] [!] 최대 스크롤 횟수({max_scroll_passes}회) 도달 후에도 타겟 MID({target_mid_str}) 미노출 ➔ 사후 분석용 UI XML 덤프 저장")
        try:
            self.inspector.save_unexposed_dump(target_mid=target_mid_str, keyword=keyword)
        except Exception as e:
            logger.warning(f"[{self.device_id}] 미노출 덤프 저장 중 예외: {e}")
        return None

    def click_target_product_and_verify(self, target_coords_or_x: Any, click_y_or_mid: Any = None, timeout_sec: float = 30.0, target_mid: Optional[str] = None, keyword: Optional[str] = None, **kwargs) -> bool:
        """
        [STEP 3-4: 타겟 상품 안전 탭, click_logs 영구 저장 및 30초 충분한 상세페이지 진입 검증]
        """
        if isinstance(target_coords_or_x, (tuple, list)):
            cx, cy = int(target_coords_or_x[0]), int(target_coords_or_x[1])
            mid_val = str(target_mid or (click_y_or_mid if isinstance(click_y_or_mid, str) else "") or "").strip()
        else:
            cx, cy = int(target_coords_or_x), int(click_y_or_mid or 0)
            mid_val = str(target_mid or kwargs.get("mid") or "").strip()

        kw_val = keyword or kwargs.get("keyword")

        logger.info(f"[{self.device_id}] ========================================================")
        logger.info(f"[{self.device_id}] 🎯 [STEP 3-4] 타겟 상품 카드 안전 탭 ({cx}, {cy}) | MID: {mid_val} ➔ 상세페이지 진입 대기 (최대 {timeout_sec}초)")
        logger.info(f"[{self.device_id}] ========================================================")

        # 안전 탭 실행 (click_before는 STEP 3-3 포커싱 단계에서 이미 단 1회 정상 저장됨)
        self.inspector.run_adb(f"input tap {cx} {cy}")

        # 상세페이지 진입 다중 지표 검증 (최대 30초 대기)
        start_time = time.time()
        re_tapped = False

        while time.time() - start_time < timeout_sec:
            time.sleep(1.0)
            elapsed = round(time.time() - start_time, 1)

            root = self.inspector.get_ui_tree("detail_check")
            if root is not None:
                nodes = list(root.iter("node"))
                texts = [elem.attrib.get("text", "").strip() or elem.attrib.get("content-desc", "").strip() for elem in nodes]
                combined = " ".join(texts)

                # 1. 캡차/보안문자 차단 감지
                if any(k in combined for k in ["자동입력 방지", "보안문자", "비정상적인 접근", "차단되었습니다"]):
                    logger.error(f"[{self.device_id}] ❌ [보안 탐지 감지] 네이버 봇 탐지/캡차 페이지 노출됨! 즉시 중단합니다.")
                    return False

                # 2. 검색 결과 페이지 잔류 여부 엄격 검사 (상단 검색창/검색버튼이 남아있으면 아직 검색화면임)
                is_still_search_page = False
                for elem in nodes:
                    rid = elem.attrib.get("resource-id", "")
                    b = elem.attrib.get("bounds", "")
                    if any(s_id in rid for s_id in ["search_query", "search_btn", "search_clear_btn"]):
                        is_still_search_page = True
                        break
                    if kw_val and kw_val in elem.attrib.get("text", "") and b:
                        coords = b.replace("][", ",").replace("[", "").replace("]", "").split(",")
                        if len(coords) == 4 and int(coords[1]) < 350:
                            is_still_search_page = True
                            break

                if is_still_search_page:
                    # 검색 결과 페이지에 머물러 있는 상태 -> 전환 대기 및 보조 탭
                    if elapsed >= 4.0 and not re_tapped:
                        logger.info(f"[{self.device_id}] [ℹ️ 전환 대기/보조 탭] 클릭 후 {elapsed}초 경과 -> 타겟 좌표 ({cx}, {cy}) 1회 보조 탭 수행")
                        self.inspector.run_adb(f"input tap {cx} {cy}")
                        re_tapped = True
                    continue

                # 3. 상품 상세페이지 고유 식별자 검증 (하단 구매바 / 스마트스토어 전용 요소)
                PURCHASE_CTA = ["구매하기", "N Pay 구매", "바로구매", "선물하기", "장바구니"]
                DETAIL_BODY_KEYS = ["톡톡문의", "스토어찜", "알림받기", "상세정보", "상품정보 제공고시", "배송/교환/반품", "Q&A", "옵션 선택"]

                has_purchase_cta = any(any(cta == t or cta in t for cta in PURCHASE_CTA) for t in texts)
                has_detail_body = any(k in combined for k in DETAIL_BODY_KEYS)

                if has_purchase_cta or has_detail_body:
                    logger.info(f"[{self.device_id}] [✓] 상품 상세페이지 정상 진입 100% 확정! (소요 시간: {elapsed}s | 검색창 소멸 확인 | 구매CTA: {has_purchase_cta})")

                    # 📸 [상세페이지 첫 화면 캡처 저장] logs/click_logs/click_after/
                    try:
                        self.inspector.save_detail_page_screenshot(target_mid=mid_val, keyword=kw_val)
                    except Exception as e:
                        logger.warning(f"[{self.device_id}] 상세페이지 스크린샷 저장 중 예외: {e}")

                    try:
                        with open(f"/tmp/macro_product_detail_{self.device_id}.png", "wb") as f:
                            subprocess.run(["adb", "-s", self.device_id, "exec-out", "screencap", "-p"], stdout=f, timeout=5)
                    except Exception:
                        pass
                    return True

        logger.warning(f"[{self.device_id}] ❌ [!] 상품 상세페이지 로딩 타임아웃 ({timeout_sec}초 초과) -> 상세페이지 진입 실패 판정")
        return False
