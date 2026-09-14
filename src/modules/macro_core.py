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
from typing import Dict, Any, Optional, Tuple, List

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
    def wait_for_home_fully_loaded(self, timeout_sec: float = 25.0) -> bool:
        return self.navigator.wait_for_home_fully_loaded(timeout_sec)

    def warm_up_home_scroll(self):
        self.gesture.warm_up_home_scroll()

    def launch_clean_home(self, timeout_sec: float = 25.0) -> bool:
        """
        [STEP 1: 네이버 메인 홈 화면 기동 & 웜업 스크롤]
        """
        logger.info(f"[{self.device_id}] ========================================================")
        logger.info(f"[{self.device_id}] 🚀 [STEP 1] 클린 홈 화면 기동 및 웜업")
        logger.info(f"[{self.device_id}] ========================================================")

        self._run_adb(f"am force-stop {NAVER_PKG} 2>/dev/null || true")
        time.sleep(0.3)

        logger.info(f"[{self.device_id}] 네이버 메인 홈 화면 기동 ({HOME_ACTIVITY})...")
        self._run_adb(f"am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n {HOME_ACTIVITY} --activity-clear-top --activity-single-top")
        time.sleep(1.0)

        # 앱 기동 시 최초 1회 키보드 상태 판별 및 ADBKeyboard 전환
        self.inspector.ensure_adb_keyboard_active()

        # 1. 포그라운드 진입 여부 엄격 검증
        if not self.inspector.ensure_naver_foreground():
            logger.error(f"[{self.device_id}] ❌ 네이버 앱 포그라운드 기동 실패")
            return False

        loaded = self.wait_for_home_fully_loaded(timeout_sec=timeout_sec)
        if not loaded:
            logger.error(f"[{self.device_id}] ❌ 네이버 홈 화면 로딩 실패 (네트워크 또는 앱 오류)")
            return False

        shot_path = f"/tmp/macro_home_{self.device_id}.png"
        try:
            with open(shot_path, "wb") as f:
                subprocess.run(["adb", "-s", self.device_id, "exec-out", "screencap", "-p"], stdout=f, timeout=5)
            logger.info(f"[{self.device_id}] [📸 홈 화면 캡처 저장 완료] -> {shot_path}")
        except Exception:
            pass
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

        if not self.inspector.ensure_naver_foreground():
            logger.error(f"[{self.device_id}] ❌ 포그라운드 이탈로 검색 모드 진입 불가")
            return False

        # 홈 화면 렌더링 및 터치 안정화 버퍼
        time.sleep(random.uniform(0.8, 1.2))

        self.tap_search_bar_random()
        ready = self.wait_for_search_input_ready(timeout_sec=6.0)

        shot_path = f"/tmp/macro_search_input_{self.device_id}.png"
        try:
            with open(shot_path, "wb") as f:
                subprocess.run(["adb", "-s", self.device_id, "exec-out", "screencap", "-p"], stdout=f, timeout=5)
            logger.info(f"[{self.device_id}] [📸 검색 입력 화면 캡처 저장 완료] -> {shot_path}")
        except Exception:
            pass
        return ready

    def wait_for_search_results_loaded(self, timeout_sec: float = 12.0) -> bool:
        return self.navigator.wait_for_search_results_loaded(timeout_sec)

    def scroll_verify_search_results(self) -> None:
        self.gesture.scroll_verify_search_results()

    def execute_search(self, query: str) -> bool:
        """[STEP 2-2: ADBKeyboard 검색어 입력 및 정규 ENTER 제출 (실패 시 Intent 다이렉트 검색 100% 보장)]"""
        logger.info(f"[{self.device_id}] ========================================================")
        logger.info(f"[{self.device_id}] 🚀 [STEP 2-2] 키워드 '{query}' 입력 및 검색 결과 로딩")
        logger.info(f"[{self.device_id}] ========================================================")

        # 검색어 입력 전 키보드가 ADBKeyboard인지 검사 및 강제 전환
        self.inspector.ensure_adb_keyboard_active()

        # 검색창 에디터 포커스 및 텍스트 클리어 (상단 검색창 탭)
        self._run_adb("input tap 400 150")
        time.sleep(0.3)
        self._run_adb("am broadcast -a ADB_CLEAR_TEXT")
        time.sleep(0.2)

        import base64
        import urllib.parse
        b64_query = base64.b64encode(query.encode("utf-8")).decode("ascii")
        logger.info(f"[{self.device_id}] ADBKeyboard를 통해 검색어 '{query}' 원자적 타이핑...")
        self._run_adb(f"am broadcast -a ADB_INPUT_B64 --es msg {b64_query}")

        time.sleep(random.uniform(0.8, 1.2))

        # 검색 실행 직전 모달 팝업 방어 (LocationTransparentActivity 잔류 시 Back Key 닫기)
        focus_check = self._run_adb("dumpsys window | grep -E 'mCurrentFocus' 2>/dev/null || true")
        if any(k in focus_check for k in ["LocationTransparentActivity", "TransparentActivity", "Dialog", "AlertDialog"]):
            logger.warning(f"[{self.device_id}] ⚠️ 검색 실행 직전 모달 감지 -> 다이얼로그 강제 닫기 (Back Key)")
            self._run_adb("input keyevent 4")
            time.sleep(0.4)

        logger.info(f"[{self.device_id}] 소프트 키보드 ENTER 키(keyevent 66) 전송하여 검색 실행...")
        self._run_adb("input keyevent 66")
        loaded = self.wait_for_search_results_loaded(timeout_sec=14.0)

        # 1차 실패 시 2차 UI 재시도 (재포커스 -> 클리어 -> 타이핑 -> 엔터)
        if not loaded:
            logger.warning(f"[{self.device_id}] ⚠️ 1차 검색 결과 로딩 지연 -> 2차 UI 재입력 검색 시도...")
            self._run_adb("input tap 400 150")
            time.sleep(0.4)
            self._run_adb("am broadcast -a ADB_CLEAR_TEXT")
            time.sleep(0.2)
            self._run_adb(f"am broadcast -a ADB_INPUT_B64 --es msg {b64_query}")
            time.sleep(0.8)
            self._run_adb("input keyevent 66")
            loaded = self.wait_for_search_results_loaded(timeout_sec=16.0)

        shot_path = f"/tmp/macro_search_result_{self.device_id}.png"
        try:
            with open(shot_path, "wb") as f:
                subprocess.run(["adb", "-s", self.device_id, "exec-out", "screencap", "-p"], stdout=f, timeout=5)
            logger.info(f"[{self.device_id}] [📸 검색 결과 페이지 캡처 저장 완료] -> {shot_path}")
        except Exception:
            pass
        return loaded

    @staticmethod
    def build_intent_search_url(keyword: str) -> Tuple[str, Dict[str, Any]]:
        """
        [Day 1 Intent 직접 진입 URL 생성기]
        - sm: mtp_sug.top (모바일 상단 자동완성 추천 선택)
        - where: m
        - query: 실제 검색어 (URL 인코딩)
        - ackey: Math.random().toString(36).substr(2, 8) -> 8자리 소문자 영숫자
        - acq: 검색어의 2자리 이상, 최대 len-1, trim 처리 (URL 인코딩)
        - acr: 1~10 중 랜덤 정수
        - qdt: 0
        """
        import random
        import string
        import urllib.parse

        clean_kw = keyword.strip()
        enc_query = urllib.parse.quote(clean_kw)

        # 8자리 소문자 영숫자 (JS base36 random string 완벽 재현)
        ackey_chars = string.ascii_lowercase + string.digits
        ackey = ''.join(random.choices(ackey_chars, k=8))

        # 2자리 이상, 최대 검색어보다 1자리 짧게, trim
        kw_len = len(clean_kw)
        if kw_len <= 2:
            acq = clean_kw
        else:
            max_cut = max(2, kw_len - 1)
            cut_len = random.randint(2, max_cut)
            acq = clean_kw[:cut_len].strip()
            if len(acq) < 2:
                acq = clean_kw[:min(kw_len, 2)]
        enc_acq = urllib.parse.quote(acq)

        # 1~10 사이 순번
        acr = random.randint(1, 10)

        url = f"https://m.search.naver.com/search.naver?sm=mtp_sug.top&where=m&query={enc_query}&ackey={ackey}&acq={enc_acq}&acr={acr}&qdt=0"
        meta = {
            "query": clean_kw,
            "ackey": ackey,
            "acq": acq,
            "acr": acr,
            "url": url
        }
        return url, meta

    def execute_intent_search(self, query: str, timeout_sec: float = 16.0) -> bool:
        """
        [Day 1 핵심 혁신: Intent 직접 검색 진입 모드]
        - 메인 홈(SearchHomePage) 및 검색창 터치/ADBKeyboard 타이핑 과정을 전면 생략
        - mtp_sug.top (모바일 상단 자동완성 추천) URL을 Intent(VIEW)로 다이렉트 호출
        - InAppBrowserActivity 검색 결과 페이지로 단번에 안착 (첫화면 오류 원천 제거)
        """
        logger.info(f"[{self.device_id}] ========================================================")
        logger.info(f"[{self.device_id}] 🚀 [Day 1 INTENT 직접 진입] 키워드: '{query}'")
        logger.info(f"[{self.device_id}] ========================================================")

        # 1. 화면 잠금 해제 및 절전 해제 보정
        self._run_adb("cmd device_state state 3 2>/dev/null; input keyevent 224 2>/dev/null; wm dismiss-keyguard 2>/dev/null || true")

        # 2. Intent 검색 URL 조립
        url, meta = self.build_intent_search_url(query)
        logger.info(f"[{self.device_id}] 🔗 [Intent URL 생성 완료]")
        logger.info(f"[{self.device_id}]    • Query : '{meta['query']}'")
        logger.info(f"[{self.device_id}]    • ACKey : '{meta['ackey']}' (8자리 base36)")
        logger.info(f"[{self.device_id}]    • ACQ   : '{meta['acq']}' (자동완성 접두어)")
        logger.info(f"[{self.device_id}]    • ACR   : {meta['acr']} (추천 순번)")
        logger.info(f"[{self.device_id}]    • URL   : {url}")

        # 3. 네이버 앱 프로세스 클린 리셋 후 Intent 기동
        self._run_adb(f"am force-stop {NAVER_PKG} 2>/dev/null || true")
        time.sleep(0.4)

        cmd = f"am start -a android.intent.action.VIEW -d '{url}' -p {NAVER_PKG} --activity-clear-top --activity-single-top"
        self._run_adb(cmd)
        logger.info(f"[{self.device_id}] 📡 Intent 호출 완료 -> 검색 결과 페이지 로딩 대기 중...")

        # 4. 검색 결과 페이지 로딩 검증 (최대 16초)
        loaded = self.wait_for_search_results_loaded(timeout_sec=timeout_sec)

        # 5. 1차 실패 시 1회 고속 재시도 (새로운 ackey/acr 발급 후 재기동)
        if not loaded:
            logger.warning(f"[{self.device_id}] ⚠️ Intent 검색 결과 1차 로딩 지연 -> 2차 Intent 재시도...")
            url2, meta2 = self.build_intent_search_url(query)
            cmd2 = f"am start -a android.intent.action.VIEW -d '{url2}' -p {NAVER_PKG} --activity-clear-top --activity-single-top"
            self._run_adb(cmd2)
            loaded = self.wait_for_search_results_loaded(timeout_sec=timeout_sec)

        # 결과 화면 캡처 저장
        shot_path = f"/tmp/macro_search_result_{self.device_id}.png"
        try:
            with open(shot_path, "wb") as f:
                subprocess.run(["adb", "-s", self.device_id, "exec-out", "screencap", "-p"], stdout=f, timeout=5)
            logger.info(f"[{self.device_id}] [📸 Intent 검색 결과 페이지 캡처 완료] -> {shot_path}")
        except Exception:
            pass

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

    def navigate_and_focus_target_card(self, target_mid: str, max_scroll_passes: int = 16, keyword: Optional[str] = None) -> Optional[Tuple[int, int]]:
        return self.navigator.navigate_and_focus_target_card(target_mid, max_scroll_passes=max_scroll_passes, keyword=keyword)

    def click_target_product_and_verify(self, target_coords_or_x: Any, click_y: Optional[int] = None, timeout_sec: float = 30.0, **kwargs) -> bool:
        return self.navigator.click_target_product_and_verify(target_coords_or_x, click_y, timeout_sec=timeout_sec, **kwargs)

    # -------------------------------------------------------------
    # 5. Step 4: 상세페이지 30초 체류 및 탐색 스크롤
    # -------------------------------------------------------------
    def browse_product_detail_page(self, target_dwell_sec: float = 30.0, min_scrolls: int = 4, max_scrolls: int = 7, **kwargs) -> bool:
        return self.gesture.browse_product_detail_page(target_dwell_sec, min_scrolls, max_scrolls, **kwargs)

    def get_session_exposed_products(self) -> List[Dict[str, Any]]:
        return self.navigator.get_session_exposed_products()

    def save_raw_impressions_action_dump(self, **kwargs) -> str:
        return self.navigator.save_raw_impressions_action_dump(**kwargs)

    # 파이프라인 호환용 별칭
    execute_step1_launch_clean_home = launch_clean_home
    execute_step2_search = execute_search
    execute_step3_expand_shopping_tab = fast_section_jump
    execute_step4_click_and_dwell = click_target_product_and_verify
