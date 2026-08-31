#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
🧭 NAVER SEARCH & SHOPPING TARGET NAVIGATOR (SearchNavigator Facade)
========================================================================================

📌 [모듈 아키텍처 개요 및 튜토리얼 (Architecture & Tutorial)]
----------------------------------------------------------------------------------------
이 모듈은 네이버 모바일 통합검색에서 타겟 상품(MID)을 초고속으로 탐색하고,
2단계 게이트 무결성 검증을 거쳐 '다른 사이트 더보기' 앵커로 다이렉트 워프한 뒤,
스마트스토어 상세페이지 진입과 30초 체류를 완수하는 매크로 핵심 내비게이터입니다.

[전체 4단계 라이프사이클 흐름도]
1. [앱 홈 & 검색창 활성화 (AppLifecycleManager)]
   - wait_for_home_fully_loaded(): 온보딩('나중에 할게요', '네이버 시작하기') 자동 바이패스
   - wait_for_search_input_ready(): IME 키보드 로딩 감지 및 2회 실패 시 자가복구
   - wait_for_search_results_loaded(): 검색 결과 웹뷰 및 툴바 완전 로딩 대기

2. [2단계 게이트 판정 & 초고속 워프 (PriceWarpNavigator)]
   - 🚪 Gate 1: '네이버 가격비교' 섹션 DOM 존재 유무 검증 -> 없으면 0회 스크롤 즉시 종료
   - 🚪 Gate 2: 가격비교 내 타겟 상품(MID) DOM 존재 유무 검증 -> 없으면 0회 스크롤 즉시 종료
   - ⚡ Jump: 존재 확정 시 '다른 사이트 더보기' 페이지 내 검색 0.7초 원자적 점프
   - 🎯 Slider: 가로 슬라이더(Slide 2) 감지 시 1회 가로 스와이프 후 상품 타이틀 좌표 산출

3. [상세페이지 진입 & 30초 체류 검증 (DetailPageVerifier)]
   - click_target_product_and_verify(): 타이틀 탭 ➔ 캡차 탐지 방어 ➔ 구매 CTA 확인 ➔ click_after 보관

4. [DOM 트리 분석 코어 (ShoppingXMLParser)]
   - detect_shopping_section_and_code(): 트리 단위의 MID, 상품명, 가격, 슬라이더 분류
