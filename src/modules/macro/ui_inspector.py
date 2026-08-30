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
from src.config import (
    DEVICE_SET_FILE, CLICK_LOGS_DIR, CLICK_BEFORE_DIR, CLICK_AFTER_DIR, SCREENSHOT_DIR, UNEXPOSED_DUMPS_DIR
)

logger = logging.getLogger("NaverMacroCore.UIInspector")


def prune_dir(dir_path: str, max_files: int = 200):
    """지정된 디렉터리의 전체 파일이 max_files(200개)를 넘지 않도록 가장 오래된 파일 자동 회전 삭제 (FIFO)"""
    try:
        if not os.path.exists(dir_path):
            return
        files = sorted(
            [os.path.join(dir_path, f) for f in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, f))],
            key=os.path.getmtime
        )
        if len(files) > max_files:
            for old_file in files[: len(files) - max_files]:
                try:
                    os.remove(old_file)
                except Exception:
                    pass
    except Exception:
        pass


def prune_image_dir(dir_path: str, max_files: int = 200):
    """호환성을 위한 prune_dir 별칭"""
    prune_dir(dir_path, max_files=max_files)


class UIInspector:
    def __init__(self, device_id: str):
        self.device_id = device_id
        os.makedirs(CLICK_BEFORE_DIR, exist_ok=True)
        os.makedirs(CLICK_AFTER_DIR, exist_ok=True)
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    def run_adb(self, cmd: str, timeout_sec: int = 3) -> str:
        """기본 ADB shell 명령 실행"""
        try:
            full_cmd = ["adb", "-s", self.device_id, "shell", cmd]
            res = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout_sec)
            return res.stdout.strip()
        except Exception:
            return ""

    def run_adb_su(self, shell_cmd: str, timeout_sec: int = 3) -> str:
        """Root(su) 권한으로 단말기 셸 명령어 실행"""
        try:
            escaped_cmd = shell_cmd.replace('"', '\\"')
            cmd = ["adb", "-s", self.device_id, "shell", f'su -c "{escaped_cmd}"']
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
            return res.stdout.strip()
        except Exception:
            return ""

    def is_naver_foreground(self) -> bool:
        """현재 화면의 최상위 포커스 윈도우/앱이 네이버 앱인지 검사"""
        focus_str = self.run_adb("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp|topResumedActivity'", timeout_sec=2)
        if "com.nhn.android.search" in focus_str:
            return True
        # 삼성 키보드 등 IME 입력 중일 때는 네이버 앱 위의 자식 윈도우이므로 True 판정
        if any(ime in focus_str for ime in ["inputmethod", "InputMethod", "ADBKeyboard"]):
            return True
        return False

    def ensure_naver_foreground(self) -> bool:
        """네이버 앱이 포그라운드가 아닐 경우 즉시 전면으로 복귀"""
        if not self.is_naver_foreground():
            logger.warning(f"[{self.device_id}] [⚠️ 포그라운드 이탈 감지] 타사 앱/런처 감지 -> 네이버 앱 포그라운드 강제 복귀 실행...")
            self.run_adb("am start -n com.nhn.android.search/.ui.pages.SearchHomePage", timeout_sec=3)
            time.sleep(1.0)
            return self.is_naver_foreground()
        return True

    def get_ui_tree(self, tmp_name: str = "ui_dump") -> Optional[ET.Element]:
        """UIAutomator XML을 덤프하고 파싱하여 ElementTree Root 반환"""
        try:
            sdcard_path = f"/sdcard/{tmp_name}.xml"
            self.run_adb(f"uiautomator dump {sdcard_path}", timeout_sec=8.0)
            xml_str = self.run_adb(f"cat {sdcard_path}", timeout_sec=5.0)
            if not xml_str or "<hierarchy" not in xml_str:
                xml_str = self.run_adb("cat /sdcard/window_dump.xml", timeout_sec=5.0)
            if xml_str and "<hierarchy" in xml_str:
                xml_clean = xml_str[xml_str.find("<hierarchy"):]
                return ET.fromstring(xml_clean)
        except Exception as e:
            logger.warning(f"[{self.device_id}] get_ui_tree 파싱 실패: {e}")
        return None

    # 단말기별 UI 액션 연속 실패 카운터 (메모리 내 관리, 오버헤드 0%)
    _failure_counters: Dict[str, Dict[str, int]] = {}

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

    def record_action_failure(self, action_name: str) -> int:
        """특정 UI 액션(search_bar, home_tab) 연속 실패 카운트 증가 및 반환"""
        if self.device_id not in UIInspector._failure_counters:
            UIInspector._failure_counters[self.device_id] = {}
        cnt = UIInspector._failure_counters[self.device_id].get(action_name, 0) + 1
        UIInspector._failure_counters[self.device_id][action_name] = cnt
        return cnt

    def record_action_success(self, action_name: str):
        """특정 UI 액션 성공 시 실패 카운트 0으로 초기화"""
        if self.device_id in UIInspector._failure_counters:
            UIInspector._failure_counters[self.device_id][action_name] = 0

    def invalidate_cache(self, cache_key: str):
        """device_set.json에서 특정 캐시 키를 원자적으로 제거하여 자가복구 트리거"""
        if os.path.exists(DEVICE_SET_FILE):
            try:
                with open(DEVICE_SET_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if self.device_id in data and cache_key in data[self.device_id]:
                    del data[self.device_id][cache_key]
                    with open(DEVICE_SET_FILE, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    logger.warning(f"[{self.device_id}] 🧹 [캐시 무효화] '{cache_key}' 캐시 삭제 완료 (다음 호출 시 실시간 재계측)")
            except Exception as e:
                logger.debug(f"[{self.device_id}] 캐시 무효화 예외: {e}")

    def get_home_tab_coords(self, force_rescan: bool = False) -> Tuple[int, int]:
        """
        [하단 '홈' 탭 버튼 동적 좌표 추출 및 1회 캐싱 (자가복구 지원)]
        - 기기 해상도 기준 하단 네비게이션 바의 2번째 탭('홈' 버튼) 중심 좌표를 계산하여 캐싱
        """
        if not force_rescan:
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

    def get_search_bar_safe_bounds(self, force_rescan: bool = False) -> Dict[str, int]:
        """
        [상단 검색창 안전 클릭 영역 추출 및 1회 캐싱 (자가복구 지원)]
        - 검색창 bounds 중 로고 및 우측 AI 아이콘을 배제한 안전 텍스트 영역 산출 및 캐싱
        """
        if not force_rescan:
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

    def draw_and_save_click_debug_image(
        self,
        click_x: int,
        click_y: int,
        target_mid: Optional[str] = None,
        extra_info: Optional[str] = None,
        stage: str = "click_before"
    ) -> str:
        """
        [클릭/탐색 직전 화면 캡처 및 타겟 좌표 시각화 디버깅 스크린샷 저장]
        - 저장 경로: logs/click_logs/click_before/click_before_{YYYYMMDD_HHMMSS}_{device_id}_mid_{mid}.png
        - 200장 초과 시 FIFO 자동 회전 삭제
        """
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        mid_tag = f"_mid_{target_mid}" if target_mid else ""
        archive_path = os.path.join(CLICK_BEFORE_DIR, f"{stage}_{now_str}_{self.device_id}{mid_tag}.png")
        local_raw = f"/tmp/macro_pre_click_{self.device_id}.png"
        local_out = f"/tmp/macro_click_debug_{self.device_id}.png"

        try:
            with open(local_raw, "wb") as f:
                subprocess.run(["adb", "-s", self.device_id, "exec-out", "screencap", "-p"], stdout=f, timeout=5)

            if os.path.exists(local_raw) and os.path.getsize(local_raw) > 1000:
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

                banner_text = f"TARGET: ({cx}, {cy}) | MID: {target_mid or 'N/A'}"
                draw.rectangle((cx + 40, cy - 35, cx + 450, cy + 20), fill="black", outline="red", width=2)
                draw.text((cx + 50, cy - 30), banner_text, fill="yellow", font=font)

                # /tmp 및 click_logs/click_before 양쪽에 저장
                img.save(local_out)
                img.save(archive_path)
                logger.info(f"[{self.device_id}] [📸 클릭/탐색 직전 시각화 스샷 저장 완료] -> {archive_path}")
                prune_image_dir(CLICK_BEFORE_DIR, max_files=200)
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
        [타겟 상품 발견 시 해당 상품 영역만 크롭하여 저장 (일자별 폴더 없이 통으로 저장)]
        - 저장 경로: logs/target_screenshot/{HHMMSS}_{mid}_{keyword}_{device_id}.png
        - 200장 초과 시 FIFO 자동 회전 삭제
        """
        now = datetime.datetime.now()
        time_str = now.strftime("%Y%m%d_%H%M%S")

        safe_kw = re.sub(r'[\s/\\:*?"<>|]+', '_', (keyword or "UNKNOWN").strip()).strip('_')
        filename = f"{time_str}_{target_mid}_{safe_kw}_{self.device_id}.png"
        archive_path = os.path.join(SCREENSHOT_DIR, filename)
        local_raw = f"/tmp/macro_screen_target_{self.device_id}.png"

        try:
            with open(local_raw, "wb") as f:
                subprocess.run(["adb", "-s", self.device_id, "exec-out", "screencap", "-p"], stdout=f, timeout=5)

            if os.path.exists(local_raw) and os.path.getsize(local_raw) > 1000:
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
                prune_image_dir(SCREENSHOT_DIR, max_files=200)
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
        [상세페이지 진입 성공 시 랜딩 화면 전체 캡처 저장]
        - 저장 경로: logs/click_logs/click_after/click_after_{YYYYMMDD_HHMMSS}_{mid}_{keyword}_{device_id}.png
        - 200장 초과 시 FIFO 자동 회전 삭제
        """
        now = datetime.datetime.now()
        time_str = now.strftime("%Y%m%d_%H%M%S")

        safe_kw = re.sub(r'[\s/\\:*?"<>|]+', '_', (keyword or "UNKNOWN").strip()).strip('_')
        filename = f"click_after_{time_str}_{target_mid}_{safe_kw}_{self.device_id}.png"
        archive_path = os.path.join(CLICK_AFTER_DIR, filename)

        try:
            with open(archive_path, "wb") as f:
                subprocess.run(["adb", "-s", self.device_id, "exec-out", "screencap", "-p"], stdout=f, timeout=5)
            if os.path.exists(archive_path) and os.path.getsize(archive_path) > 1000:
                logger.info(f"[{self.device_id}] [📸 상세페이지 랜딩 스크린샷 저장 완료] -> {archive_path}")
                prune_image_dir(CLICK_AFTER_DIR, max_files=200)
                return archive_path
        except Exception as e:
            logger.warning(f"[{self.device_id}] [!] 상세페이지 랜딩 스크린샷 저장 실패: {e}")
        return ""

    def save_unexposed_dump(
        self,
        target_mid: str,
        keyword: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        [타겟 상품 미노출(is_exposed=False) 시 사후 분석을 위해 전체 UI XML 덤프 및 화면 캡처 저장]
        - 저장 경로: logs/unexposed_dumps/unexposed_{YYYYMMDD_HHMMSS}_{mid}_{keyword}_{device_id}.xml / .png
        - 200개 초과 시 FIFO 자동 회전 삭제
        """
        now = datetime.datetime.now()
        time_str = now.strftime("%Y%m%d_%H%M%S")
        safe_kw = re.sub(r'[\s/\\:*?"<>|]+', '_', (keyword or "UNKNOWN").strip()).strip('_')
        base_name = f"unexposed_{time_str}_{target_mid}_{safe_kw}_{self.device_id}"
        xml_path = os.path.join(UNEXPOSED_DUMPS_DIR, f"{base_name}.xml")
        png_path = os.path.join(UNEXPOSED_DUMPS_DIR, f"{base_name}.png")

        try:
            # 1. XML 덤프 저장
            self.run_adb("uiautomator dump /sdcard/unexp_dump.xml", timeout_sec=8.0)
            xml_str = self.run_adb("cat /sdcard/unexp_dump.xml", timeout_sec=5.0)
            if xml_str and "<hierarchy" in xml_str:
                xml_clean = xml_str[xml_str.find("<hierarchy"):]
                with open(xml_path, "w", encoding="utf-8") as f:
                    f.write(xml_clean)
                logger.info(f"[{self.device_id}] [📝 미노출 UI XML 덤프 저장 완료] -> {xml_path}")

            # 2. 화면 전체 스크린샷 캡처
            with open(png_path, "wb") as f:
                subprocess.run(["adb", "-s", self.device_id, "exec-out", "screencap", "-p"], stdout=f, timeout=5)
            if os.path.exists(png_path) and os.path.getsize(png_path) > 1000:
                logger.info(f"[{self.device_id}] [📸 미노출 전체 화면 캡처 저장 완료] -> {png_path}")

            # 3. 자동 로테이션 정리 (최대 200개 유지, 초과 시 FIFO 자동 삭제)
            prune_dir(UNEXPOSED_DUMPS_DIR, max_files=200)
            return (xml_path, png_path)
        except Exception as e:
            logger.warning(f"[{self.device_id}] [!] 미노출 덤프/캡처 저장 실패: {e}")
        return ("", "")
