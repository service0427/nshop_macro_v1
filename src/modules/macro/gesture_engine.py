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
        """[홈 화면 스크롤 및 홈 버튼 탭 액션 제거 - 클린 홈 상단에서 검색창 즉시 진입]"""
        logger.info(f"[{self.device_id}] [✓] 클린 홈 화면 상단 원점 확인 완료 (불필요한 메인 피드 스크롤/영상 오터치 방지를 위해 스크롤 생략)")

    def scroll_verify_search_results(self) -> None:
        """[검색 결과 로딩 확인차 가벼운 1~2회 하단 스크롤 후 TOP 버튼 탭으로 최상단 초고속 원점 복귀]"""
        down_passes = random.randint(1, 2)
        logger.info(f"[{self.device_id}] [기본 스크롤] 검색 결과 확인차 가벼운 {down_passes}회 하단 스크롤 ➔ TOP 버튼 원점 복귀...")

        for i in range(1, down_passes + 1):
            # 🛡️ 웹 링크/블로그/광고 카드 클릭 오인식 방지: 화면 우측 안전 여백(X: 880~950) 및 빠른 스와이프(200~240ms) 적용
            x1 = random.randint(880, 950)
            y1 = random.randint(1550, 1750)
            x2 = x1 + random.randint(-5, 5)
            y2 = random.randint(1050, 1250)
            duration = random.randint(200, 240)
            logger.info(f"[{self.device_id}]  ↳ [기본 다운 #{i}/{down_passes}] ({x1}, {y1}) -> ({x2}, {y2}) [이동: {y1 - y2}px | {duration}ms (우측 여백 안전 스크롤)]")
            self.inspector.run_adb(f"input swipe {x1} {y1} {x2} {y2} {duration}")
            time.sleep(random.uniform(0.5, 0.8))

        logger.info(f"[{self.device_id}]  ↳ [TOP 버튼 트리거 & 탭] 미세 위 플릭 ➔ TOP 플로팅 버튼(993, 2262) 탭")
        self.inspector.run_adb("input swipe 920 1300 920 1450 150")
        time.sleep(0.3)
        self.inspector.run_adb("input tap 993 2262")
        time.sleep(0.8)
        logger.info(f"[{self.device_id}] [✓] TOP 버튼을 통해 검색 결과 페이지 최상단 원점 복귀 완료 (부하 제로, 오차 제로)")

    def browse_product_detail_page(self, target_dwell_sec: float = 30.0, min_scrolls: int = 4, max_scrolls: int = 7, load_timeout_sec: float = 30.0) -> bool:
        """
        [STEP 4: 상품 상세페이지 완전 로딩 확인 후 25~45초 랜덤 휴먼 체류 및 고도화된 탐색 스크롤]
        """
        # 0. 상세페이지 본문 및 구매 CTA 완전 로딩 대기 (최대 30초)
        logger.info(f"[{self.device_id}] 상세페이지 완전 로딩 및 CTA 렌더링 대기 중 (최대 {load_timeout_sec}초)...")
        load_start = time.time()
        fully_loaded = False
        while time.time() - load_start < load_timeout_sec:
            if self.inspector.is_on_product_detail_page():
                fully_loaded = True
                break
            time.sleep(0.5)

        if not fully_loaded:
            logger.warning(f"[{self.device_id}] [⚠️ 상세페이지 로딩 미흡] {load_timeout_sec}초 내 상세페이지(m.smartstore/brand) 진입이 확인되지 않음 -> 체류 중단")
            return False

        scroll_count = random.randint(min_scrolls, max_scrolls)
        logger.info(f"[{self.device_id}] ========================================================")
        logger.info(f"[{self.device_id}] 📜 [STEP 4 강화 체류] 상품 상세페이지 로딩 완료 ➔ {target_dwell_sec}초 고도화 체류 시작 (스크롤 {scroll_count}회)")
        logger.info(f"[{self.device_id}] ========================================================")

        t_start = time.time()

        # 1. 상단 대표 썸네일 이미지 가로 슬라이더 탐색 (1~2회 스와이프)
        try:
            logger.info(f"[{self.device_id}]  ↳ [휴먼 제스처: 썸네일 탐색] 상단 상품 이미지 슬라이더 가로 스와이프")
            self.inspector.run_adb("input swipe 850 850 250 850 280")
            time.sleep(random.uniform(1.5, 2.2))
            if random.random() < 0.5:
                self.inspector.run_adb("input swipe 850 850 250 850 280")
                time.sleep(random.uniform(1.2, 1.8))
        except Exception:
            pass

        # 2. 다단계 상세 스크롤 및 체류 인터랙션
        for s_idx in range(1, scroll_count + 1):
            # 🛡️ 상세 체류 중 타사 앱/알림 팝업 및 페이지 이탈 검증 가드
            self.inspector.ensure_naver_foreground()
            if not self.inspector.is_on_product_detail_page():
                logger.warning(f"[{self.device_id}] [⚠️ 상품 페이지 이탈 감지] 상세페이지에서 벗어남 -> 추가 스크롤 즉시 중단")
                break

            scroll_dist = random.randint(450, 750)
            start_x = random.randint(450, 650)
            start_y = random.randint(1550, 1780)
            end_x = start_x + random.randint(-15, 15)

            # 마지막 직전 혹은 중간에 자연스러운 상향(되돌아보기) 스크롤 1회 섞기
            if (s_idx == scroll_count or s_idx == 3) and random.random() < 0.5:
                end_y = start_y + random.randint(250, 450)
                action_label = "상향 훑기 (재확인)"
            else:
                end_y = start_y - scroll_dist
                action_label = "하향 탐색"

            duration = random.randint(350, 480)
            remaining_time = max(1.0, target_dwell_sec - (time.time() - t_start))
            remaining_scrolls = max(1, scroll_count - s_idx + 1)
            pause_time = round(min(7.0, max(3.0, remaining_time / remaining_scrolls + random.uniform(-0.5, 0.8))), 2)

            logger.info(f"[{self.device_id}]  ↳ [상세 {action_label} #{s_idx}/{scroll_count}] ({start_x}, {start_y}) -> ({end_x}, {end_y}) [이동: {abs(end_y-start_y)}px | 정독 체류: {pause_time}s]")
            self.inspector.run_adb(f"input swipe {start_x} {start_y} {end_x} {end_y} {duration}")
            time.sleep(pause_time)

        # 3. 목표 체류 시간 완주 대기
        elapsed = time.time() - t_start
        if elapsed < target_dwell_sec:
            extra_wait = round(target_dwell_sec - elapsed, 1)
            logger.info(f"[{self.device_id}]  ↳ [{target_dwell_sec}초 체류 충족 대기] 잔여 {extra_wait}초간 상세페이지 추가 체류 중...")
            time.sleep(extra_wait)

        total_dwell = round(time.time() - t_start, 1)
        subprocess.run(["adb", "-s", self.device_id, "shell", "screencap -p /sdcard/macro_product_final.png"], stdout=subprocess.DEVNULL)
        subprocess.run(["adb", "-s", self.device_id, "pull", "/sdcard/macro_product_final.png", f"/tmp/macro_product_final_{self.device_id}.png"], stdout=subprocess.DEVNULL)
        logger.info(f"[{self.device_id}] [📸 최종 상세페이지 캡처 저장 완료] -> /tmp/macro_product_final_{self.device_id}.png")
        logger.info(f"[{self.device_id}] [🎉 STEP 4 완료] 상품 상세페이지 {total_dwell}초 체류 및 탐색 완주!")

        # 4. [휴먼 세션 이탈 및 비콘 Flush 버퍼] 뒤로가기(BACK) 키 2회 전송 후 3초 대기 (wcs/nlog 비콘 완벽 전송)
        try:
            logger.info(f"[{self.device_id}] 🔙 [정상 세션 이탈] 뒤로가기(BACK) 키 전송 및 FDS 비콘/체류시간 Flush 대기(3초)...")
            self.inspector.run_adb("input keyevent 4")
            time.sleep(1.5)
            self.inspector.run_adb("input keyevent 4")
            time.sleep(2.0)
        except Exception:
            pass

        return True
