#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config/settings.py

Global Settings & Constants for NShop Macro V1
"""

import os
from pathlib import Path

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
LOGS_DIR = PROJECT_ROOT / "logs"
CAPTURES_DIR = LOGS_DIR / "captures"
DATA_DIR = LOGS_DIR / "data"
INSTALL_DIR = PROJECT_ROOT / "install"
APKS_DIR = INSTALL_DIR / "apks"
BIN_DIR = INSTALL_DIR / "bin"
ASSETS_DIR = PROJECT_ROOT / "src" / "assets"

# Ensure runtime directories exist
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Data & Agent Files
TASKS_FILE = DATA_DIR / "tasks.json"
NNB_POOL_FILE = DATA_DIR / "nnb_pool.json"
HISTORY_FILE = DATA_DIR / "execution_history.json"
DEVICE_CONFIG_FILE = CONFIG_DIR / "device_settings.json"
FRIDA_AGENT_PATH = ASSETS_DIR / "cdp_clean_agent.js"

# App & Device Settings
NAVER_APP_PACKAGE = "com.nhn.android.search"
DEFAULT_DEVICE_ID = "R3CR70FFFEK"
DEFAULT_CDP_PORT = 9905

# FDS & Aging Policy
MIN_AGING_SECONDS = 1260   # 21분 (20분 FDS 하한선 + 1분 안전 마진)
TARGET_NNB_POOL_SIZE = 100 # 풀 목표 유지 수량 (Watermark)
STORE_COOLDOWN_SECONDS = 4800 # 80분 (상점 간 안전 쿨다운)

# Central API Settings
CENTRAL_API_BASE = os.getenv("CENTRAL_API_BASE", "http://114.207.112.173:8000")

# Network URLs
LCS_BEACON_URL = "https://lcs.naver.com/m"
SERP_BASE_URL = "https://m.search.naver.com/search.naver"
IP_CHECK_URL = "https://api.ipify.org"

# Pipeline Timings & QoS Configuration (SSOT)
from config.timings import PipelineTimings, TIMINGS

# [데이터 다이어트] 상세페이지 대용량 이미지 차단 패턴 (스마트에디터 본문 통이미지 및 대문 썸네일)
BLOCKED_DETAIL_IMAGE_URLS = [
    # 동영상 / 라이브 스트리밍
    "*.mp4*", "*.m3u8*", "*.webm*", "*.ts*",
    "*vod.pstatic.net*", "*naver-live*", "*shoppinglive*",
    # 스마트스토어 상세페이지 본문 대용량 통이미지 (w860, w960, w1000 등)
    "*shop-phinf.pstatic.net*type=w*",
    # 스마트스토어 상품 대문 대표/썸네일 대형 이미지 (510px, 1000px, 640px, 400px)
    "*shop-phinf.pstatic.net*type=m510*",
    "*shop-phinf.pstatic.net*type=m1000*",
    "*shop-phinf.pstatic.net*type=f640*",
    "*shop-phinf.pstatic.net*type=f400*",
    # 스마트에디터 연동 대용량 이미지
    "*post-phinf.pstatic.net*",
    "*seller-phinf.pstatic.net*",
    # 외부 상세페이지 이미지 호스팅
    "*gi.esmplus.com*",
    "*img.echosting.cafe24.com*",
    "*godo.co.kr*",
    "*makeshop.co.kr*"
]