========================================================================================
"""

import logging
from typing import Dict, Any, Optional, Tuple

from src.modules.macro.ui_inspector import UIInspector
from src.modules.macro.shopping_xml_parser import ShoppingXMLParser
from src.modules.macro.navigator.app_lifecycle import AppLifecycleManager
from src.modules.macro.navigator.price_warp_navigator import PriceWarpNavigator
from src.modules.macro.navigator.detail_page_verifier import DetailPageVerifier

logger = logging.getLogger("NaverMacroCore.SearchNavigator")


class SearchNavigator:
    """
    네이버 통합검색 내비게이터 통합 퍼사드 (Unified Navigator Facade)
    - 하위 전담 서브모듈(AppLifecycleManager, PriceWarpNavigator, DetailPageVerifier)을 조율
    - 기존 매크로 파이프라인(macro_core.py, daemon.py)과 100% 하위 호환성 보장
    """

    def __init__(self, device_id: str, inspector: UIInspector):
        self.device_id = device_id
        self.inspector = inspector

        # 서브모듈 인스턴스화
        self.lifecycle = AppLifecycleManager(device_id, inspector)
        self.warp_navigator = PriceWarpNavigator(device_id, inspector)
        self.verifier = DetailPageVerifier(device_id, inspector)
        self.xml_parser = ShoppingXMLParser()

    # ---------------------------------------------------------------------------------
    # 📱 1. 앱 홈 & 검색 입력 화면 생명주기 관리
    # ---------------------------------------------------------------------------------
    def wait_for_home_fully_loaded(self, timeout_sec: float = 8.0) -> bool:
        """[Phase 1] 홈 화면 동적 콘텐츠 로딩 및 온보딩/팝업 자동 바이패스"""
        return self.lifecycle.wait_for_home_fully_loaded(timeout_sec=timeout_sec)

    def wait_for_search_input_ready(self, timeout_sec: float = 5.0) -> bool:
        """[Phase 1] 검색어 입력 화면 완전 로딩 및 키보드 활성화 판별 (연속 실패 시 자가복구)"""
        return self.lifecycle.wait_for_search_input_ready(timeout_sec=timeout_sec)

    def wait_for_search_results_loaded(self, timeout_sec: float = 30.0) -> bool:
        """[Phase 2] 검색 결과 페이지(InAppBrowser) 완전 로딩 다중 지표 검증"""
        return self.lifecycle.wait_for_search_results_loaded(timeout_sec=timeout_sec)

    # ---------------------------------------------------------------------------------
    # 🔍 2. DOM 트리 기반 쇼핑 섹션 & 타겟 상품 분석
    # ---------------------------------------------------------------------------------
    def detect_shopping_section_and_code(self, target_mid: Optional[str] = None) -> Dict[str, Any]:
        """
        [Phase 2] UI XML 덤프를 ShoppingXMLParser로 트리 분석하여 쇼핑 섹션 및 타겟 상품 정보 산출
        """
        target_mid_str = str(target_mid).strip() if target_mid else ""
        root = self.inspector.get_ui_tree("detect_shop")
        if root is None:
            return {
                "has_shopping_section": False,
                "section_type": None,
                "target_found_on_page": False,
                "target_slide_page": None,
                "is_slide_1": False,
                "target_bounds": None,
                "action_strategy": "FAIL_FAST",
                "extracted_mids": [],
                "slide_1_mids": [],
                "slide_2_plus_mids": []
            }

        res = self.xml_parser.parse_shopping_section(root, target_mid=target_mid_str)
        res["has_shopping_section"] = bool(res.get("section_type") or len(res.get("extracted_mids", [])) > 0)
        return res

    def check_target_exists_fast(self, target_mid: str) -> bool:
        """[단순 탐색 모드(allow_click=False)] DOM 상 타겟 MID 존재 여부 즉시 판정"""
        info = self.detect_shopping_section_and_code(target_mid)
        return info.get("target_found_on_page", False)

    # ---------------------------------------------------------------------------------
    # ⚡ 3. 2단계 게이트 무결성 검증, 가격비교 다이렉트 워프 & 슬라이더 조준
    # ---------------------------------------------------------------------------------
    def jump_to_section_via_find_in_page(self, query: str = "다른 사이트 더보기") -> bool:
        """[Phase 3] 우측 하단 메뉴 ➔ '다른 사이트 더보기' 0.7초 원자적 앵커링 점프"""
        return self.warp_navigator.jump_to_section_via_find_in_page(query=query)

    def navigate_and_focus_target_card(
        self,
        target_mid: str,
        max_scroll_passes: int = 3,
        keyword: Optional[str] = None
    ) -> Optional[Tuple[int, int]]:
        """
        [Phase 3] 2단계 게이트 검증 ➔ '다른 사이트 더보기' 워프 ➔ Slide 1/2 안착 ➔ 타이틀 좌표 계산
        - Gate 1: '네이버 가격비교' 섹션 없음 ➔ 스크롤 0회 즉시 종료 (Fail-Fast)
        - Gate 2: 타겟 상품(MID) 없음 ➔ 스크롤 0회 즉시 종료 (Fail-Fast)
        - 통과 시: 워프 ➔ 슬라이더 보정 ➔ 타이틀 정밀 탭 좌표 (click_x, click_y) 반환
        """
        return self.warp_navigator.navigate_and_focus_target_card(target_mid=target_mid, keyword=keyword)

    # ---------------------------------------------------------------------------------
    # 🛒 4. 상품 클릭 & 스마트스토어 30초 체류 완주 검증
    # ---------------------------------------------------------------------------------
    def click_target_product_and_verify(
        self,
        target_coords_or_x: Any,
        click_y_or_mid: Any = None,
        timeout_sec: float = 30.0,
        target_mid: Optional[str] = None,
        keyword: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        [Phase 4] 상품 타이틀 안전 탭 ➔ 상세페이지 진입 대기 (최대 30초) ➔ 체류 증적 보관
        """
        if isinstance(target_coords_or_x, (tuple, list)):
            coords = (int(target_coords_or_x[0]), int(target_coords_or_x[1]))
            mid_val = str(target_mid or (click_y_or_mid if isinstance(click_y_or_mid, str) else "") or "").strip()
        else:
            coords = (int(target_coords_or_x), int(click_y_or_mid or 0))
            mid_val = str(target_mid or kwargs.get("mid") or "").strip()

        kw_val = keyword or kwargs.get("keyword")
        return self.verifier.click_target_product_and_verify(
            click_coords=coords,
            target_mid=mid_val,
            keyword=kw_val,
            timeout_sec=timeout_sec
        )
