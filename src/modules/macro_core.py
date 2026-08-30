#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
🚀 NAVER SHOPPING MODULAR MACRO CORE ENGINE (NaverMacroCore V2.0)
========================================================================================
- 순수 매크로 전용 개발 및 액션 제어 모듈 (리팩토링 완료)
- 내부 모듈 구조:
    • UIInspector (src.modules.macro.ui_inspector): ADB 실행, UI 덤프, 동적 좌표 감지
    • GestureEngine (src.modules.macro.gesture_engine): 권한 승인, 자연스러운 제스처, 30초 체류
    • SearchNavigator (src.modules.macro.search_navigator): 쇼핑 섹션 감지, 타겟 포커싱/클릭, 30초 검증
========================================================================================
"""

import time
import random
import logging
import subprocess
from typing import Dict, Any, Optional, Tuple

from src.config import NAVER_PKG, HOME_ACTIVITY
from src.modules.macro.ui_inspector import UIInspector
from src.modules.macro.gesture_engine import GestureEngine
from src.modules.macro.search_navigator import SearchNavigator

logger = logging.getLogger("NaverMacroCore")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [MacroCore] %(message)s",
        datefmt="%H:%M:%S"
    )


class NaverMacroCore:
    """
    네이버 쇼핑 자동화 매크로 코어 엔진
    """

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.inspector = UIInspector(device_id)
        self.gesture = GestureEngine(device_id, self.inspector)
        self.navigator = SearchNavigator(device_id, self.inspector)

    # -------------------------------------------------------------
    # 1. 하위 호환성 ADB & UI 헬퍼
    # -------------------------------------------------------------
    def _run_adb(self, cmd: str, timeout_sec: int = 5) -> str:
        return self.inspector.run_adb(cmd, timeout_sec)

    def _run_adb_su(self, cmd: str, timeout_sec: int = 5) -> str:
        return self.inspector.run_adb_su(cmd, timeout_sec)

    def _get_ui_tree(self, tmp_name: str = "ui_dump"):
        return self.inspector.get_ui_tree(tmp_name)

    def _get_device_config(self) -> dict:
        return self.inspector.get_device_config()

    def _update_device_config(self, updates: dict):
        return self.inspector.update_device_config(updates)

    def _draw_and_save_click_debug_image(self, click_x: int, click_y: int) -> str:
        return self.inspector.draw_and_save_click_debug_image(click_x, click_y)

    def get_home_tab_coords(self) -> Tuple[int, int]:
        return self.inspector.get_home_tab_coords()

    def get_search_bar_safe_bounds(self) -> Dict[str, int]:
        return self.inspector.get_search_bar_safe_bounds()

    # -------------------------------------------------------------
    # 2. Step 1: 클린 홈 기동 및 웜업
    # -------------------------------------------------------------
    def wait_for_home_fully_loaded(self, timeout_sec: float = 8.0) -> bool:
        return self.navigator.wait_for_home_fully_loaded(timeout_sec)

    def warm_up_home_scroll(self):
        self.gesture.warm_up_home_scroll()

    def launch_clean_home(self, timeout_sec: float = 8.0) -> bool:
        """
        [STEP 1: 네이버 메인 홈 화면 기동 & 웜업 스크롤]
        """
        logger.info(f"[{self.device_id}] ========================================================")
        logger.info(f"[{self.device_id}] 🚀 [STEP 1] 클린 홈 화면 기동 및 웜업")
        logger.info(f"[{self.device_id}] ========================================================")

        self._run_adb(f"am force-stop {NAVER_PKG} 2>/dev/null || true")
        time.sleep(0.3)

        logger.info(f"[{self.device_id}] 네이버 메인 홈 화면 기동 ({HOME_ACTIVITY})...")
        self._run_adb(f"am start -n {HOME_ACTIVITY} --activity-clear-top --activity-single-top")
        time.sleep(1.0)

        self.wait_for_home_fully_loaded(timeout_sec=timeout_sec)
        self.warm_up_home_scroll()

        shot_path = f"/tmp/macro_home_{self.device_id}.png"
        subprocess.run(["adb", "-s", self.device_id, "shell", "screencap -p /sdcard/home_ready.png"], stdout=subprocess.DEVNULL)
        subprocess.run(["adb", "-s", self.device_id, "pull", "/sdcard/home_ready.png", shot_path], stdout=subprocess.DEVNULL)
        logger.info(f"[{self.device_id}] [📸 홈 화면 캡처 저장 완료] -> {shot_path}")
        return True

    # -------------------------------------------------------------
    # 3. Step 2: 검색창 진입 & 검색 실행
    # -------------------------------------------------------------
    def tap_search_bar_random(self) -> Tuple[int, int]:
        return self.gesture.tap_search_bar_random()

    def wait_for_search_input_ready(self, timeout_sec: float = 5.0) -> bool:
        return self.navigator.wait_for_search_input_ready(timeout_sec)

    def enter_search_mode(self) -> bool:
        """[STEP 2-1: 검색창 탭 및 검색 모드 진입]"""
        logger.info(f"[{self.device_id}] ========================================================")
        logger.info(f"[{self.device_id}] 🚀 [STEP 2-1] 검색창 안전 랜덤 탭 및 입력창 로딩 검증")
        logger.info(f"[{self.device_id}] ========================================================")

        self.tap_search_bar_random()
        ready = self.wait_for_search_input_ready(timeout_sec=5.0)

        shot_path = f"/tmp/macro_search_input_{self.device_id}.png"
        subprocess.run(["adb", "-s", self.device_id, "shell", "screencap -p /sdcard/search_input_ready.png"], stdout=subprocess.DEVNULL)
        subprocess.run(["adb", "-s", self.device_id, "pull", "/sdcard/search_input_ready.png", shot_path], stdout=subprocess.DEVNULL)
        logger.info(f"[{self.device_id}] [📸 검색 입력 화면 캡처 저장 완료] -> {shot_path}")
        return ready

    def wait_for_search_results_loaded(self, timeout_sec: float = 30.0) -> bool:
        return self.navigator.wait_for_search_results_loaded(timeout_sec)

    def scroll_verify_search_results(self) -> None:
        self.gesture.scroll_verify_search_results()

    def execute_search(self, query: str) -> bool:
        """[STEP 2-2: ADBKeyboard 검색어 입력 및 정규 ENTER 제출 (최대 30초 로딩 대기)]"""
        logger.info(f"[{self.device_id}] ========================================================")
        logger.info(f"[{self.device_id}] 🚀 [STEP 2-2] 키워드 '{query}' 입력 및 검색 결과 로딩")
        logger.info(f"[{self.device_id}] ========================================================")

        import base64
        b64_query = base64.b64encode(query.encode("utf-8")).decode("ascii")
        logger.info(f"[{self.device_id}] ADBKeyboard를 통해 검색어 '{query}' 원자적 타이핑...")
        self._run_adb(f"am broadcast -a ADB_INPUT_B64 --es msg {b64_query}")

        time.sleep(random.uniform(1.5, 2.0))

        logger.info(f"[{self.device_id}] 소프트 키보드 ENTER 키(keyevent 66) 전송하여 검색 실행...")
        self._run_adb("input keyevent 66")

        loaded = self.wait_for_search_results_loaded(timeout_sec=30.0)
        if loaded:
            self.scroll_verify_search_results()

        shot_path = f"/tmp/macro_search_result_{self.device_id}.png"
        subprocess.run(["adb", "-s", self.device_id, "shell", "screencap -p /sdcard/search_result_ready.png"], stdout=subprocess.DEVNULL)
        subprocess.run(["adb", "-s", self.device_id, "pull", "/sdcard/search_result_ready.png", shot_path], stdout=subprocess.DEVNULL)
        logger.info(f"[{self.device_id}] [📸 검색 결과 페이지 캡처 저장 완료] -> {shot_path}")
        return loaded

    # -------------------------------------------------------------
    # 4. Step 3: 쇼핑 섹션 탐색 & 타겟 상품 포커싱/클릭
    # -------------------------------------------------------------
    def detect_shopping_section_and_code(self, target_mid: Optional[str] = None) -> Dict[str, Any]:
        return self.navigator.detect_shopping_section_and_code(target_mid)

    def fast_section_jump(self, jump_keyword: str = "다른 사이트 더보기") -> bool:
        return self.navigator.fast_section_jump(jump_keyword)

    def check_target_exists_fast(self, target_mid: str) -> bool:
        return self.navigator.check_target_exists_fast(target_mid)

    def navigate_and_focus_target_card(self, target_mid: str, max_scroll_passes: int = 12, keyword: Optional[str] = None) -> Optional[Tuple[int, int]]:
        return self.navigator.navigate_and_focus_target_card(target_mid, max_scroll_passes=max_scroll_passes, keyword=keyword)

    def click_target_product_and_verify(self, target_coords_or_x: Any, click_y: Optional[int] = None, timeout_sec: float = 30.0, **kwargs) -> bool:
        return self.navigator.click_target_product_and_verify(target_coords_or_x, click_y, timeout_sec=timeout_sec, **kwargs)

    # -------------------------------------------------------------
    # 5. Step 4: 상세페이지 30초 체류 및 탐색 스크롤
    # -------------------------------------------------------------
    def browse_product_detail_page(self, target_dwell_sec: float = 30.0, min_scrolls: int = 4, max_scrolls: int = 7) -> bool:
        return self.gesture.browse_product_detail_page(target_dwell_sec, min_scrolls, max_scrolls)

    # 파이프라인 호환용 별칭
    execute_step1_launch_clean_home = launch_clean_home
    execute_step2_search = execute_search
    execute_step3_expand_shopping_tab = fast_section_jump
    execute_step4_click_and_dwell = click_target_product_and_verify
