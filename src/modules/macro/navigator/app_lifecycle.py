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

    def wait_for_home_fully_loaded(self, timeout_sec: float = 25.0) -> bool:
        """
        [STEP 1: 네이버 메인 홈 완전 로딩 및 온보딩/위치 팝업 바이패스 검증]
        - '위치 정보에 접근할 수 없어' 다이얼로그 발생 시 즉시 '취소' 탭
        - '나중에 할게요' / '네이버 시작하기' 온보딩 발생 시 정밀 원터치 바이패스
        - 검색창 및 동적 피드 렌더링 완료 여부 고속 판별 (안정적인 25초 타임아웃)
        """
        logger.info(f"[{self.device_id}] 홈 화면 동적 콘텐츠(피드/날씨/배너) 완전 로딩 대기 중...")
        # 플립 단말기 메인 화면 OPEN 강제 보정 및 키가드 해제
        self.inspector.run_adb("cmd device_state state 3 2>/dev/null; input keyevent 224 2>/dev/null; wm dismiss-keyguard 2>/dev/null || true")
        start_t = time.time()
        deadline = start_t + timeout_sec
        poll_i = 0

        while time.time() < deadline:
            poll_i += 1
            time.sleep(0.4)
            elapsed = time.time() - start_t

            # 1. 고속 포커스 Activity 검사 (소요 시간 0.03s)
            top_act = self.inspector.run_adb("dumpsys activity activities | grep topResumedActivity 2>/dev/null || true")
            is_naver_active = ("com.nhn.android.search" in top_act)
            is_dialog_up = any(k in top_act for k in ["LocationTransparentActivity", "TransparentActivity", "Dialog", "AlertDialog", "GrantPermissionsActivity", "permissioncontroller"])
            is_home_resumed = any(k in top_act for k in ["SearchHomePage", "UniverseActivity", "MainActivity"]) and not is_dialog_up

            # 네이버 앱 및 시스템 다이얼로그가 화면에 올라오기 전(런처 등)에만 대기하고,
            # TutorialActivity 등 온보딩/시작 화면이 뜬 경우 즉시 UI 덤프를 진행하여 바이패스 실행
            if not is_naver_active and not is_dialog_up:
                time.sleep(0.3)
                continue

            # 2. UI Tree 덤프를 통한 홈 화면 및 검색창 완전 렌더링 검증 (--compressed로 초고속 0.5s 덤프)
            xml_str = self.inspector.run_adb(
                "rm -f /sdcard/home_chk.xml; uiautomator dump --compressed /sdcard/home_chk.xml >/dev/null 2>&1 && cat /sdcard/home_chk.xml || true",
                timeout_sec=6
            )

            # 2-0. Android 시스템 권한 다이얼로그 (알림/위치 권한 요청) 감지 시 즉시 '허용' 처리
            if "GrantPermissionsActivity" in top_act or "permission_allow" in xml_str or "알림을 보내도록 허용" in xml_str or "액세스하도록 허용" in xml_str:
                logger.warning(f"[{self.device_id}] ⚡ [시스템 권한 팝업 감지] 알림/권한 다이얼로그 즉시 허용 탭...")
                m_allow = re.search(r'resource-id="[^"]*(?:permission_allow_foreground_only_button|permission_allow_button)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml_str)
                if not m_allow:
                    m_allow = re.search(r'text="(?:앱 사용 중에만 허용|이번만 허용|허용)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml_str)
                if m_allow:
                    ax1, ay1, ax2, ay2 = map(int, m_allow.groups())
                    self.inspector.run_adb(f"input tap {(ax1+ax2)//2} {(ay1+ay2)//2}")
                else:
                    self.inspector.run_adb("input keyevent 4")
                time.sleep(0.5)
                continue

            # 2-0-B. '위치 정보에 접근할 수 없어' / LocationTransparentActivity 모달 팝업 감지 시 '취소' 또는 Back Key로 즉시 닫기
            if ("LocationTransparentActivity" in top_act) or "위치 정보에 접근할 수 없어" in xml_str or "설정 화면으로 이동하시겠습니까" in xml_str:
                logger.warning(f"[{self.device_id}] ⚡ [위치 모달 팝업 감지] '위치 정보 접근 불가' 다이얼로그 즉시 닫기(Back Key / 취소 탭)...")
                m_cancel = re.search(r'text="취소"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml_str)
                if m_cancel:
                    cx1, cy1, cx2, cy2 = map(int, m_cancel.groups())
                    self.inspector.run_adb(f"input tap {(cx1+cx2)//2} {(cy1+cy2)//2}")
                else:
                    self.inspector.run_adb("input keyevent 4")
                time.sleep(0.6)
                continue

            # 2-1. '나중에 할게요' 로그인 건너뛰기 감지 시 정밀 탭 (하단 네비게이션 제스처 바 회피 y1+10 탭)
            if "laterLoginBtn" in xml_str or "나중에 할게요" in xml_str:
                m = re.search(r'resource-id="[^"]*laterLoginBtn"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml_str)
                if not m:
                    m = re.search(r'text="나중에 할게요"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml_str)
                if m:
                    logger.info(f"[{self.device_id}] ⚡ [온보딩 감지] '나중에 할게요' 로그인 건너뛰기 정밀 탭")
                    x1, y1, x2, y2 = map(int, m.groups())
                    target_y = min(y1 + 10, (y1 + y2) // 2)
                    self.inspector.run_adb(f"input tap {(x1+x2)//2} {target_y}")
                    time.sleep(0.6)
                    continue

            # 2-2. '네이버 시작하기' 시작 버튼 감지 시 정밀 탭
            if "locationStartBtn" in xml_str or "startNaverBtnLayout" in xml_str or "네이버 시작하기" in xml_str:
                m = re.search(r'resource-id="[^"]*(?:locationStartBtn|startNaverBtnLayout|startNaver)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml_str)
                if not m:
                    m = re.search(r'text="네이버 시작하기"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml_str)
                if m:
                    logger.info(f"[{self.device_id}] ⚡ [온보딩 감지] '네이버 시작하기' 시작 버튼 정밀 탭")
                    x1, y1, x2, y2 = map(int, m.groups())
                    target_y = min((y1 + y2) // 2, y1 + 30)
                    self.inspector.run_adb(f"input tap {(x1+x2)//2} {target_y}")
                    time.sleep(0.6)
                    continue

            # 2-3. 네트워크 단절 오류 화면 감지
            network_error_keywords = [
                "ERR_INTERNET_DISCONNECTED", "ERR_NAME_NOT_RESOLVED", "ERR_CONNECTION_TIMED_OUT",
                "웹페이지를 사용할 수 없음", "페이지를 로드할 수 없음"
            ]
            if any(k in xml_str for k in network_error_keywords):
                logger.error(f"[{self.device_id}] [❌ 네트워크 오류 감지] WireGuard 터널 단절 또는 인터넷 불통 감지 -> 즉시 조기 탈출")
                return False

            has_searchbar = any(k in xml_str for k in ["searchBarRootView", "searchBarContainer", "검색어 또는 URL 입력", "customSearchBarLogoViewGroup", "searchBarOverlayWrapper"])
            if has_searchbar and (is_home_resumed or is_naver_active) and not is_dialog_up:
                logger.info(f"[{self.device_id}] [✓] 검색창 및 홈 화면 정상 로딩 확인 완료! (소요 시간: {elapsed:.2f}s | Poll #{poll_i})")
                return True

        logger.error(f"[{self.device_id}] ❌ 홈 로딩 대기 타임아웃 ({timeout_sec}s) -> 실패 중단")
        return False

    def wait_for_search_input_ready(self, timeout_sec: float = 6.0) -> bool:
        """
        [STEP 2: 검색어 입력 화면 완전 로딩 및 키보드 활성화 판별 + 미반응 시 정밀 재탭]
        """
        logger.info(f"[{self.device_id}] 검색어 입력 화면 및 키보드 로딩 판별 중...")
        start_t = time.time()
        deadline = start_t + timeout_sec
        poll_i = 0
        retried_center_tap = False

        while time.time() < deadline:
            poll_i += 1
            time.sleep(0.3)
            top_act = self.inspector.run_adb("dumpsys activity activities | grep topResumedActivity 2>/dev/null || true")
            ime_status = self.inspector.run_adb("dumpsys input_method | grep -E 'mInputShown|mServedView' 2>/dev/null || true")
            focus_str = self.inspector.run_adb("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' 2>/dev/null || true")

            # 실제 검색 제안(Suggest) / 검색창 액티비티 판별 (SearchHomePage는 홈 화면이므로 제외)
            is_suggest_act = any(k in top_act or k in focus_str for k in [
                "SearchWindowSuggest", "SearchWindow", "suggest", "Suggest", "searchwindow"
            ])
            has_nceditor = "NCEditor" in ime_status or "NCEditor" in focus_str
            is_modal = any(k in top_act or k in focus_str for k in [
                "LocationTransparentActivity", "TransparentActivity", "Dialog", "AlertDialog"
            ])

            if is_modal:
                logger.warning(f"[{self.device_id}] ⚡ [검색 입력 중 모달 감지] 모달 다이얼로그 즉시 닫기 (Back Key)...")
                self.inspector.run_adb("input keyevent 4")
                time.sleep(0.4)
                continue

            elapsed = time.time() - start_t
            # 홈 화면(SearchHomePage)이 topResumedActivity에 아직 있으면 미완료! 실제 검색창/에디터 활성화 확인
            if (is_suggest_act or has_nceditor) and "SearchHomePage" not in top_act and not is_modal:
                self.inspector.ensure_adb_keyboard_active()
                self.inspector.record_action_success("search_bar")
                logger.info(f"[{self.device_id}] [✓] 검색 입력창(Suggest/NCEditor) 로딩 완료 확인! (소요 시간: {elapsed:.2f}s | Poll #{poll_i})")
                return True

            # 1.0초 경과 시에도 홈 화면(SearchHomePage)에 머물러 있으면 검색창 중심 좌표(500, 500) 1회 정밀 재탭 (Retry Tap)
            if elapsed >= 1.0 and not retried_center_tap and ("SearchHomePage" in top_act or not is_suggest_act):
                logger.warning(f"[{self.device_id}] [!] 검색창 탭 미반응 감지 (홈 화면 잔류). 검색창 중심 좌표(500, 500) 1회 정밀 재탭 실행...")
                self.inspector.run_adb("input tap 500 500")
                retried_center_tap = True

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
                focus_str = self.inspector.run_adb("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'")
                top_act = self.inspector.run_adb("dumpsys activity activities | grep topResumedActivity 2>/dev/null || true")
                is_suggest_act = any(k in top_act or k in focus_str for k in ["SearchWindowSuggest", "SearchWindow", "suggest", "Suggest", "searchwindow"])
                is_modal = any(k in top_act or k in focus_str for k in ["LocationTransparentActivity", "TransparentActivity", "Dialog", "AlertDialog"])
                if (is_suggest_act or "com.nhn.android.search" in focus_str) and "SearchHomePage" not in top_act and not is_modal:
                    self.inspector.record_action_success("search_bar")
                    logger.info(f"[{self.device_id}] [🎉 자가복구 성공] 검색 입력창 정상 진입 확인 완료!")
                    return True
            except Exception as e:
                logger.warning(f"[{self.device_id}] 자가복구 재시도 실패: {e}")

        return False

    def wait_for_search_results_loaded(self, timeout_sec: float = 12.0) -> bool:
        """
        [STEP 3: 검색 결과 페이지 완전 로딩 다중 지표 엄격 검증]
        """
        logger.info(f"[{self.device_id}] 검색 결과 페이지 완전 로딩 대기 중 (최대 {timeout_sec}초)...")
        start_t = time.time()
        deadline = start_t + timeout_sec
        poll_i = 0
        enter_retried = False

        # 실제 브라우저 에러 페이지만 정밀 감지 (하단 툴바 '새로고침 버튼' 오인 방지)
        strict_network_error_keywords = [
            "ERR_INTERNET_DISCONNECTED", "ERR_NAME_NOT_RESOLVED", "ERR_CONNECTION_TIMED_OUT",
            "ERR_ADDRESS_UNREACHABLE", "ERR_CONNECTION_REFUSED", "ERR_SSL_PROTOCOL_ERROR",
            "웹페이지를 사용할 수 없음", "페이지를 로드할 수 없음", "사이트에 연결할 수 없습니다"
        ]

        while time.time() < deadline:
            poll_i += 1
            time.sleep(0.3)
            elapsed = time.time() - start_t

            # 2. UI Tree 덤프 기반 2차 엄격 검증 (항상 이전 덤프를 삭제하여 잔여 캐시 재인식 방지)
            xml_str = self.inspector.run_adb("rm -f /sdcard/sr_chk.xml; uiautomator dump /sdcard/sr_chk.xml >/dev/null 2>&1 && cat /sdcard/sr_chk.xml || true")
            
            # 네트워크 오류 감지 시 즉시 실패
            if any(k in xml_str for k in strict_network_error_keywords):
                logger.error(f"[{self.device_id}] [❌ 검색 결과 네트워크 오류 감지] 브라우저 연결 실패 ➔ 즉시 조기 탈출")
                return False

            # 2-0. 빈 검색어 또는 검색 결과 없음 화면 감지 -> Fail-Fast
            has_empty_error = any(k in xml_str for k in ["에 대한 검색결과가 없습니다", "결과없음", "단어의 철자가 정확한지"])
            if has_empty_error:
                logger.warning(f"[{self.device_id}] [⚠️ 빈 검색 결과 감지] '에 대한 검색결과가 없습니다' 노출 -> 즉시 실패 반환")
                return False

            # 메인 홈 화면 잔류 여부 확인
            is_on_home = any(k in xml_str for k in ["searchBarRootView", "검색어를 입력해주세요", "검색어 또는 URL 입력", "추천·구독", "MY구독"])

            # 검색 결과 탭 및 브라우저 컴포넌트 마커 확인
            has_search_markers = any(k in xml_str for k in [
                "블로그", "카페", "클립", "이미지", "지식iN", "동영상", "쇼핑", "VIEW", "어학사전", "뉴스",
                "inappWebView", "tailView", "search_clear", "다른 사이트 더보기", "네이버 가격비교", "쇼핑베스트",
                "광고", "관련문서", "스마트스토어"
            ])

            # 0. 고속 Activity 검사 (SearchPage 또는 InAppBrowserActivity 진입 + 렌더링 버퍼 확보 후 성공 판정)
            top_act = self.inspector.run_adb("dumpsys activity activities | grep topResumedActivity 2>/dev/null || true")
            if any(k in top_act for k in ["SearchPage", "InAppBrowserActivity"]):
                if elapsed >= 1.2 and not is_on_home and has_search_markers and not has_empty_error:
                    time.sleep(0.8)  # 웹뷰 DOM/쇼핑 섹션 렌더링 안정화 대기
                    logger.info(f"[{self.device_id}] [✓] 검색 결과 페이지 액티비티 및 렌더링 안착 감지! (소요 시간: {elapsed:.2f}s | Poll #{poll_i})")
                    return True

            # 1. Frida 웹뷰 활성 URL 기반 1차 엄격 검증
            current_url = self.inspector.get_current_webview_url().lower()
            if ("m.search.naver.com" in current_url or "search.naver.com" in current_url) and not is_on_home and not has_empty_error:
                if elapsed >= 1.2:
                    time.sleep(0.8)
                    logger.info(f"[{self.device_id}] [✓] 검색 결과 페이지 URL 감지 완료 ({current_url[:40]}...) (소요 시간: {elapsed:.2f}s | Poll #{poll_i})")
                    return True

            if elapsed >= 1.2 and not is_on_home and has_search_markers and not has_empty_error:
                logger.info(f"[{self.device_id}] [✓] 검색 결과 페이지 안착 및 마커 확인 완료! (소요 시간: {elapsed:.2f}s | Poll #{poll_i})")
                return True

            # 음성검색 팝업 방어 (우측 마이크 오인 탭 시 즉시 닫기 - 검색창 기본 마이크 버튼의 '음성검색' content-desc와 오인 방지)
            if "듣고 있어요" in xml_str or "음성으로 검색하려면" in xml_str:
                logger.warning(f"[{self.device_id}] ⚠️ 음성검색 팝업 감지 -> Back Key로 다이얼로그 즉시 닫기")
                self.inspector.run_adb("input keyevent 4")
                time.sleep(0.3)

            # 3. 2.0초 경과 시 메인 홈이나 검색 입력창에 잔류하고 있으면 Enter 1회 재전송 (Intent 모드 오인 발송 방어)
            if (is_on_home or any(k in top_act for k in ["SearchHome", "SearchHomePage"])) and elapsed >= 2.0 and not enter_retried:
                logger.warning(f"[{self.device_id}] 검색어 입력 후 결과 페이지 지연 감지. 엔터(Enter) 키 재전송...")
                self.inspector.run_adb("input keyevent 66")
                enter_retried = True

        logger.error(f"[{self.device_id}] ❌ 검색 결과 로딩 대기 타임아웃 ({timeout_sec}s) -> 실패 중단")
        return False

