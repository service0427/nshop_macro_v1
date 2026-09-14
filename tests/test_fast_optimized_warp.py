#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 초고속 튜닝된 핀포인트 워프 (2.5s 초고속 앵커 점프)
Target Device: R3CR70KAZDM
"""

import sys
import os
sys.path.insert(0, '/home/tech/nshop_macro_v1')

import time
import subprocess
import xml.etree.ElementTree as ET
from src.modules.macro_core import NaverMacroCore

DEVICE_ID = "R3CR70KAZDM"
SEARCH_KEYWORD = "노트북"

core = NaverMacroCore(DEVICE_ID)
print("[*] 1. '노트북' 검색 결과 로딩...")
core.enter_search_mode()
core.execute_search(SEARCH_KEYWORD)

time.sleep(1.0)
print("\n⚡ [2.5초 초고속 핀포인트 워프 실행 시작] ⚡")
t0 = time.time()

# 1. 우측 하단 메뉴 탭 (990, 2374)
subprocess.run(['adb', '-s', DEVICE_ID, 'shell', 'input tap 990 2374'])
time.sleep(0.35)

# 2. '페이지 내 검색' 탭 (546, 2013)
subprocess.run(['adb', '-s', DEVICE_ID, 'shell', 'input tap 546 2013'])
time.sleep(0.35)

# 3. '다른 사이트 더보기' 입력 및 엔터
subprocess.run(['adb', '-s', DEVICE_ID, 'shell', 'am broadcast -a ADB_INPUT_TEXT --es msg \"다른 사이트 더보기\" 2>/dev/null; input keyevent 66'])
time.sleep(0.4)

# 4. 툴바 닫기 (keyevent 4)
subprocess.run(['adb', '-s', DEVICE_ID, 'shell', 'input keyevent 4'])

t_elapsed = round(time.time() - t0, 2)
print(f"[✓] 초고속 핀포인트 워프 완료! (소요 시간: {t_elapsed}초)")

# 5. 화면 검증
dump_xml = subprocess.run(['adb', '-s', DEVICE_ID, 'shell', 'uiautomator dump /sdcard/fast_warp.xml && cat /sdcard/fast_warp.xml'], capture_output=True, text=True).stdout
if '<hierarchy' in dump_xml:
    root = ET.fromstring(dump_xml[dump_xml.find('<hierarchy'):])
    print('\n=== 워프 직후 화면 안착 현황 ===')
    for n in root.iter('node'):
        t = n.get('text', '').strip() or n.get('content-desc', '').strip()
        b = n.get('bounds', '').strip()
        if any(kw in t for kw in ['네이버 가격비교', '다른 사이트 더보기', 'LG전자', '삼성전자', '베이직스', '갤럭시북', '그램']):
            if b != '[0,0][0,0]' and '2347' not in b:
                print(f'  • [{b:21}] {t[:65]}')
