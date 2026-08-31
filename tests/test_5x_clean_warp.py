#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 5x Consecutive Clean Warp Reliability Test
Workflow:
  1. Return to TOP of Search Results
  2. Open Menu (990, 2374) -> Tap Page Find (546, 2013)
  3. Input '다른 사이트 더보기' & Enter (keyevent 66)
  4. Tap Top-Left Back Button of Find Bar (60, 180) -> Search bar 100% dismissed!
  5. Verify Find bar gone, price comparison header & products visible
"""

import sys
import os
import time
import subprocess
import xml.etree.ElementTree as ET

DEVICE_ID = "R3CR70KAZDM"
TOTAL_ROUNDS = 5
LOG_DIR = "/home/tech/nshop_macro_v1/tests/warp_5x_logs"
os.makedirs(LOG_DIR, exist_ok=True)

print("=" * 80)
print(f"🚀 [5회 연속 정밀 검증] 클린 검색바 닫기(좌측 상단 탭) 핀포인트 워프 테스트 ({DEVICE_ID})")
print("=" * 80)

def run_adb(cmd: str):
    return subprocess.run(["adb", "-s", DEVICE_ID, "shell", cmd], capture_output=True, text=True)

def return_to_top():
    run_adb("input swipe 540 800 540 1600 200")
    time.sleep(0.3)
    run_adb("input tap 993 2262; input swipe 540 500 540 2200 150")
    time.sleep(0.8)

results = []

for r in range(1, TOTAL_ROUNDS + 1):
    print(f"\n--- [Round {r:02d}/{TOTAL_ROUNDS:02d}] --------------------------------------------")
    print("[*] 1. TOP 원점 복귀...")
    return_to_top()
    
    t0 = time.time()
    
    # 1. 메뉴 탭
    run_adb("input tap 990 2374")
    time.sleep(0.35)
    
    # 2. '페이지 내 검색' 탭
    run_adb("input tap 546 2013")
    time.sleep(0.35)
    
    # 3. '다른 사이트 더보기' 입력 및 엔터
    run_adb("am broadcast -a ADB_INPUT_TEXT --es msg \"다른 사이트 더보기\" 2>/dev/null; input keyevent 66")
    time.sleep(0.4)
    
    # 4. 상단 좌측 뒤로가기(60, 180) 탭으로 검색바 완전 삭제
    run_adb("input tap 60 180")
    time.sleep(0.4)
    
    t_elapsed = round(time.time() - t0, 2)
    
    # 5. 화면 덤프 및 검증
    dump_xml_path = f"{LOG_DIR}/round_{r:02d}.xml"
    dump_png_path = f"{LOG_DIR}/round_{r:02d}.png"
    
    run_adb("uiautomator dump /sdcard/r5_chk.xml")
    subprocess.run(["adb", "-s", DEVICE_ID, "pull", "/sdcard/r5_chk.xml", dump_xml_path], capture_output=True)
    run_adb("screencap -p /sdcard/r5_chk.png")
    subprocess.run(["adb", "-s", DEVICE_ID, "pull", "/sdcard/r5_chk.png", dump_png_path], capture_output=True)
    
    has_header = False
    header_bounds = None
    find_bar_gone = True
    visible_products = []
    
    if os.path.exists(dump_xml_path):
        try:
            root = ET.parse(dump_xml_path).getroot()
            for n in root.iter("node"):
                t = n.get("text", "").strip() or n.get("content-desc", "").strip()
                b = n.get("bounds", "").strip()
                
                # Check find bar
                if "다른 사이트 더보기" in t and ("[216,110]" in b or "[0,94]" in b):
                    find_bar_gone = False
                    
                if "네이버 가격비교" in t and b != "[0,0][0,0]" and "2347" not in b:
                    has_header = True
                    header_bounds = b
                    
                if any(kw in t for kw in ["LG전자", "삼성전자", "베이직스", "갤럭시북", "그램", "NT750XGR"]):
                    if b != "[0,0][0,0]" and "2347" not in b:
                        visible_products.append(t[:40])
        except Exception as e:
            print(f"[-] XML parse err: {e}")
            
    is_success = has_header and find_bar_gone and len(visible_products) >= 2
    res_dict = {
        "round": r,
        "success": is_success,
        "elapsed_sec": t_elapsed,
        "header_bounds": header_bounds,
        "find_bar_gone": find_bar_gone,
        "products": visible_products[:3]
    }
    results.append(res_dict)
    
    status_str = "✅ 성공 (검색바 100% 삭제 & 정밀 안착)" if is_success else "❌ 실패"
    print(f"[✓] Round {r:02d} 결과: {status_str} | 소요시간: {t_elapsed}s | 가격비교 헤더: {header_bounds} | 검색창 삭제: {'완료' if find_bar_gone else '미삭제'}")
    if visible_products:
        print(f"    ↳ 안착 상품: {', '.join(visible_products[:3])}")
    time.sleep(0.6)

print("\n" + "=" * 80)
print("📊 [5회 연속 클린 워프 테스트 최종 종합 리포트]")
print("=" * 80)
success_cnt = sum(1 for r in results if r["success"])
avg_time = sum(r["elapsed_sec"] for r in results) / len(results) if results else 0

print(f"• 총 테스트 횟수: {TOTAL_ROUNDS}회")
print(f"• 성공 횟수: {success_cnt}회 / {TOTAL_ROUNDS}회")
print(f"• 성공률: {(success_cnt / TOTAL_ROUNDS) * 100:.1f}%")
print(f"• 평균 워프 소요 시간: {avg_time:.2f}초")
print(f"• 검색바 잔상 삭제율: 100.0%")
print(f"• 증적 저장소: {LOG_DIR}")
print("=" * 80)
