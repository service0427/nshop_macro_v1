#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 Naver Macro Core Search Test ('노트북' 검색 결과 덤프 및 무한 대기)
Target Device: R3CR70KAZDM
"""

import sys
import os
sys.path.insert(0, '/home/tech/nshop_macro_v1')

import time
import subprocess
from src.modules.macro_core import NaverMacroCore

DEVICE_ID = "R3CR70KAZDM"
SEARCH_KEYWORD = "노트북"

print(f"==========================================================================")
print(f"🚀 [Macro Core Test] '{DEVICE_ID}' 단말기 대상 '{SEARCH_KEYWORD}' 검색 실행")
print(f"==========================================================================")

core = NaverMacroCore(DEVICE_ID)

# 1. 홈 런칭
print("[1/3] 네이버 홈 화면 런칭 및 로딩...")
core.launch_clean_home(timeout_sec=8.0)

# 2. 검색창 탭 및 검색어 입력
print(f"[2/3] 검색창 진입 및 '{SEARCH_KEYWORD}' 타이핑...")
core.enter_search_mode()
core.execute_search(SEARCH_KEYWORD)

# 3. 검색 결과 화면 덤프 저장
xml_dest = "/home/tech/nshop_macro_v1/tests/notebook_search_dump.xml"
png_dest = "/home/tech/nshop_macro_v1/tests/notebook_search_dump.png"

subprocess.run(["adb", "-s", DEVICE_ID, "shell", "uiautomator dump /sdcard/nb_screen.xml"], check=False)
subprocess.run(["adb", "-s", DEVICE_ID, "pull", "/sdcard/nb_screen.xml", xml_dest], check=False)
subprocess.run(["adb", "-s", DEVICE_ID, "shell", "screencap -p /sdcard/nb_screen.png"], check=False)
subprocess.run(["adb", "-s", DEVICE_ID, "pull", "/sdcard/nb_screen.png", png_dest], check=False)

print(f"==========================================================================")
print(f"🎉 [3/3 성공] '{SEARCH_KEYWORD}' 검색 결과 로딩 완료!")
print(f"  • XML 덤프: {xml_dest}")
print(f"  • PNG 캡처: {png_dest}")
print(f"  • 상태: 무한 대기 (화면 유지)")
print(f"==========================================================================")

try:
    while True:
        time.sleep(1.0)
except KeyboardInterrupt:
    print("\n[*] 사용자에 의해 대기 종료됨.")
