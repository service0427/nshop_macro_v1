#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
📸 MACRO IMAGE & SCREENSHOT ARCHIVER (MacroImageArchiver)
(src/modules/macro/image_archiver.py)
========================================================================================
- 기능:
    1. 클릭/탐색 직전 타겟 좌표 시각화(붉은 십자선/박스) 디버그 이미지 렌더링 및 저장
    2. 타겟 상품 영역 정밀 크롭(Crop) 및 타겟 증적 보존
    3. 상세페이지 랜딩 및 1화면 스크롤 2차 증적 스크린샷 보존
    4. 미노출/노출 성공 시 UI XML 덤프 및 전체 화면 캡처 영구 보관
    5. 30일 보존 정책(prune_dir_by_age) 자동 적용

----------------------------------------------------------------------------------------
[수정 및 변경 이력 (Revision History)]
----------------------------------------------------------------------------------------
- 2026-09-05:
    * [UIInspector 분리 및 모듈화] UIInspector에서 비대해진 이미지 후처리 및 아카이빙 로직을
      단일 책임 원칙(SRP)에 따라 독립 모듈로 분리 리팩토링.
    * Pillow 임포트 최적화 및 들여쓰기/가독성 정제.
========================================================================================
"""

import os
import re
import time
import logging
import datetime
import subprocess
from typing import Optional, Tuple, Callable
from PIL import Image, ImageDraw, ImageFont

from src.config import (
    CLICK_BEFORE_DIR, CLICK_AFTER_DIR, SCREENSHOT_DIR,
    UNEXPOSED_DUMPS_DIR, EXPOSED_DUMPS_DIR,
    get_dated_dir, prune_dir_by_age, LOG_RETENTION_DAYS
)

logger = logging.getLogger("NaverMacroCore.ImageArchiver")


class MacroImageArchiver:
    """스크린샷 캡처, 주석 드로잉, 이미지 크롭 및 증적 아카이빙 전담 클래스"""

    def __init__(
        self,
        device_id: str,
        run_adb_fn: Optional[Callable[[str, int], str]] = None,
        is_foreground_fn: Optional[Callable[[], bool]] = None
    ):
        self.device_id = device_id
        self._run_adb = run_adb_fn or self._default_run_adb
        self._is_foreground = is_foreground_fn or (lambda: True)

        os.makedirs(CLICK_BEFORE_DIR, exist_ok=True)
        os.makedirs(CLICK_AFTER_DIR, exist_ok=True)
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        os.makedirs(UNEXPOSED_DUMPS_DIR, exist_ok=True)
        os.makedirs(EXPOSED_DUMPS_DIR, exist_ok=True)

    def _default_run_adb(self, cmd: str, timeout_sec: int = 5) -> str:
        try:
            res = subprocess.run(
                ["adb", "-s", self.device_id, "shell"] + cmd.split(),
                capture_output=True, text=True, timeout=timeout_sec
            )
            return res.stdout.strip()
        except Exception:
            return ""

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
        - 저장 경로: logs/click_logs/click_before/YYYY-MM-DD/click_before_{YYYYMMDD_HHMMSS}_{device_id}_mid_{mid}.png
        - 30일 보존 정책 적용
        """
        now = datetime.datetime.now()
        now_str = now.strftime("%Y%m%d_%H%M%S")
        date_str = now.strftime("%Y-%m-%d")
        dated_dir = get_dated_dir(CLICK_BEFORE_DIR, date_str)

        mid_tag = f"_mid_{target_mid}" if target_mid else ""
        archive_path = os.path.join(dated_dir, f"{stage}_{now_str}_{self.device_id}{mid_tag}.png")
        local_raw = f"/tmp/macro_pre_click_{self.device_id}.png"
        local_out = f"/tmp/macro_click_debug_{self.device_id}.png"

        try:
            with open(local_raw, "wb") as f:
                subprocess.run(
                    ["adb", "-s", self.device_id, "exec-out", "screencap", "-p"],
                    stdout=f, timeout=5
                )

            if os.path.exists(local_raw) and os.path.getsize(local_raw) > 1000:
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

                # /tmp 및 click_logs/click_before/YYYY-MM-DD/ 양쪽에 저장
                img.save(local_out)
                img.save(archive_path)
                logger.info(f"[{self.device_id}] [📸 클릭/탐색 직전 시각화 스샷 저장 완료] -> {archive_path}")
                prune_dir_by_age(CLICK_BEFORE_DIR, retention_days=LOG_RETENTION_DAYS)
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
        [타겟 상품 발견 시 해당 상품 영역만 크롭하여 일자별 폴더에 저장]
        - 저장 경로: logs/target_screenshot/YYYY-MM-DD/{YYYYMMDD_HHMMSS}_{mid}_{keyword}_{device_id}.png
        - 30일 보존 정책 적용
        """
        now = datetime.datetime.now()
        time_str = now.strftime("%Y%m%d_%H%M%S")
        date_str = now.strftime("%Y-%m-%d")
        dated_dir = get_dated_dir(SCREENSHOT_DIR, date_str)

        safe_kw = re.sub(r'[\s/\\:*?"<>|]+', '_', (keyword or "UNKNOWN").strip()).strip('_')
        filename = f"{time_str}_{target_mid}_{safe_kw}_{self.device_id}.png"
        archive_path = os.path.join(dated_dir, filename)
        local_raw = f"/tmp/macro_screen_target_{self.device_id}.png"

        try:
            with open(local_raw, "wb") as f:
                subprocess.run(
                    ["adb", "-s", self.device_id, "exec-out", "screencap", "-p"],
                    stdout=f, timeout=5
                )

            if os.path.exists(local_raw) and os.path.getsize(local_raw) > 1000:
                img = Image.open(local_raw).convert("RGBA")
                w_img, h_img = img.size

                x1, y1, x2, y2 = target_bounds
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

                cropped = img.crop((crop_x1, crop_y1, crop_x2, crop_y2))
                cropped.save(archive_path)
                logger.info(f"[{self.device_id}] [📸 타겟 상품 영역 크롭 저장 완료] [{crop_x1},{crop_y1}][{crop_x2},{crop_y2}] -> {archive_path}")
                prune_dir_by_age(SCREENSHOT_DIR, retention_days=LOG_RETENTION_DAYS)
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
        [상세페이지 진입 성공 시 랜딩 화면 전체 캡처를 일자별 폴더에 저장]
        - 저장 경로: logs/click_logs/click_after/YYYY-MM-DD/click_after_{YYYYMMDD_HHMMSS}_{mid}_{keyword}_{device_id}.png
        - 30일 보존 정책 적용
        """
        now = datetime.datetime.now()
        time_str = now.strftime("%Y%m%d_%H%M%S")
        date_str = now.strftime("%Y-%m-%d")
        dated_dir = get_dated_dir(CLICK_AFTER_DIR, date_str)

        safe_kw = re.sub(r'[\s/\\:*?"<>|]+', '_', (keyword or "UNKNOWN").strip()).strip('_')
        filename = f"click_after_{time_str}_{target_mid}_{safe_kw}_{self.device_id}.png"
        archive_path = os.path.join(dated_dir, filename)

        try:
            # 1. 1차 랜딩 스크린샷 캡처
            with open(archive_path, "wb") as f:
                subprocess.run(
                    ["adb", "-s", self.device_id, "exec-out", "screencap", "-p"],
                    stdout=f, timeout=5
                )
            if os.path.exists(archive_path) and os.path.getsize(archive_path) > 1000:
                logger.info(f"[{self.device_id}] [📸 상세페이지 랜딩 1차 스크린샷 저장 완료] -> {archive_path}")

            # 2. 1.0초 대기 후 한 화면 스크롤 다운 (Y: 2050 -> 650)
            time.sleep(1.0)
            logger.info(f"[{self.device_id}] [📜 상세정보 검증] 1화면 하단 스크롤 (2050 -> 650) 이동...")
            subprocess.run(
                ["adb", "-s", self.device_id, "shell", "input", "swipe", "900", "2050", "900", "650", "380"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
            )
            time.sleep(1.0)

            # 3. 2차 스크롤 상세정보 스크린샷 캡처
            filename_scroll = f"click_after_{time_str}_{target_mid}_{safe_kw}_{self.device_id}_scroll.png"
            archive_path_scroll = os.path.join(dated_dir, filename_scroll)
            with open(archive_path_scroll, "wb") as f:
                subprocess.run(
                    ["adb", "-s", self.device_id, "exec-out", "screencap", "-p"],
                    stdout=f, timeout=5
                )
            if os.path.exists(archive_path_scroll) and os.path.getsize(archive_path_scroll) > 1000:
                logger.info(f"[{self.device_id}] [📸 상세페이지 스크롤 2차 스크린샷 저장 완료] -> {archive_path_scroll}")

            prune_dir_by_age(CLICK_AFTER_DIR, retention_days=LOG_RETENTION_DAYS)
            return archive_path
        except Exception as e:
            logger.warning(f"[{self.device_id}] [!] 상세페이지 랜딩/스크롤 스크린샷 저장 실패: {e}")
        return ""

    def save_unexposed_dump(
        self,
        target_mid: str,
        keyword: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        [타겟 상품 미노출(is_exposed=False) 시 사후 분석을 위해 전체 UI XML 덤프 및 화면 캡처를 일자별 폴더에 저장]
        - 저장 경로: logs/unexposed_dumps/YYYY-MM-DD/unexposed_{YYYYMMDD_HHMMSS}_{mid}_{keyword}_{device_id}.xml / .png
        - 30일 보존 정책 적용
        """
        if not self._is_foreground():
            logger.warning(f"[{self.device_id}] [⚠️ 덤프 차단] 현재 포그라운드가 네이버 앱이 아니므로 unexposed_dumps 저장을 취소합니다.")
            return ("", "")

        now = datetime.datetime.now()
        time_str = now.strftime("%Y%m%d_%H%M%S")
        date_str = now.strftime("%Y-%m-%d")
        dated_dir = get_dated_dir(UNEXPOSED_DUMPS_DIR, date_str)

        safe_kw = re.sub(r'[\s/\\:*?"<>|]+', '_', (keyword or "UNKNOWN").strip()).strip('_')
        base_name = f"unexposed_{time_str}_{target_mid}_{safe_kw}_{self.device_id}"
        xml_path = os.path.join(dated_dir, f"{base_name}.xml")
        png_path = os.path.join(dated_dir, f"{base_name}.png")

        try:
            # 1. XML 덤프 저장
            self._run_adb("uiautomator dump /sdcard/unexp_dump.xml", timeout_sec=8)
            xml_str = self._run_adb("cat /sdcard/unexp_dump.xml", timeout_sec=5)
            if xml_str and "<hierarchy" in xml_str:
                xml_clean = xml_str[xml_str.find("<hierarchy"):]
                with open(xml_path, "w", encoding="utf-8") as f:
                    f.write(xml_clean)
                logger.info(f"[{self.device_id}] [📝 미노출 UI XML 덤프 저장 완료] -> {xml_path}")

            # 2. 화면 전체 스크린샷 캡처
            with open(png_path, "wb") as f:
                subprocess.run(
                    ["adb", "-s", self.device_id, "exec-out", "screencap", "-p"],
                    stdout=f, timeout=5
                )
            if os.path.exists(png_path) and os.path.getsize(png_path) > 1000:
                logger.info(f"[{self.device_id}] [📸 미노출 전체 화면 캡처 저장 완료] -> {png_path}")

            prune_dir_by_age(UNEXPOSED_DUMPS_DIR, retention_days=LOG_RETENTION_DAYS)
            return (xml_path, png_path)
        except Exception as e:
            logger.warning(f"[{self.device_id}] [!] 미노출 덤프/캡처 저장 실패: {e}")
        return ("", "")

    def save_exposed_dump(
        self,
        target_mid: str,
        keyword: Optional[str] = None,
        slide_page: int = 1
    ) -> Tuple[str, str]:
        """
        [타겟 상품 노출(is_exposed=True) 시 증적 및 연구 분석을 위해 전체 UI XML 덤프 및 화면 캡처를 일자별 폴더에 저장]
        - 저장 경로: logs/exposed_dumps/YYYY-MM-DD/exposed_{YYYYMMDD_HHMMSS}_{mid}_p{slide_page}_{keyword}_{device_id}.xml / .png
        - 30일 보존 정책 적용
        """
        if not self._is_foreground():
            logger.warning(f"[{self.device_id}] [⚠️ 덤프 차단] 현재 포그라운드가 네이버 앱이 아니므로 exposed_dumps 저장을 취소합니다.")
            return ("", "")

        now = datetime.datetime.now()
        time_str = now.strftime("%Y%m%d_%H%M%S")
        date_str = now.strftime("%Y-%m-%d")
        dated_dir = get_dated_dir(EXPOSED_DUMPS_DIR, date_str)

        safe_kw = re.sub(r'[\s/\\:*?"<>|]+', '_', (keyword or "UNKNOWN").strip()).strip('_')
        base_name = f"exposed_{time_str}_{target_mid}_p{slide_page}_{safe_kw}_{self.device_id}"
        xml_path = os.path.join(dated_dir, f"{base_name}.xml")
        png_path = os.path.join(dated_dir, f"{base_name}.png")

        try:
            # 1. XML 덤프 저장
            self._run_adb("rm -f /sdcard/exp_dump.xml; uiautomator dump /sdcard/exp_dump.xml", timeout_sec=8)
            xml_str = self._run_adb("cat /sdcard/exp_dump.xml", timeout_sec=5)
            if xml_str and "<hierarchy" in xml_str:
                xml_clean = xml_str[xml_str.find("<hierarchy"):]
                with open(xml_path, "w", encoding="utf-8") as f:
                    f.write(xml_clean)
                logger.info(f"[{self.device_id}] [📝 노출 성공 UI XML 덤프 저장 완료 (Slide #{slide_page})] -> {xml_path}")

            # 2. 화면 전체 스크린샷 캡처
            with open(png_path, "wb") as f:
                subprocess.run(
                    ["adb", "-s", self.device_id, "exec-out", "screencap", "-p"],
                    stdout=f, timeout=5
                )
            if os.path.exists(png_path) and os.path.getsize(png_path) > 1000:
                logger.info(f"[{self.device_id}] [📸 노출 성공 전체 화면 캡처 저장 완료 (Slide #{slide_page})] -> {png_path}")

            prune_dir_by_age(EXPOSED_DUMPS_DIR, retention_days=LOG_RETENTION_DAYS)
            return (xml_path, png_path)
        except Exception as e:
            logger.warning(f"[{self.device_id}] [!] 노출 덤프/캡처 저장 실패: {e}")
        return ("", "")
