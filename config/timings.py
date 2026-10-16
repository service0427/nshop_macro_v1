#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config/timings.py

Global Pipeline Timings & QoS Configuration (SSOT)
--------------------------------------------------
파이프라인 전 단계(기동, 통검, 쇼핑 전환, 쇼핑탭 탐색, 상세 체류, IP 토글 등)에
산재되어 있던 하드코딩 매직 넘버(타임아웃, 대기 간격, 재시도 횟수)를 단일 진실 공급원(SSOT)으로 집중 관리합니다.

QoS 대역폭 저하나 통신사 쓰로틀링(일 3GB 초과 등) 발생 시에도
안정적으로 동기화 및 타격을 유지할 수 있도록 적응형 파라미터를 제공합니다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineTimings:
    """단일 진실 공급원(SSOT) 글로벌 타임아웃 및 인터벌 설정"""

    # --------------------------------------------------------------------------
    # 1. Step 1: Clean Launcher & Frida Hooking (step1_launcher.py)
    # --------------------------------------------------------------------------
    LAUNCH_SERP_DEBUGGER_TIMEOUT: float = 20.0   # find_serp_debugger_url 최대 대기 (초, 토글 직후 웹뷰 지연 완충)
    LAUNCH_WS_CONNECT_TIMEOUT: float = 10.0      # websockets.connect 오픈 타임아웃 (초)
    LAUNCH_SET_COOKIE_TIMEOUT: float = 0.5       # NNB/BUC 쿠키 동기화 타임아웃 (초)
    LAUNCH_MAX_ATTEMPTS: int = 3                 # 인텐트 및 웹소켓 연결 최대 재시도

    # --------------------------------------------------------------------------
    # 2. Step 2: SERP Exploration & Fast-Fail (step2_serp.py)
    # --------------------------------------------------------------------------
    SERP_SECTION_POLL_INTERVAL: float = 0.2      # shp_ 쇼핑 섹션 감지 폴링 간격 (초)
    SERP_SECTION_MAX_WAIT: float = 15.0          # shp_ 섹션 최대 대기 (초, 멀티 병렬 환경 완충 15초)
    SERP_WARMUP_SWIPE_MIN_DELAY: float = 0.30    # SERP 워밍업 스와이프 최소 대기 (초)
    SERP_WARMUP_SWIPE_MAX_DELAY: float = 0.40    # SERP 워밍업 스와이프 최대 대기 (초)
    SERP_RESET_HOME_WAIT: float = 0.3            # SERP 최상단(Home) 복귀 후 완충 대기 (초)

    # --------------------------------------------------------------------------
    # 3. Step 3: Shopping Navigation (.more 버튼 터치) (step3_shop_nav.py)
    # --------------------------------------------------------------------------
    SHOP_NAV_MORE_POLL_INTERVAL: float = 0.3     # .more 버튼 감지 폴링 간격 (초)
    SHOP_NAV_MORE_MAX_WAIT: float = 7.5          # .more 버튼 최대 탐색 대기 (초, 25회 * 0.3s)
    SHOP_NAV_TRANSITION_TIMEOUT: float = 7.0     # 1차 쇼핑 더보기 터치 후 페이지 전환 타임아웃 (초, 통검 먹통 방지)
    SHOP_NAV_RETRY_TIMEOUT: float = 5.0          # 2차 정밀 재터치 후 페이지 전환 타임아웃 (초, 통검 먹통 방지)
    SHOP_NAV_TAB_SCAN_TIMEOUT: float = 2.0       # 분리된 웹뷰(InAppBrowser) 탭 스캔 제한 (초)

    # --------------------------------------------------------------------------
    # 4. Step 4: Shopping Tab Exploration & Strike (step4_shop.py)
    # --------------------------------------------------------------------------
    SHOP_NEXT_DATA_POLL_INTERVAL: float = 0.3    # __NEXT_DATA__ 타겟 사전 확인 간격 (초)
    SHOP_NEXT_DATA_MAX_WAIT: float = 12.0        # __NEXT_DATA__ 최대 대기 (초, 멀티 병렬 LTE 완충 12초)
    SHOP_MAX_SCROLL_COUNT: int = 8               # 쇼핑탭 타겟 포착을 위한 최대 확장 스크롤 횟수 (QoS 완충)
    SHOP_SCROLL_AJAX_POLL_INTERVAL: float = 0.3  # 인피니트 스크롤 AJAX 렌더링 폴링 간격 (초, 고속 반응)
    SHOP_SCROLL_AJAX_MAX_WAIT: float = 3.0       # 인피니트 스크롤 1회당 최대 AJAX 대기 (초, 10회 * 0.3s, 3GB 초과 감속 완충)
    SHOP_POST_SCROLL_SETTLE: float = 0.5         # 40개 노출/조기발견 후 레이아웃 정착 대기 (초)

    # --------------------------------------------------------------------------
    # 5. Step 5: Landing Verification & Organic Dwell (step5_landing.py)
    # --------------------------------------------------------------------------
    LANDING_SNIFF_POLL_INTERVAL: float = 0.3     # 리다이렉트/외부몰 스니핑 폴링 간격 (초)
    LANDING_SNIFF_MAX_WAIT: float = 30.0         # 리다이렉트/외부몰 스니핑 최대 대기 (초, 30초 관대 완충)
    LANDING_HYDRATION_POLL_INTERVAL: float = 0.4 # 스마트스토어 구매버튼/가격 수화 폴링 간격 (초)
    LANDING_HYDRATION_MAX_WAIT: float = 30.0     # 스마트스토어 수화 최대 대기 (초, 30초 관대 처리, 사용자 지침)
    DWELL_DEFAULT_SECONDS: float = 40.0          # 인간 체류 시간 중앙값 (초, 로그정규분포 기준)
    DWELL_MIN_SECONDS: float = 20.0              # 인간 체류 시간 하한선 (초)
    DWELL_MAX_SECONDS: float = 58.0              # 인간 체류 시간 상한선 (초)
    DWELL_HOME_BEACON_WAIT: float = 1.0          # Home 키 발송 후 onPause / sendBeacon 플러시 대기 (초)

    # --------------------------------------------------------------------------
    # 6. Universal Transition Waiter (transition_waiter.py)
    # --------------------------------------------------------------------------
    TRANSITION_DEFAULT_TIMEOUT: float = 7.0      # 기본 전환 타임아웃 (초)
    TRANSITION_POLL_INTERVAL: float = 0.15       # 전환 상태 하이브리드 검사 주기 (초)
    TRANSITION_CLICK_MISSED_THRESHOLD: float = 3.5 # 터치 불발(Click Missed) 의심 시작 시점 (초)

    # --------------------------------------------------------------------------
    # 7. Pinpoint CDP Touch & Capture (cdp_touch.py)
    # --------------------------------------------------------------------------
    TOUCH_PRE_DELAY_MIN: float = 0.50            # 물리 터치 직전 인간 시선 체류 지연 하한 (초)
    TOUCH_PRE_DELAY_MAX: float = 0.65            # 물리 터치 직전 인간 시선 체류 지연 상한 (초)
    TOUCH_HOLD_MS_MIN: float = 0.075             # 화면 가압 유지 시간 하한 (초, 75ms)
    TOUCH_HOLD_MS_MAX: float = 0.110             # 화면 가압 유지 시간 상한 (초, 110ms)
    SCREENSHOT_EXEC_TIMEOUT: float = 8.0         # adb exec-out screencap 타임아웃 (초)

    # --------------------------------------------------------------------------
    # 8. Master Runner & System Lifecycle (run.py)
    # --------------------------------------------------------------------------
    DEVICE_HARD_TIMEOUT: float = 140.0           # 기기당 하드 타임아웃 (초, 첫화면 30s + 수화 30s 관대 완충 + 체류 완결 보장)
    TARGET_CYCLE_DURATION: float = 90.0          # 회차당 권장 완충 주기 (초)
    MIN_CYCLE_DURATION: float = 0.0              # 회차당 최소 보장 완충 시간 (초, 0=즉시 순환)
    IP_TOGGLE_SETTLE_INTERVAL: float = 8.0       # IP 토글 완료 후 통신망 안정화 대기 시간 (초)
    NAVER_CONNECT_MAX_RETRIES: int = 10          # lcs.naver.com 통신망 개통 검증 최대 재시도 횟수
    NAVER_CONNECT_TIMEOUT_PER_TRY: float = 3.0   # lcs.naver.com 1회당 curl 타임아웃 (초)


# 글로벌 싱글톤 인스턴스
TIMINGS = PipelineTimings()
