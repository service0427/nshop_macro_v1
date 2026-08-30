#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
🖐️ HUMAN-LIKE GESTURE & ACTION ENGINE (GestureEngine)
========================================================================================
- 권한 일괄 부여 및 온보딩/튜토리얼 스킵 주입
- 인간적인 터치/스크롤 제스처 시뮬레이션 (랜덤 패딩, 가변 스피드)
- TOP 버튼 초고속 원점 복귀 제어
- 상세페이지 30초 자연스러운 체류(Dwell) 및 다단계 스크롤
========================================================================================
"""

import os
import time
import random
import logging
import subprocess
from typing import Tuple

from src.config import NAVER_PKG
from src.modules.macro.ui_inspector import UIInspector

logger = logging.getLogger("NaverMacroCore.GestureEngine")

class GestureEngine:
    """
    인간적인 터치, 가변 스크롤 및 상품 상세페이지 체류 제스처 전담 엔진
    """
    def __init__(self, device_id: str, inspector: UIInspector):
        self.device_id = device_id
        self.inspector = inspector

    def tap_search_bar_random(self) -> Tuple[int, int]:
        """[검색창 안전 영역 내 랜덤 좌표 탭]"""
        bounds = self.inspector.get_search_bar_safe_bounds()
        rx = random.randint(bounds["x_min"], bounds["x_max"])
        ry = random.randint(bounds["y_min"], bounds["y_max"])
        logger.info(f"[{self.device_id}] 검색창 안전 영역 내 랜덤 탭 실행 -> ({rx}, {ry}) [안전영역: X:{bounds['x_min']}~{bounds['x_max']}, Y:{bounds['y_min']}~{bounds['y_max']}]")
        self.inspector.run_adb(f"input tap {rx} {ry}")
        return (rx, ry)

    def warm_up_home_scroll(self):
        """[홈 화면 랜덤 웜업 스크롤 ➔ 하단 '홈' 탭 1회 탭으로 최상단 새로고침 복귀]"""
        logger.info(f"[{self.device_id}] 홈 화면 랜덤 웜업 스크롤 수행...")
        scroll_count = random.randint(1, 2)
        for _ in range(scroll_count):
            start_y = random.randint(1550, 1750)
            end_y = random.randint(700, 950)
            duration = random.randint(250, 350)
            self.inspector.run_adb(f"input swipe 540 {start_y} 540 {end_y} {duration}")
            time.sleep(random.uniform(0.7, 1.2))

        hx, hy = self.inspector.get_home_tab_coords()
        logger.info(f"[{self.device_id}] 하단 '홈' 탭 버튼({hx}, {hy}) 탭 ➔ 최상단 새로고침 및 원점 복귀...")
        self.inspector.run_adb(f"input tap {hx} {hy}")
        time.sleep(1.2)
        logger.info(f"[{self.device_id}] [✓] 홈 화면 최상단 원점 복귀 완료 (검색 준비 완료)")

    def scroll_verify_search_results(self) -> None:
        """[검색 결과 로딩 확인차 가벼운 1~2회 하단 스크롤 후 TOP 버튼 탭으로 최상단 초고속 원점 복귀]"""
        down_passes = random.randint(1, 2)
        logger.info(f"[{self.device_id}] [기본 스크롤] 검색 결과 확인차 가벼운 {down_passes}회 하단 스크롤 ➔ TOP 버튼 원점 복귀...")

        for i in range(1, down_passes + 1):
            x1 = random.randint(480, 600)
            y1 = random.randint(1550, 1750)
            x2 = x1 + random.randint(-10, 10)
            y2 = random.randint(1100, 1300)
            duration = random.randint(320, 420)
            logger.info(f"[{self.device_id}]  ↳ [기본 다운 #{i}/{down_passes}] ({x1}, {y1}) -> ({x2}, {y2}) [이동: {y1 - y2}px | {duration}ms]")
            self.inspector.run_adb(f"input swipe {x1} {y1} {x2} {y2} {duration}")
            time.sleep(random.uniform(0.6, 0.9))

        logger.info(f"[{self.device_id}]  ↳ [TOP 버튼 트리거 & 탭] 미세 위 플릭 ➔ TOP 플로팅 버튼(993, 2262) 탭")
        self.inspector.run_adb("input swipe 500 1300 500 1450 150")
        time.sleep(0.3)
        self.inspector.run_adb("input tap 993 2262")
        time.sleep(0.8)
        logger.info(f"[{self.device_id}] [✓] TOP 버튼을 통해 검색 결과 페이지 최상단 원점 복귀 완료 (부하 제로, 오차 제로)")

    def browse_product_detail_page(self, target_dwell_sec: float = 30.0, min_scrolls: int = 4, max_scrolls: int = 7) -> bool:
        """
        [STEP 4: 상품 상세페이지 30초 자연스러운 체류(Dwell) 및 다단계 탐색 스크롤]
        - 상세페이지에서 30초간 실제 사용자 패턴으로 체류 및 스크롤
        """
        scroll_count = random.randint(min_scrolls, max_scrolls)
        logger.info(f"[{self.device_id}] ========================================================")
        logger.info(f"[{self.device_id}] 📜 [STEP 4] 상품 상세페이지 {target_dwell_sec}초 체류 및 랜덤 {scroll_count}회 다단계 탐색 스크롤")
        logger.info(f"[{self.device_id}] ========================================================")

        t_start = time.time()
        for s_idx in range(1, scroll_count + 1):
            scroll_dist = random.randint(480, 750)
            start_x = random.randint(450, 650)
            start_y = random.randint(1550, 1780)
            end_x = start_x + random.randint(-15, 15)

            if s_idx == scroll_count and random.random() < 0.6:
                end_y = start_y + random.randint(300, 500)
                action_label = "상향 훑기"
            else:
                end_y = start_y - scroll_dist
                action_label = "하향 탐색"

            duration = random.randint(380, 480)
            remaining_time = max(1.0, target_dwell_sec - (time.time() - t_start))
            remaining_scrolls = max(1, scroll_count - s_idx + 1)
            pause_time = round(min(6.5, max(2.5, remaining_time / remaining_scrolls + random.uniform(-0.6, 0.6))), 2)

            logger.info(f"[{self.device_id}]  ↳ [상세 {action_label} #{s_idx}/{scroll_count}] ({start_x}, {start_y}) -> ({end_x}, {end_y}) [이동: {abs(end_y-start_y)}px | 체류 대기: {pause_time}s]")
            self.inspector.run_adb(f"input swipe {start_x} {start_y} {end_x} {end_y} {duration}")
            time.sleep(pause_time)

        elapsed = time.time() - t_start
        if elapsed < target_dwell_sec:
            extra_wait = round(target_dwell_sec - elapsed, 1)
            logger.info(f"[{self.device_id}]  ↳ [30초 체류 충족 대기] 잔여 {extra_wait}초간 상세페이지 추가 체류 중...")
            time.sleep(extra_wait)

        total_dwell = round(time.time() - t_start, 1)
        subprocess.run(["adb", "-s", self.device_id, "shell", "screencap -p /sdcard/macro_product_final.png"], stdout=subprocess.DEVNULL)
        subprocess.run(["adb", "-s", self.device_id, "pull", "/sdcard/macro_product_final.png", f"/tmp/macro_product_final_{self.device_id}.png"], stdout=subprocess.DEVNULL)
        logger.info(f"[{self.device_id}] [📸 최종 상세페이지 캡처 저장 완료] -> /tmp/macro_product_final_{self.device_id}.png")
        logger.info(f"[{self.device_id}] [🎉 STEP 4 완료] 상품 상세페이지 {total_dwell}초 체류 및 탐색 스크롤 완주!")
        return True
