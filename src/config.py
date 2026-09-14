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
EXPOSED_DUMPS_DIR = os.path.join(LOGS_DIR, "exposed_dumps")
RAW_IMPRESSIONS_DIR = os.path.join(LOGS_DIR, "raw_impressions")
BATTERY_LOG_DIR = os.path.join(LOGS_DIR, "battery_history")
BATTERY_SUMMARY_LOG = os.path.join(LOGS_DIR, "battery_history.log")

LOG_RETENTION_DAYS = 30  # 로그 및 증적 최소 30일 보존

for _d in [LOGS_DIR, CLICK_LOGS_DIR, CLICK_BEFORE_DIR, CLICK_AFTER_DIR, ALLOCATE_HISTORY_DIR, RELEASE_HISTORY_DIR, SCREENSHOT_DIR, UNEXPOSED_DUMPS_DIR, EXPOSED_DUMPS_DIR, RAW_IMPRESSIONS_DIR, BATTERY_LOG_DIR]:
    os.makedirs(_d, exist_ok=True)


def get_dated_dir(base_dir: str, date_str: str = None) -> str:
    """일자별(YYYY-MM-DD) 서브디렉토리 경로를 생성하고 반환"""
    import datetime
    if not date_str:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    target_path = os.path.join(base_dir, date_str)
    os.makedirs(target_path, exist_ok=True)
    return target_path


def prune_dir_by_age(base_dir: str, retention_days: int = LOG_RETENTION_DAYS):
    """
    30일 이상 경과한 오래된 로그/증적 파일 및 빈 일자별 서브폴더만 안전하게 정리.
    (30일 이내의 데이터는 수량과 무관하게 100% 영구 보존)
    """
    import time
    import shutil
    try:
        if not os.path.exists(base_dir):
            return
        now_ts = time.time()
        max_age_sec = retention_days * 86400

        # 1. 파일 단위 30일 경과 검사 및 삭제
        for root, dirs, files in os.walk(base_dir, topdown=False):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    mtime = os.path.getmtime(fpath)
                    if (now_ts - mtime) > max_age_sec:
                        os.remove(fpath)
                except Exception:
                    pass
            # 2. 비어있는 오래된 서브디렉토리 정리
            for dname in dirs:
                dpath = os.path.join(root, dname)
                try:
                    if not os.listdir(dpath):
                        os.rmdir(dpath)
                except Exception:
                    pass
    except Exception:
        pass

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
DEFAULT_DNS = os.getenv("WG_DNS", "168.126.63.1, 219.250.36.130, 8.8.8.8")
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

# --- 7. 작업 및 타임아웃 튜닝 파라미터 ---
MAX_CYCLE_TIMEOUT_SEC = 240.0         # 단일 사이클 전체 최대 허용 한계 시간 (240초)
DETAIL_TRANSITION_TIMEOUT_SEC = 30.0  # 타겟 클릭 후 상세페이지 전환 대기 타임아웃 (30초)
DETAIL_LOAD_TIMEOUT_SEC = 30.0        # 상세페이지 본문/CTA 렌더링 확인 타임아웃 (30초)

# --- 8. 보호 대상 단말기 (절대 작업/스케줄러 투입 금지) ---
EXCLUDED_DEVICES = []

# --- 9. 24시간 디바이스 격리 및 60분 순차 롤링 정책 (1회성 검증 모드) ---
DEVICE_COOLDOWN_SEC = float(os.getenv("DEVICE_COOLDOWN_SEC", 86400.0))  # 단말기 1대당 성공 쿨타임 24시간 (86,400초)
DEVICE_FAIL_COOLDOWN_SEC = float(os.getenv("DEVICE_FAIL_COOLDOWN_SEC", 3600.0))  # 클릭/작업 실패 시 단말기 쿨다운 (스토어 쿨다운 및 롤링 주기 일치: 60분, 3,600초)
DISPATCH_INTERVAL_SEC = float(os.getenv("DISPATCH_INTERVAL_SEC", 3600.0))  # 60분(3600초)마다 1대씩 순차 투입
MAX_DISPATCH_BATCH = int(os.getenv("MAX_DISPATCH_BATCH", 1))  # 1회 디스패치 시 최대 단말기 수 (60분에 1대씩)
DEVICE_COOLDOWN_FILE = os.path.join(LOGS_DIR, "device_cooldown_history.json")
DEVICE_FAIL_COOLDOWN_FILE = os.path.join(LOGS_DIR, "device_fail_cooldown_history.json")

# --- 10. 공인 IP(Egress IP) 24시간 쿨다운 2차 방어선 ---
IP_COOLDOWN_SEC = float(os.getenv("IP_COOLDOWN_SEC", 86400.0))  # 동일 공인 IP 24시간 격리
IP_COOLDOWN_FILE = os.path.join(LOGS_DIR, "ip_cooldown_history.json")

# --- 11. 검색 진입 모드 (Day 0: UI_TYPING vs Day 1: INTENT_DIRECT) ---
SEARCH_MODE = os.getenv("SEARCH_MODE", "INTENT_DIRECT")  # "INTENT_DIRECT" (기본값) 또는 "UI_TYPING"



