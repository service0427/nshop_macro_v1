#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
🔍 UI INSPECTOR & DYNAMIC COORDINATES DETECTOR (UIInspector)
========================================================================================
- 단말기 ADB 실행 및 XML UI 계층 구조 덤프/파싱
- 기기 해상도별 동적 좌표 추출 (검색창 안전 영역, 하단 홈 탭) 및 캐싱 관리
- 클릭 위치 시각화 디버깅 스크린샷 렌더링 및 /home/tech/nshop_macro_v1/click_logs 영구 보관
========================================================================================
"""

import os
import re
import json
import time
import shutil
import logging
import datetime
import subprocess
import xml.etree.ElementTree as ET
from typing import Dict, Any, Optional, Tuple
from src.config import DEVICE_SET_FILE, CLICK_LOGS_DIR, SCREENSHOT_DIR

logger = logging.getLogger("NaverMacroCore.UIInspector")


class UIInspector:
    def __init__(self, device_id: str):
        self.device_id = device_id
        os.makedirs(CLICK_LOGS_DIR, exist_ok=True)

    def run_adb(self, cmd: str, timeout_sec: int = 5) -> str:
        """기본 ADB shell 명령 실행"""
        try:
            full_cmd = ["adb", "-s", self.device_id, "shell", cmd]
            res = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout_sec)
            return res.stdout.strip()
        except Exception:
            return ""

    def run_adb_su(self, shell_cmd: str, timeout_sec: int = 5) -> str:
        """Root(su) 권한으로 단말기 셸 명령어 실행"""
        try:
            escaped_cmd = shell_cmd.replace('"', '\\"')
            cmd = ["adb", "-s", self.device_id, "shell", f'su -c "{escaped_cmd}"']
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
            return res.stdout.strip()
        except Exception:
            return ""

    def get_ui_tree(self, tmp_name: str = "ui_dump") -> Optional[ET.Element]:
        """UIAutomator XML을 덤프하고 파싱하여 ElementTree Root 반환 (버퍼 누락 방지)"""
        sdcard_file = f"/sdcard/{tmp_name}_{self.device_id}.xml"
        local_file = f"/tmp/{tmp_name}_{self.device_id}.xml"
        try:
            res = subprocess.run(
                ["adb", "-s", self.device_id, "shell", f"uiautomator dump {sdcard_file}"],
                capture_output=True, text=True, timeout=6
            )
            if res.returncode == 0:
                subprocess.run(
                    ["adb", "-s", self.device_id, "pull", sdcard_file, local_file],
                    capture_output=True, check=False, timeout=4
                )
                if os.path.exists(local_file):
                    tree = ET.parse(local_file)
                    return tree.getroot()
        except Exception:
            pass
        return None

    def get_device_config(self) -> dict:
        """device_set.json에서 해당 단말기 설정 조회"""
        if os.path.exists(DEVICE_SET_FILE):
            try:
                with open(DEVICE_SET_FILE, "r", encoding="utf-8") as f:
                    return json.load(f).get(self.device_id, {})
            except Exception:
                pass
        return {}

    def update_device_config(self, updates: dict):
        """device_set.json에 해당 단말기 설정 원자적 갱신"""
        data = {}
        if os.path.exists(DEVICE_SET_FILE):
            try:
                with open(DEVICE_SET_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        if self.device_id not in data:
            data[self.device_id] = {}
        data[self.device_id].update(updates)
        try:
            with open(DEVICE_SET_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get_home_tab_coords(self) -> Tuple[int, int]:
        """
        [하단 '홈' 탭 버튼 동적 좌표 추출 및 1회 캐싱]
        - 기기 해상도 기준 하단 네비게이션 바의 2번째 탭('홈' 버튼) 중심 좌표를 계산하여 캐싱
        """
        config = self.get_device_config()
        cached = config.get("home_tab_coords")
        if cached and isinstance(cached, list) and len(cached) == 2:
            if cached[0] >= 250:
                return tuple(cached)

        try:
            wm_size_out = self.run_adb("wm size")
            m_size = re.search(r"(\d+)x(\d+)", wm_size_out)
            if m_size:
                width, height = int(m_size.group(1)), int(m_size.group(2))
            else:
                width, height = 1080, 2400

            xml_str = self.run_adb("uiautomator dump /sdcard/home_nav.xml >/dev/null 2>&1 && cat /sdcard/home_nav.xml || true")
            nav_y = height - 40
            if "bottomNavigationView" in xml_str or "navigationContent" in xml_str:
                m_nav = re.search(r"resource-id=\"com\.nhn\.android\.search:id/(?:bottomNavigationView|navigationContent)\"[^>]*bounds=\"\[\d+,(\d+)\]\[\d+,(\d+)\]\"", xml_str)
                if m_nav:
                    y1, y2 = int(m_nav.group(1)), int(m_nav.group(2))
                    nav_y = (y1 + y2) // 2

            cx = int(width * 0.316)
            cy = nav_y

            logger.info(f"[{self.device_id}] [✓] 하단 '홈' 탭 버튼 정밀 좌표 확정: ({cx}, {cy})")
            self.update_device_config({"home_tab_coords": [cx, cy]})
            return (cx, cy)
        except Exception as e:
            logger.debug(f"[{self.device_id}] 하단 홈 탭 좌표 추출 예외: {e}")

        default_coords = (342, 2365)
        self.update_device_config({"home_tab_coords": list(default_coords)})
        return default_coords

    def get_search_bar_safe_bounds(self) -> Dict[str, int]:
        """
        [상단 검색창 안전 클릭 영역 추출 및 1회 캐싱]
        - 검색창 bounds 중 로고 및 우측 AI 아이콘을 배제한 안전 텍스트 영역 산출 및 캐싱
        """
        config = self.get_device_config()
        cached = config.get("search_bar_safe_bounds")
        if cached and isinstance(cached, dict) and "x_min" in cached:
            return cached

        try:
            xml_str = self.run_adb("uiautomator dump /sdcard/sb_chk.xml >/dev/null 2>&1 && cat /sdcard/sb_chk.xml || true")
            if xml_str and "<hierarchy" in xml_str:
                tree = ET.fromstring(xml_str[xml_str.find("<hierarchy"):])
                for elem in tree.iter("node"):
                    rid = elem.attrib.get("resource-id", "")
                    d = elem.attrib.get("content-desc", "")
                    b = elem.attrib.get("bounds", "")
                    if "searchBarRootView" in rid or "검색어 또는 URL 입력" in d:
                        m = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
                        if m:
                            x1, y1, x2, y2 = map(int, m.groups())
                            w = x2 - x1
                            h = y2 - y1
                            safe_bounds = {
                                "x_min": int(x1 + w * 0.25),
                                "x_max": int(x2 - w * 0.35),
                                "y_min": int(y1 + h * 0.20),
                                "y_max": int(y2 - h * 0.20),
                                "raw_bounds": [x1, y1, x2, y2]
                            }
                            logger.info(f"[{self.device_id}] [✓] 검색창 안전 영역 추출 완료: X({safe_bounds['x_min']}~{safe_bounds['x_max']}), Y({safe_bounds['y_min']}~{safe_bounds['y_max']})")
                            self.update_device_config({"search_bar_safe_bounds": safe_bounds})
                            return safe_bounds
        except Exception as e:
            logger.debug(f"[{self.device_id}] 검색창 영역 파싱 예외: {e}")

        default_safe = {"x_min": 300, "x_max": 680, "y_min": 480, "y_max": 580, "raw_bounds": [60, 438, 1020, 618]}
        self.update_device_config({"search_bar_safe_bounds": default_safe})
        return default_safe

    def draw_and_save_click_debug_image(self, click_x: int, click_y: int, target_mid: Optional[str] = None, extra_info: Optional[str] = None) -> str:
        """
        [클릭 직전 화면 캡처 및 타겟 좌표 시각화 디버깅 스크린샷 저장]
        - /home/tech/nshop_macro_v1/click_logs/ 폴더에 타임스탬프와 함께 영구 저장
        """
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        mid_tag = f"_mid_{target_mid}" if target_mid else ""
        archive_path = os.path.join(CLICK_LOGS_DIR, f"click_{now_str}_{self.device_id}{mid_tag}.png")
        local_raw = f"/tmp/macro_pre_click_{self.device_id}.png"
        local_out = f"/tmp/macro_click_debug_{self.device_id}.png"

        try:
            subprocess.run(["adb", "-s", self.device_id, "shell", "screencap -p /sdcard/macro_pre_click.png"], stdout=subprocess.DEVNULL)
            subprocess.run(["adb", "-s", self.device_id, "pull", "/sdcard/macro_pre_click.png", local_raw], stdout=subprocess.DEVNULL)
            if os.path.exists(local_raw):
                from PIL import Image, ImageDraw, ImageFont
                img = Image.open(local_raw).convert("RGBA")
                draw = ImageDraw.Draw(img)
                cx, cy = click_x, click_y
                r = 30
                # 붉은색 타겟 조준선 및 원형 마커 표시
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline="red", width=6)
                draw.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill="red")
                draw.line((cx - 65, cy, cx + 65, cy), fill="red", width=4)
                draw.line((cx, cy - 65, cx, cy + 65), fill="red", width=4)

                try:
                    font = ImageFont.load_default(size=26)
                except Exception:
                    font = None

                banner_text = f"TAP: ({cx}, {cy}) | MID: {target_mid or 'N/A'}"
                draw.rectangle((cx + 40, cy - 35, cx + 450, cy + 20), fill="black", outline="red", width=2)
                draw.text((cx + 50, cy - 30), banner_text, fill="yellow", font=font)

                # /tmp 및 click_logs 양쪽에 저장
                img.save(local_out)
                img.save(archive_path)
                logger.info(f"[{self.device_id}] [📸 클릭 위치 시각화 스샷 저장 완료] -> {archive_path}")
                return archive_path
        except Exception as e:
            logger.warning(f"[{self.device_id}] [!] 클릭 시각화 스샷 저장 실패: {e}")
        return ""

    def crop_and_save_target_screenshot(
        self,
        target_bounds: Tuple[int, int, int, int],
        target_mid: str,
        keyword: Optional[str] = None,
        click_coords: Optional[Tuple[int, int]] = None
    ) -> str:
        """
        [타겟 상품 발견 시 해당 상품 영역만 크롭하여 저장]
        - 저장 경로: logs/target_screenshot/{YYYY-MM-DD}/{HHMMSS}_{mid}_{keyword}_{device_id}.png
        """
        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")
        target_dir = os.path.join(SCREENSHOT_DIR, today_str)
        os.makedirs(target_dir, exist_ok=True)

        safe_kw = re.sub(r'[\s/\\:*?"<>|]+', '_', (keyword or "UNKNOWN").strip()).strip('_')
        filename = f"{time_str}_{target_mid}_{safe_kw}_{self.device_id}.png"
        archive_path = os.path.join(target_dir, filename)
        local_raw = f"/tmp/macro_screen_target_{self.device_id}.png"

        try:
            subprocess.run(["adb", "-s", self.device_id, "shell", "screencap -p /sdcard/target_screen.png"], stdout=subprocess.DEVNULL)
            subprocess.run(["adb", "-s", self.device_id, "pull", "/sdcard/target_screen.png", local_raw], stdout=subprocess.DEVNULL)

            if os.path.exists(local_raw):
                from PIL import Image, ImageDraw, ImageFont
                img = Image.open(local_raw).convert("RGBA")
                w_img, h_img = img.size

                x1, y1, x2, y2 = target_bounds
                # 유효 좌표 범위 클램핑 (상하좌우 10px 여백 포함)
                pad = 10
                crop_x1 = max(0, min(x1 - pad, w_img - 1))
                crop_y1 = max(0, min(y1 - pad, h_img - 1))
                crop_x2 = max(0, min(x2 + pad, w_img))
                crop_y2 = max(0, min(y2 + pad, h_img))

                if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
                    crop_x1, crop_y1, crop_x2, crop_y2 = max(0, x1), max(0, y1), min(w_img, x2), min(h_img, y2)

                draw = ImageDraw.Draw(img)
                # 타겟 상품 감지 박스 (초록색 외곽선)
                draw.rectangle((x1, y1, x2, y2), outline="#00FF00", width=4)

                # 클릭 좌표가 전달된 경우 타겟 포인트 표시 (빨간 조준선)
                if click_coords:
                    cx, cy = click_coords
                    r = 18
                    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline="red", width=4)
                    draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill="red")
                    draw.line((cx - 35, cy, cx + 35, cy), fill="red", width=3)
                    draw.line((cx, cy - 35, cx, cy + 35), fill="red", width=3)

                # 타겟 상품 영역만 크롭
                cropped = img.crop((crop_x1, crop_y1, crop_x2, crop_y2))
                cropped.save(archive_path)
                logger.info(f"[{self.device_id}] [📸 타겟 상품 영역 크롭 저장 완료] [{crop_x1},{crop_y1}][{crop_x2},{crop_y2}] -> {archive_path}")
                return archive_path
        except Exception as e:
            logger.warning(f"[{self.device_id}] [!] 타겟 상품 영역 크롭 저장 실패: {e}")
        return ""

    def save_detail_page_screenshot(
        self,
        target_mid: str,
        keyword: Optional[str] = None
    ) -> str:
        """
        [상세페이지 진입 성공 시 첫 화면 전체 캡처 저장]
        - 저장 경로: logs/target_screenshot/{YYYY-MM-DD}/{HHMMSS}_{mid}_{keyword}_{device_id}_click.png
        """
        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")
        target_dir = os.path.join(SCREENSHOT_DIR, today_str)
        os.makedirs(target_dir, exist_ok=True)

        safe_kw = re.sub(r'[\s/\\:*?"<>|]+', '_', (keyword or "UNKNOWN").strip()).strip('_')
        filename = f"{time_str}_{target_mid}_{safe_kw}_{self.device_id}_click.png"
        archive_path = os.path.join(target_dir, filename)

        try:
            subprocess.run(["adb", "-s", self.device_id, "shell", "screencap -p /sdcard/detail_click.png"], stdout=subprocess.DEVNULL)
            subprocess.run(["adb", "-s", self.device_id, "pull", "/sdcard/detail_click.png", archive_path], stdout=subprocess.DEVNULL)
            if os.path.exists(archive_path):
                logger.info(f"[{self.device_id}] [📸 상세페이지 랜딩 스크린샷 저장 완료] -> {archive_path}")
                return archive_path
        except Exception as e:
            logger.warning(f"[{self.device_id}] [!] 상세페이지 랜딩 스크린샷 저장 실패: {e}")
        return ""
