#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 10x Consecutive Price Comparison Warp Reliability Test
Target Device: R3CR70KAZDM
Workflow per iteration:
  1. Scroll / Return to TOP of search result page
  2. Perform "다른 사이트 더보기" Warp (Menu -> Find in page -> Enter -> Close bar)
  3. Verify "네이버 가격비교" & Product Card Visibility
  4. Record elapsed time, status, and coordinates
"""

import sys
import os
import time
import re
import subprocess
import xml.etree.ElementTree as ET

DEVICE_ID = "R3CR70KAZDM"
TOTAL_ROUNDS = 10
LOG_DIR = "/home/tech/nshop_macro_v1/tests/warp_10x_logs"
os.makedirs(LOG_DIR, exist_ok=True)

print("=" * 80)
print(f"🚀 [10회 연속 신뢰성 검증] '노트북' 검색 결과 가격비교 앵커 워프 테스트 시작 ({DEVICE_ID})")
print("=" * 80)

results = []

def run_adb(cmd: str):
    return subprocess.run(["adb", "-s", DEVICE_ID, "shell", cmd], capture_output=True, text=True)

def return_to_top():
    """TOP 버튼 또는 강제 상향 제스처로 검색 결과 최상단 원점 복귀"""
    # 1. 미세 상향 제스처로 TOP 플로팅 버튼 활성화
    run_adb("input swipe 540 800 540 1600 200")
    time.sleep(0.5)
    
    # 2. TOP 플로팅 버튼 탭 (993, 2262 또는 990, 2200) 또는 상향 플링
    run_adb("input tap 993 2262; input swipe 540 500 540 2200 150")
    time.sleep(1.0)

def execute_anchor_warp(round_idx: int) -> dict:
    t_start = time.time()
    
    # Step A: 우측 하단 메뉴 더보기(≡) 버튼 탭
    run_adb("input tap 990 2374")
    time.sleep(0.6)
    
    # Step B: 시트에서 '페이지 내 검색' 노드 탐색 및 탭
    sheet_xml = run_adb("uiautomator dump /sdcard/sheet_chk.xml && cat /sdcard/sheet_chk.xml").stdout
    find_coords = (546, 2013) # Default verified center
    
    if "<hierarchy" in sheet_xml:
        try:
            root_s = ET.fromstring(sheet_xml[sheet_xml.find("<hierarchy"):])
            for n in root_s.iter("node"):
                t = n.get("text", "").strip() or n.get("content-desc", "").strip()
                b = n.get("bounds", "").strip()
                if "페이지 내 검색" in t and b:
                    m = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
                    if m:
                        x1, y1, x2, y2 = map(int, m.groups())
                        find_coords = ((x1 + x2) // 2, (y1 + y2) // 2)
                        break
        except Exception:
            pass
            
    run_adb(f"input tap {find_coords[0]} {find_coords[1]}")
    time.sleep(0.6)
    
    # Step C: '다른 사이트 더보기' 입력 및 엔터 (keyevent 66)
    run_adb("am broadcast -a ADB_INPUT_TEXT --es msg \"다른 사이트 더보기\" 2>/dev/null; input keyevent 66")
    time.sleep(0.5)
    
    # Step D: 검색 툴바 닫기 (keyevent 4)
    run_adb("input keyevent 4")
    time.sleep(0.4)
    
    t_elapsed = round(time.time() - t_start, 2)
    
    # Step E: 화면 덤프 및 검증
    dump_xml_path = f"{LOG_DIR}/round_{round_idx:02d}_warp.xml"
    dump_png_path = f"{LOG_DIR}/round_{round_idx:02d}_warp.png"
    
    run_adb("uiautomator dump /sdcard/round_chk.xml")
    subprocess.run(["adb", "-s", DEVICE_ID, "pull", "/sdcard/round_chk.xml", dump_xml_path], capture_output=True)
    run_adb("screencap -p /sdcard/round_chk.png")
    subprocess.run(["adb", "-s", DEVICE_ID, "pull", "/sdcard/round_chk.png", dump_png_path], capture_output=True)
    
    # XML 분석
    has_header = False
    header_bounds = None
    visible_products = []
    
    if os.path.exists(dump_xml_path):
        try:
            root_v = ET.parse(dump_xml_path).getroot()
            for n in root_v.iter("node"):
                t = n.get("text", "").strip() or n.get("content-desc", "").strip()
                b = n.get("bounds", "").strip()
                
                if "네이버 가격비교" in t and b != "[0,0][0,0]" and "2347" not in b:
                    has_header = True
                    header_bounds = b
                
                if any(kw in t for kw in ["LG전자", "삼성전자", "베이직스", "갤럭시북", "그램", "NT750XGR", "14ZD95U"]):
                    if b != "[0,0][0,0]" and "2347" not in b:
                        visible_products.append(t[:40])
        except Exception:
            pass
            
    is_success = has_header or len(visible_products) >= 2
    return {
        "round": round_idx,
        "success": is_success,
        "elapsed_sec": t_elapsed,
        "header_bounds": header_bounds,
        "product_count": len(visible_products),
        "products_sample": visible_products[:3]
    }

for r in range(1, TOTAL_ROUNDS + 1):
    print(f"\n--- [Round {r:02d}/{TOTAL_ROUNDS:02d}] --------------------------------------------")
    print(f"[*] 1. TOP 원점 복귀 중...")
    return_to_top()
    
    print(f"[*] 2. '다른 사이트 더보기' 핀포인트 워프 실행 중...")
    res = execute_anchor_warp(r)
    results.append(res)
    
    status_str = "✅ 성공 (100% 안착)" if res["success"] else "❌ 실패"
    print(f"[✓] Round {r:02d} 결과: {status_str} | 소요시간: {res['elapsed_sec']}s | 가격비교 헤더: {res['header_bounds']} | 화면 상품수: {res['product_count']}개")
    if res["products_sample"]:
        print(f"    ↳ 안착 상품: {', '.join(res['products_sample'])}")
    time.sleep(1.0)

print("\n" + "=" * 80)
print(f"📊 [최종 10회 연속 테스트 종합 리포트]")
print("=" * 80)
success_cnt = sum(1 for r in results if r["success"])
avg_time = sum(r["elapsed_sec"] for r in results) / len(results) if results else 0

print(f"• 총 테스트 횟수: {TOTAL_ROUNDS}회")
print(f"• 성공 횟수: {success_cnt}회 / {TOTAL_ROUNDS}회")
print(f"• 성공률: {(success_cnt/TOTAL_ROUNDS)*100:.1f}%")
print(f"• 평균 워프 소요 시간: {avg_time:.2f}초")
print(f"• 증적 저장 디렉터리: {LOG_DIR}")
print("=" * 80)
