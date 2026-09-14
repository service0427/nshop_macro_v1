#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 [뒤로가기 키입력(keyevent 4) 기반 초고속 워프 검증]
Target Device: R3CR70KAZDM
"""

import sys
import os
import time
import subprocess
import xml.etree.ElementTree as ET

DEVICE_ID = "R3CR70KAZDM"
xml_dest = "/home/tech/nshop_macro_v1/tests/back_keyevent_res.xml"
png_dest = "/home/tech/nshop_macro_v1/tests/back_keyevent_res.png"

print(f"=== [뒤로가기 키입력(keyevent 4) 기반 워프 검증] ({DEVICE_ID}) ===")

def run_adb(cmd: str):
    return subprocess.run(["adb", "-s", DEVICE_ID, "shell", cmd], capture_output=True, text=True)

# 1. TOP 원점 복귀
print("[*] 1. TOP 원점 복귀...")
run_adb("input swipe 540 800 540 1600 200")
time.sleep(0.4)
run_adb("input tap 993 2262; input swipe 540 500 540 2200 150")
time.sleep(1.0)

t0 = time.time()

# 2. 우측 하단 메뉴(≡) 탭
run_adb("input tap 990 2374")
time.sleep(0.35)

# 3. '페이지 내 검색' 탭
run_adb("input tap 546 2013")
time.sleep(0.35)

# 4. '다른 사이트 더보기' 입력 및 엔터 (keyevent 66)
run_adb("am broadcast -a ADB_INPUT_TEXT --es msg \"다른 사이트 더보기\" 2>/dev/null; input keyevent 66")
time.sleep(0.4)

# 5. 뒤로가기 키입력 (keyevent 4) 전송으로 검색바 즉시 닫기
run_adb("input keyevent 4")

t_elapsed = round(time.time() - t0, 2)
print(f"[✓] 뒤로가기 키입력(keyevent 4) 워프 완료! (소요 시간: {t_elapsed}초)")

# 6. 화면 덤프 및 검증
time.sleep(0.5)
run_adb("uiautomator dump /sdcard/back_key_res.xml")
subprocess.run(["adb", "-s", DEVICE_ID, "pull", "/sdcard/back_key_res.xml", xml_dest], capture_output=True)
run_adb("screencap -p /sdcard/back_key_res.png")
subprocess.run(["adb", "-s", DEVICE_ID, "pull", "/sdcard/back_key_res.png", png_dest], capture_output=True)

root = ET.parse(xml_dest).getroot()
print("\n=== 뒤로가기 키입력 후 화면 안착 현황 ===")
visible_nodes = []
for n in root.iter("node"):
    t = n.get("text", "").strip() or n.get("content-desc", "").strip()
    b = n.get("bounds", "").strip()
    if any(kw in t for kw in ["네이버 가격비교", "다른 사이트 더보기", "LG전자", "삼성전자", "베이직스", "갤럭시북", "그램"]):
        if b != "[0,0][0,0]" and "2347" not in b:
            visible_nodes.append((b, t[:65]))

for b, t in visible_nodes:
    print(f"  • [{b:21}] {t}")

print(f"\n• XML 증적: {xml_dest}")
print(f"• PNG 증적: {png_dest}")
