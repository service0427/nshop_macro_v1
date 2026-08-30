# -*- coding: utf-8 -*-
"""
========================================================================================
N-Shop Automation Macro Global Configuration & Constants (src/config.py)
========================================================================================
"""

import os
from pathlib import Path

# --- 0. 프로젝트 디렉터리 경로 (동적 탐색) ---
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = str(BASE_DIR)

LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
CLICK_LOGS_DIR = os.path.join(LOGS_DIR, "click_logs")
CLICK_BEFORE_DIR = os.path.join(CLICK_LOGS_DIR, "click_before")
CLICK_AFTER_DIR = os.path.join(CLICK_LOGS_DIR, "click_after")
DEVICE_SET_FILE = os.path.join(PROJECT_ROOT, "device_set.json")
ALLOCATE_HISTORY_DIR = os.path.join(LOGS_DIR, "allocate_history")
RELEASE_HISTORY_DIR = os.path.join(LOGS_DIR, "release_history")
SCREENSHOT_DIR = os.path.join(LOGS_DIR, "target_screenshot")
UNEXPOSED_DUMPS_DIR = os.path.join(LOGS_DIR, "unexposed_dumps")
BATTERY_LOG_DIR = os.path.join(LOGS_DIR, "battery_history")
BATTERY_SUMMARY_LOG = os.path.join(LOGS_DIR, "battery_history.log")

for _d in [LOGS_DIR, CLICK_LOGS_DIR, CLICK_BEFORE_DIR, CLICK_AFTER_DIR, ALLOCATE_HISTORY_DIR, RELEASE_HISTORY_DIR, SCREENSHOT_DIR, UNEXPOSED_DUMPS_DIR, BATTERY_LOG_DIR]:
    os.makedirs(_d, exist_ok=True)

# --- 1. 네이버 앱 패키지 및 액티비티 ---
NAVER_PKG = "com.nhn.android.search"
HOME_ACTIVITY = "com.nhn.android.search/.ui.pages.SearchHomePage"
SEARCH_ACTIVITY = "com.nhn.android.search/.ui.pages.SearchHomeActivity"
IN_APP_BROWSER_ACTIVITY = "com.nhn.android.search/.inappbrowser.InAppBrowserActivity"

# --- 2. 화면 고정영역 배제 및 안전 마진 (Safe Touch Margin) ---
TOP_BAR_LIMIT = 340         # 상단 네비/검색/필터 고정바 영역 (이 이하로만 터치 허용)
BOTTOM_NAV_LIMIT = 2260     # 하단 탭바/장바구니 고정바 영역 (이 이상으로만 터치 허용)
TOUCH_HORIZONTAL_INSET = 80 # 좌우 베젤/사이드 패딩 회피 마진 (px)

# --- 3. WireGuard VPN 설정 ---
WG_PKG = "com.wireguard.android"
WG_MAIN_ACTIVITY = "com.wireguard.android/.activity.MainActivity"
DEFAULT_DNS = os.getenv("WG_DNS", "8.8.8.8, 1.1.1.1")
DEFAULT_MTU = int(os.getenv("WG_MTU", "1420"))
DEFAULT_ENDPOINT_PORT = int(os.getenv("WG_PORT", "45820"))
WG_SWITCH_BOUNDS = (876, 310, 1032, 454)  # (Left, Top, Right, Bottom)
WG_SWITCH_CENTER = (954, 382)             # 기본 탭 좌표

# --- 4. 중앙 관제 API 서버 설정 ---
PRIMARY_SERVER_URL = os.getenv("ROUTER_API_HOST", "http://114.207.112.173:5000")
BACKUP_SERVER_URL = os.getenv("ROUTER_BACKUP_HOST", "https://aaa4.kr")
ALLOCATE_ENDPOINT = "/api/v1/allocate"
RELEASE_ENDPOINT = "/api/v1/release"

# --- 5. 프로필 및 스냅샷 저장소 ---
PROFILE_STORAGE_DIR = "/data/local/tmp/profile_storage"

# --- 6. 스크롤 튜닝 파라미터 ---
MAX_SCROLL_DOWN_PX = 1100      # 1회 다운 스크롤 최대 이동량
SAFE_OVERLAP_PX = 700          # 지나침 방지 최소 중첩 안전거리
DETAIL_PAGE_MIN_SCROLLS = 2    # 상세페이지 체류 최소 스크롤 횟수
DETAIL_PAGE_MAX_SCROLLS = 5    # 상세페이지 체류 최대 스크롤 횟수
