#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
📱 NAVER APP LIFECYCLE MANAGER (AppLifecycleManager)
========================================================================================
- 네이버 앱 메인 홈 화면 완전 로딩 및 온보딩/팝업 자동 바이패스
- 검색창 진입, IME 키보드 활성화 검증 및 연속 실패 시 자가복구(Self-Healing)
- 검색 결과 페이지(InAppBrowser) 및 웹뷰 완전 로딩 대기
========================================================================================
"""

import time
import re
import logging
import random
from typing import Optional

from src.modules.macro.ui_inspector import UIInspector

logger = logging.getLogger("NaverMacroCore.AppLifecycleManager")


class AppLifecycleManager:
    """네이버 앱 홈, 검색창, 검색 결과 페이지의 생명주기 및 안정적 진입을 관리하는 모듈"""

    def __init__(self, device_id: str, inspector: UIInspector):
        self.device_id = device_id
        self.inspector = inspector

    def wait_for_home_fully_loaded(self, timeout_sec: float = 8.0) -> bool:
        """
        [STEP 1: 네이버 홈 화면 완전 로딩 및 온보딩 자동 바이패스]
        - '나중에 할게요' 로그인 건너뛰기 팝업 자동 감지 및 탭
        - '네이버 시작하기' 온보딩 버튼 자동 감지 및 탭
        - 검색창 및 동적 피드 렌더링 완료 여부 판별
        """
        logger.info(f"[{self.device_id}] 홈 화면 동적 콘텐츠(피드/날씨/배너) 완전 로딩 대기 중...")
        start_t = time.time()
        feed_indicators = [
            "weatherText", "temperature", "priceTextView", "nameTextView",
            "content1", "content2", "channelTitle", "광고 이미지", "광고"
        ]

        for poll_i in range(1, int(timeout_sec * 4) + 1):
            time.sleep(0.35)
            elapsed = time.time() - start_t

            xml_str = self.inspector.run_adb(
                "rm -f /sdcard/home_chk.xml; uiautomator dump /sdcard/home_chk.xml >/dev/null 2>&1 && cat /sdcard/home_chk.xml || true"
            )

            # 1. '나중에 할게요' 로그인 건너뛰기 감지 시 정밀 탭
            if "laterLoginBtn" in xml_str or "나중에 할게요" in xml_str:
                m = re.search(r'resource-id="[^"]*laterLoginBtn"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml_str)
                if not m:
                    m = re.search(r'text="나중에 할게요"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml_str)
                if m:
                    logger.info(f"[{self.device_id}] ⚡ [온보딩 감지] '나중에 할게요' 로그인 건너뛰기 정밀 탭")
                    x1, y1, x2, y2 = map(int, m.groups())
                    target_y = min((y1 + y2) // 2, y1 + 15)
                    self.inspector.run_adb(f"input tap {(x1+x2)//2} {target_y}")
                    time.sleep(0.8)
                    continue

            # 2. '네이버 시작하기' 시작 버튼 감지 시 정밀 탭
            if "locationStartBtn" in xml_str or "startNaverBtnLayout" in xml_str or "네이버 시작하기" in xml_str:
                m = re.search(r'resource-id="[^"]*(?:locationStartBtn|startNaverBtnLayout|startNaver)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml_str)
                if not m:
                    m = re.search(r'text="네이버 시작하기"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml_str)
                if m:
                    logger.info(f"[{self.device_id}] ⚡ [온보딩 감지] '네이버 시작하기' 시작 버튼 정밀 탭")
                    x1, y1, x2, y2 = map(int, m.groups())
                    target_y = min((y1 + y2) // 2, y1 + 30)
                    self.inspector.run_adb(f"input tap {(x1+x2)//2} {target_y}")
                    time.sleep(0.8)
                    continue

            # 3. 포그라운드 이탈 방지
            self.inspector.ensure_naver_foreground()

            # 4. 네트워크 오류 화면 감지 (인터넷/VPN 단절 시 조기 탈출)
            if any(k in xml_str for k in ["네트워크에 연결할 수 없습니다", "네트워크 오류", "인터넷 연결을 확인", "다시 시도", "ERR_INTERNET_DISCONNECTED", "ERR_NAME_NOT_RESOLVED"]):
                logger.error(f"[{self.device_id}] [❌ 네트워크 오류 감지] WireGuard 터널 단절 또는 인터넷 불통 감지 -> 즉시 조기 탈출")
                return False

            has_searchbar = any(k in xml_str for k in ["searchBarRootView", "searchBarContainer", "검색어 또는 URL 입력", "searchBarOverlayWrapper"])
            if has_searchbar:
                logger.info(f"[{self.device_id}] [✓] 검색창 및 홈 화면 로딩 확인 완료! (소요 시간: {elapsed:.2f}s | Poll #{poll_i})")
                return True

        logger.warning(f"[{self.device_id}] [!] 홈 로딩 대기 타임아웃 ({timeout_sec}s), 기본 진행...")
        return True

    def wait_for_search_input_ready(self, timeout_sec: float = 5.0) -> bool:
        """
        [STEP 2: 검색어 입력 화면 완전 로딩 및 키보드 활성화 판별 + 연속 2회 실패 시 자가복구]
        """
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

        fail_cnt = self.inspector.record_action_failure("search_bar")
        logger.warning(f"[{self.device_id}] [!] 검색 입력창 전환 대기 타임아웃 ({timeout_sec}s | 연속 실패: {fail_cnt}/2)...")
        if fail_cnt >= 2:
            logger.warning(f"[{self.device_id}] 🚨 [UI 자가복구 발동] 검색창 진입 연속 {fail_cnt}회 실패 감지 ➔ 실시간 화면 재계측!")
            self.inspector.invalidate_cache("search_bar_safe_bounds")
            try:
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
        """
        [STEP 3: 검색 결과 페이지(InAppBrowser) 완전 로딩 다중 지표 검증]
        """
        logger.info(f"[{self.device_id}] 검색 결과 페이지(InAppBrowser) 완전 로딩 대기 중 (최대 {timeout_sec}초)...")
        start_t = time.time()

        for poll_i in range(1, int(timeout_sec * 4) + 1):
            time.sleep(0.25)
            top_act = self.inspector.run_adb("dumpsys activity activities | grep topResumedActivity")

            if "InAppBrowserActivity" in top_act:
                xml_str = self.inspector.run_adb("uiautomator dump /sdcard/sr_chk.xml >/dev/null 2>&1 && cat /sdcard/sr_chk.xml || true")
                has_webview = any(k in xml_str for k in ["inappWebView", "bodyView", "android.webkit.WebView"])
                has_toolbar = any(k in xml_str for k in ["tailView", "통합검색 버튼", "새로고침 버튼", "com.nhn.android.search:id"])

                if has_webview or has_toolbar or poll_i >= 6:
                    elapsed = time.time() - start_t
                    logger.info(f"[{self.device_id}] [✓] 검색 결과 페이지 및 웹뷰/툴바 완전 로딩 확인 완료! (소요 시간: {elapsed:.2f}s | Poll #{poll_i})")
                    return True

        logger.warning(f"[{self.device_id}] [!] 검색 결과 로딩 대기 타임아웃 ({timeout_sec}s), 기본 진행...")
        return True
