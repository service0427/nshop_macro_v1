#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
🔍 UI INSPECTOR & DYNAMIC COORDINATES DETECTOR (UIInspector)
========================================================================================
- 단말기 ADB 실행 및 XML UI 계층 구조 덤프/파싱
- 기기 해상도별 동적 좌표 추출 (검색창 안전 영역, 하단 홈 탭) 및 캐싱 관리
- 클릭 위치 시각화 디버깅 스크린샷 렌더링 및 /home/tech/nshop_macro_v1/click_logs 영구 보관
========================================================================================
"""

import os
import re
import json
import time
import shutil
import logging
import datetime
import subprocess
import xml.etree.ElementTree as ET
from typing import Dict, Any, Optional, Tuple
from src.config import (
    DEVICE_SET_FILE, CLICK_LOGS_DIR, CLICK_BEFORE_DIR, CLICK_AFTER_DIR, SCREENSHOT_DIR,
    UNEXPOSED_DUMPS_DIR, EXPOSED_DUMPS_DIR, get_dated_dir, prune_dir_by_age, LOG_RETENTION_DAYS
)
from src.modules.macro.image_archiver import MacroImageArchiver

logger = logging.getLogger("NaverMacroCore.UIInspector")

_BOUNDS_REGEX = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def parse_bounds(bounds_str: str) -> Optional[Tuple[int, int, int, int]]:
    """안드로이드 XML UI dump의 bounds 문자열('[x1,y1][x2,y2]')을 정규식으로 파싱하여 정수 튜플 (x1, y1, x2, y2) 반환"""
    if not bounds_str:
        return None
    m = _BOUNDS_REGEX.search(bounds_str)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return None


def prune_dir(dir_path: str, max_files: int = 200):
    """30일 기준 보존 정책으로 위임 (max_files 제한 제거)"""
    prune_dir_by_age(dir_path, retention_days=LOG_RETENTION_DAYS)


def prune_image_dir(dir_path: str, max_files: int = 200):
    """30일 기준 보존 정책으로 위임 (max_files 제한 제거)"""
    prune_dir_by_age(dir_path, retention_days=LOG_RETENTION_DAYS)


class UIInspector:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.image_archiver = MacroImageArchiver(
            device_id=device_id,
            run_adb_fn=self.run_adb,
            is_foreground_fn=self.is_naver_foreground
        )
        os.makedirs(CLICK_BEFORE_DIR, exist_ok=True)
        os.makedirs(CLICK_AFTER_DIR, exist_ok=True)
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    def run_adb(self, cmd: str, timeout_sec: int = 6) -> str:
        """기본 ADB shell 명령 실행"""
        try:
            full_cmd = ["adb", "-s", self.device_id, "shell", cmd]
            res = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout_sec)
            return res.stdout.strip()
        except Exception:
            return ""

    def run_adb_su(self, shell_cmd: str, timeout_sec: int = 3) -> str:
        """Root(su) 권한으로 단말기 셸 명령어 실행"""
        try:
            escaped_cmd = shell_cmd.replace('"', '\\"')
            cmd = ["adb", "-s", self.device_id, "shell", f'su -c "{escaped_cmd}"']
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
            return res.stdout.strip()
        except Exception:
            return ""

    def is_naver_foreground(self) -> bool:
        """현재 화면의 최상위 포커스 윈도우/앱이 네이버 앱인지 검사"""
        focus_str = self.run_adb("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp|topResumedActivity'", timeout_sec=2)
        if "com.nhn.android.search" in focus_str:
            return True
        # 삼성 키보드 등 IME 입력 중일 때는 네이버 앱 위의 자식 윈도우이므로 True 판정
        if any(ime in focus_str for ime in ["inputmethod", "InputMethod", "ADBKeyboard"]):
            return True
        return False

    def ensure_adb_keyboard_active(self) -> bool:
        """
        [키보드 상태 판별 및 ADBKeyboard 즉시 전환]
        현재 기본 키보드가 ADBKeyboard(com.android.adbkeyboard/.AdbIME)인지 판단하고,
        아닐 경우 즉시 활성화(enable) 및 기본 IME로 전환(set).
        """
        try:
            curr_ime = self.run_adb("settings get secure default_input_method").strip()
            if "com.android.adbkeyboard/.AdbIME" in curr_ime:
                return True

            logger.info(f"[{self.device_id}] ⌨️ 기본 키보드 '{curr_ime}' 감지 ➔ ADBKeyboard(AdbIME)로 전환...")
            self.run_adb("ime enable com.android.adbkeyboard/.AdbIME 2>/dev/null || true")
            self.run_adb("ime set com.android.adbkeyboard/.AdbIME 2>/dev/null || true")
            self.run_adb("settings put secure default_input_method com.android.adbkeyboard/.AdbIME 2>/dev/null || true")
            time.sleep(0.2)

            chk_ime = self.run_adb("settings get secure default_input_method").strip()
            if "com.android.adbkeyboard/.AdbIME" in chk_ime:
                logger.info(f"[{self.device_id}] [✓] ADBKeyboard 전환 완료 ({chk_ime})")
                return True
            else:
                logger.warning(f"[{self.device_id}] [!] ADBKeyboard 전환 재확인: {chk_ime}")
                return False
        except Exception as e:
            logger.warning(f"[{self.device_id}] ADBKeyboard 전환 중 예외: {e}")
            return False
    def get_current_webview_url(self) -> str:
        """Frida가 실시간 기록하는 인앱 웹뷰 현재 활성 URL 조회 (0.01s 초고속)"""
        try:
            return self.run_adb("cat /data/local/tmp/naver_webview_url.txt 2>/dev/null", timeout_sec=2).strip()
        except Exception:
            return ""

    def is_on_search_page(self, root: Optional[ET.Element] = None) -> bool:
        """현재 화면이 네이버 검색 결과 페이지(m.search.naver.com)인지 엄격 검증"""
        # Activity 검사: 메인 홈 화면(SearchHomePage) 잔류 여부 확인
        top_act = self.run_adb("dumpsys activity activities | grep topResumedActivity 2>/dev/null || true")
        if "SearchHomePage" in top_act:
            return False

        # 보조 검증: UI 덤프에 검색 결과 고유 마커 존재 여부
        if root is None:
            root = self.get_ui_tree("search_page_check")
        if root is not None:
            all_text = " ".join([e.attrib.get("text", "") or e.attrib.get("content-desc", "") or e.attrib.get("resource-id", "") for e in root.iter("node")])
            
            # 0. 빈 검색어 / 결과 없음 화면 감지 시 즉시 False
            if "에 대한 검색결과가 없습니다" in all_text or "결과없음" in all_text:
                return False

            # 메인 홈 화면 전용 고유 마커만 감지 (본문에 흔한 '날씨', '쇼핑' 등 배제)
            MAIN_HOME_MARKERS = ["searchBarRootView", "검색어를 입력해주세요", "검색어 또는 URL 입력", "홈피드"]
            if any(m in all_text for m in MAIN_HOME_MARKERS) and "SearchHomePage" in top_act:
                return False

            SEARCH_RESULT_MARKERS = [
                "블로그", "카페", "클립", "이미지", "지식iN", "동영상", "쇼핑", "VIEW", "어학사전", "뉴스",
                "inappWebView", "tailView", "search_clear", "통합검색", "다른 사이트 더보기", "네이버 가격비교", "쇼핑베스트",
                "nx_query", "nx_search_form", "nx_header", "_sch_tab", "power_link"
            ]
            if any(k in all_text for k in SEARCH_RESULT_MARKERS):
                return True

        url = self.get_current_webview_url().lower()
        if ("m.search.naver.com" in url or "search.naver.com" in url) and "SearchHomePage" not in top_act:
            return True
        return False

    def is_on_product_detail_page(self, root: Optional[ET.Element] = None) -> bool:
        """
        현재 화면이 스마트스토어/브랜드스토어 상품 페이지(m.smartstore.naver.com / m.brand.naver.com)인지 엄격 2중 검증
        - 1. URL 검증: m.smartstore.naver.com, m.brand.naver.com, smartstore.naver.com, brand.naver.com
        - 2. DOM 검증: 'N Pay 구매', '구매하기', '바로구매', '장바구니', '선물하기' 등 구매 전용 CTA 렌더링 확인
        """
        url = self.get_current_webview_url().lower()
        has_store_url = any(domain in url for domain in [
            "m.smartstore.naver.com", "m.brand.naver.com", "smartstore.naver.com", "brand.naver.com",
            "shopping.naver.com/v1/products", "shopping.naver.com/window-products", "/products/"
        ])

        if root is None:
            root = self.get_ui_tree("detail_page_check")

        has_purchase_cta = False
        has_detail_body = False
        if root is not None:
            all_text = " ".join([e.attrib.get("text", "") or e.attrib.get("content-desc", "") for e in root.iter("node")])
            PURCHASE_CTA = ["구매하기", "N Pay 구매", "바로구매", "선물하기", "장바구니"]
            DETAIL_BODY_KEYS = ["톡톡문의", "스토어찜", "알림받기", "상세정보", "상품정보 제공고시", "배송/교환/반품", "Q&A", "옵션 선택"]
            has_purchase_cta = any(cta in all_text for cta in PURCHASE_CTA)
            has_detail_body = any(k in all_text for k in DETAIL_BODY_KEYS)

        # 1. URL이 스마트스토어/브랜드스토어이고 구매 CTA가 있으면 100% 확정
        if has_store_url and (has_purchase_cta or has_detail_body):
            return True
        # 2. URL이 기록되지 않았더라도 구매 CTA 및 상세 바디가 모두 갖춰져 있고 검색 페이지가 아니면 확정
        elif has_purchase_cta and has_detail_body and "m.search.naver.com" not in url:
            return True
        return False

    def human_bio_tap(self, cx: int, cy: int, w: int = 400, h: int = 80) -> Tuple[int, int]:
        """
        [네이버 미어캣(Meerkat) / LCS 완벽 통과용 휴먼 생체 탭 엔진]
        1. 2D 가우시안 정규분포를 통한 자연스러운 타원형 터치 오프셋 (정중앙 기계적 편중 탈피)
        2. 미세 손떨림 및 마이크로 슬립 궤적(1~2px) 생성 -> screenCoords 다중 궤적 배열 자동 충족
        3. 실제 인간 엄지손가락 접촉 체류 시간(75ms ~ 115ms) -> from 시간 기계성 배제
        4. isTrusted: true 100% 보장 (안드로이드 OS 하드웨어 터치 파이프라인)
        """
        import random
        sigma_x = max(10, min(50, w // 8))
        sigma_y = max(8, min(20, h // 8))
        jitter_x = int(random.gauss(0, sigma_x / 2))
        jitter_y = int(random.gauss(0, sigma_y / 2))

        actual_x = cx + max(-w // 4, min(w // 4, jitter_x))
        actual_y = cy + max(-h // 4, min(h // 4, jitter_y))

        # 미세 손떨림 / 마이크로 궤적 (Micro-motion Trajectory: 1~2px 슬립)
        slip_dx = random.choice([-2, -1, 0, 1, 2])
        slip_dy = random.choice([-2, -1, 0, 1, 2])
        end_x = actual_x + slip_dx
        end_y = actual_y + slip_dy

        # 생체 접촉 지속 시간 (Human Dwell: 75ms ~ 115ms)
        duration_ms = random.randint(75, 115)

        logger.info(f"[{self.device_id}] 👆 [휴먼 생체 탭] ({actual_x}, {actual_y}) -> ({end_x}, {end_y}) [체류: {duration_ms}ms | 궤적 생성]")
        self.run_adb(f"input swipe {actual_x} {actual_y} {end_x} {end_y} {duration_ms}")
        return (actual_x, actual_y)

    def ensure_naver_foreground(self) -> bool:
        """네이버 앱이 포그라운드가 아닐 경우 즉시 전면으로 복귀"""
        if not self.is_naver_foreground():
            logger.warning(f"[{self.device_id}] [⚠️ 포그라운드 이탈 감지] 타사 앱/런처 감지 -> 네이버 앱 포그라운드 강제 복귀 실행...")
            self.run_adb("am start -n com.nhn.android.search/.ui.pages.SearchHomePage", timeout_sec=3)
            time.sleep(1.0)
            return self.is_naver_foreground()
        return True

    def get_ui_tree(self, tmp_name: str = "ui_dump") -> Optional[ET.Element]:
        """UIAutomator XML을 덤프하고 파싱하여 ElementTree Root 반환"""
        try:
            sdcard_path = f"/sdcard/{tmp_name}.xml"
            self.run_adb(f"uiautomator dump {sdcard_path}", timeout_sec=8.0)
            xml_str = self.run_adb(f"cat {sdcard_path}", timeout_sec=5.0)
            if not xml_str or "<hierarchy" not in xml_str:
                xml_str = self.run_adb("cat /sdcard/window_dump.xml", timeout_sec=5.0)
            if xml_str and "<hierarchy" in xml_str:
                xml_clean = xml_str[xml_str.find("<hierarchy"):]
                return ET.fromstring(xml_clean)
        except Exception as e:
            logger.warning(f"[{self.device_id}] get_ui_tree 파싱 실패: {e}")
        return None

    # 단말기별 UI 액션 연속 실패 카운터 (메모리 내 관리, 오버헤드 0%)
    _failure_counters: Dict[str, Dict[str, int]] = {}

    def get_device_config(self) -> dict:
        """device_set.json에서 해당 단말기 설정 조회"""
        if os.path.exists(DEVICE_SET_FILE):
            try:
                with open(DEVICE_SET_FILE, "r", encoding="utf-8") as f:
                    return json.load(f).get(self.device_id, {})
            except Exception:
                pass
        return {}

    def update_device_config(self, updates: dict):
        """device_set.json에 해당 단말기 설정 원자적 갱신"""
        data = {}
        if os.path.exists(DEVICE_SET_FILE):
            try:
                with open(DEVICE_SET_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        if self.device_id not in data:
            data[self.device_id] = {}
        data[self.device_id].update(updates)
        try:
            with open(DEVICE_SET_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def record_action_failure(self, action_name: str) -> int:
        """특정 UI 액션(search_bar, home_tab) 연속 실패 카운트 증가 및 반환"""
        if self.device_id not in UIInspector._failure_counters:
            UIInspector._failure_counters[self.device_id] = {}
        cnt = UIInspector._failure_counters[self.device_id].get(action_name, 0) + 1
        UIInspector._failure_counters[self.device_id][action_name] = cnt
        return cnt

    def record_action_success(self, action_name: str):
        """특정 UI 액션 성공 시 실패 카운트 0으로 초기화"""
        if self.device_id in UIInspector._failure_counters:
            UIInspector._failure_counters[self.device_id][action_name] = 0

    def invalidate_cache(self, cache_key: str):
        """device_set.json에서 특정 캐시 키를 원자적으로 제거하여 자가복구 트리거"""
        if os.path.exists(DEVICE_SET_FILE):
            try:
                with open(DEVICE_SET_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if self.device_id in data and cache_key in data[self.device_id]:
                    del data[self.device_id][cache_key]
                    with open(DEVICE_SET_FILE, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    logger.warning(f"[{self.device_id}] 🧹 [캐시 무효화] '{cache_key}' 캐시 삭제 완료 (다음 호출 시 실시간 재계측)")
            except Exception as e:
                logger.debug(f"[{self.device_id}] 캐시 무효화 예외: {e}")

    def get_home_tab_coords(self, force_rescan: bool = False) -> Tuple[int, int]:
        """
        [하단 '홈' 탭 버튼 동적 좌표 추출 및 1회 캐싱 (자가복구 지원)]
        - 기기 해상도 기준 하단 네비게이션 바의 2번째 탭('홈' 버튼) 중심 좌표를 계산하여 캐싱
        """
        if not force_rescan:
            config = self.get_device_config()
            cached = config.get("home_tab_coords")
            if cached and isinstance(cached, list) and len(cached) == 2:
                if cached[0] >= 250:
                    return tuple(cached)

        try:
            wm_size_out = self.run_adb("wm size")
            m_size = re.search(r"(\d+)x(\d+)", wm_size_out)
            if m_size:
                width, height = int(m_size.group(1)), int(m_size.group(2))
            else:
                width, height = 1080, 2400

            xml_str = self.run_adb("uiautomator dump /sdcard/home_nav.xml >/dev/null 2>&1 && cat /sdcard/home_nav.xml || true")
            nav_y = height - 40
            if "bottomNavigationView" in xml_str or "navigationContent" in xml_str:
                m_nav = re.search(r"resource-id=\"com\.nhn\.android\.search:id/(?:bottomNavigationView|navigationContent)\"[^>]*bounds=\"\[\d+,(\d+)\]\[\d+,(\d+)\]\"", xml_str)
                if m_nav:
                    y1, y2 = int(m_nav.group(1)), int(m_nav.group(2))
                    nav_y = (y1 + y2) // 2

            cx = int(width * 0.316)
            cy = nav_y

            logger.info(f"[{self.device_id}] [✓] 하단 '홈' 탭 버튼 정밀 좌표 확정: ({cx}, {cy})")
            self.update_device_config({"home_tab_coords": [cx, cy]})
            return (cx, cy)
        except Exception as e:
            logger.debug(f"[{self.device_id}] 하단 홈 탭 좌표 추출 예외: {e}")

        default_coords = (342, 2365)
        self.update_device_config({"home_tab_coords": list(default_coords)})
        return default_coords

    def get_search_bar_safe_bounds(self, force_rescan: bool = False) -> Dict[str, int]:
        """
        [상단 검색창 안전 클릭 영역 추출 및 1회 캐싱 (자가복구 지원)]
        - 검색창 bounds 중 로고 및 우측 AI 아이콘을 배제한 안전 텍스트 영역 산출 및 캐싱
        """
        if not force_rescan:
            config = self.get_device_config()
            cached = config.get("search_bar_safe_bounds")
            if cached and isinstance(cached, dict) and "x_min" in cached:
                return cached

        try:
            xml_str = self.run_adb("uiautomator dump /sdcard/sb_chk.xml >/dev/null 2>&1 && cat /sdcard/sb_chk.xml || true")
            if xml_str and "<hierarchy" in xml_str:
                tree = ET.fromstring(xml_str[xml_str.find("<hierarchy"):])
                for elem in tree.iter("node"):
                    rid = elem.attrib.get("resource-id", "")
                    d = elem.attrib.get("content-desc", "")
                    b = elem.attrib.get("bounds", "")
                    if any(k in rid for k in ["searchBar", "search_window", "query", "edit_search"]) or any(k in d for k in ["검색어 또는 URL 입력", "검색어를 입력해주세요", "검색창", "검색"]):
                        parsed = parse_bounds(b)
                        if parsed:
                            x1, y1, x2, y2 = parsed
                            w = x2 - x1
                            h = y2 - y1
                            if w > 300 and h > 50:  # 유효한 검색창 크기 필터
                                safe_bounds = {
                                    "x_min": int(x1 + w * 0.25),
                                    "x_max": int(x2 - w * 0.35),
                                    "y_min": int(y1 + h * 0.20),
                                    "y_max": int(y2 - h * 0.20),
                                    "raw_bounds": [x1, y1, x2, y2]
                                }
                                logger.info(f"[{self.device_id}] [✓] 검색창 안전 영역 추출 완료: X({safe_bounds['x_min']}~{safe_bounds['x_max']}), Y({safe_bounds['y_min']}~{safe_bounds['y_max']})")
                                self.update_device_config({"search_bar_safe_bounds": safe_bounds})
                                return safe_bounds
        except Exception as e:
            logger.debug(f"[{self.device_id}] 검색창 영역 파싱 예외: {e}")

        # 공통 해상도(1080x2400) 구형/신형 레이아웃 교집합 중심 (Y: 430~470)
        default_safe = {"x_min": 350, "x_max": 650, "y_min": 430, "y_max": 470, "raw_bounds": [60, 380, 1020, 520]}
        self.update_device_config({"search_bar_safe_bounds": default_safe})
        return default_safe

    def draw_and_save_click_debug_image(
        self,
        click_x: int,
        click_y: int,
        target_mid: Optional[str] = None,
        extra_info: Optional[str] = None,
        stage: str = "click_before"
    ) -> str:
        """[위임] 클릭/탐색 직전 화면 캡처 및 타겟 좌표 시각화 디버깅 스크린샷 저장"""
        return self.image_archiver.draw_and_save_click_debug_image(
            click_x=click_x,
            click_y=click_y,
            target_mid=target_mid,
            extra_info=extra_info,
            stage=stage
        )

    def crop_and_save_target_screenshot(
        self,
        target_bounds: Tuple[int, int, int, int],
        target_mid: str,
        keyword: Optional[str] = None,
        click_coords: Optional[Tuple[int, int]] = None
    ) -> str:
        """[위임] 타겟 상품 발견 시 해당 상품 영역만 크롭하여 일자별 폴더에 저장"""
        return self.image_archiver.crop_and_save_target_screenshot(
            target_bounds=target_bounds,
            target_mid=target_mid,
            keyword=keyword,
            click_coords=click_coords
        )

    def save_detail_page_screenshot(
        self,
        target_mid: str,
        keyword: Optional[str] = None
    ) -> str:
        """[위임] 상세페이지 진입 성공 시 랜딩 화면 전체 캡처를 일자별 폴더에 저장"""
        return self.image_archiver.save_detail_page_screenshot(
            target_mid=target_mid,
            keyword=keyword
        )

    def save_unexposed_dump(
        self,
        target_mid: str,
        keyword: Optional[str] = None
    ) -> Tuple[str, str]:
        """[위임] 타겟 상품 미노출 시 사후 분석을 위해 전체 UI XML 덤프 및 화면 캡처 저장"""
        return self.image_archiver.save_unexposed_dump(
            target_mid=target_mid,
            keyword=keyword
        )

    def save_exposed_dump(
        self,
        target_mid: str,
        keyword: Optional[str] = None,
        slide_page: int = 1
    ) -> Tuple[str, str]:
        """[위임] 타겟 상품 노출 시 증적 및 연구 분석을 위해 전체 UI XML 덤프 및 화면 캡처 저장"""
        return self.image_archiver.save_exposed_dump(
            target_mid=target_mid,
            keyword=keyword,
            slide_page=slide_page
        )
