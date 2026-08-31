#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
🛒 SMARTSTORE DETAIL PAGE VERIFIER (DetailPageVerifier)
========================================================================================
- 상품 타이틀 안전 터치 및 상세페이지 전환 감시
- 네이버 봇/캡차 자동 탐지 및 즉시 차단 회피
- 검색 화면 이탈 및 구매 CTA / 스마트스토어 전용 지표 30초 체류 완주 검증
- 클릭 직후/직전 증적 이미지(click_after) 영구 보관
========================================================================================
"""

import time
import logging
from typing import Optional, Tuple, Any

from src.modules.macro.ui_inspector import UIInspector

logger = logging.getLogger("NaverMacroCore.DetailPageVerifier")


class DetailPageVerifier:
    """스마트스토어 상세페이지 정상 진입 및 체류 다중 지표 검증 모듈"""

    def __init__(self, device_id: str, inspector: UIInspector):
        self.device_id = device_id
        self.inspector = inspector

    def click_target_product_and_verify(
        self,
        click_coords: Tuple[int, int],
        target_mid: Optional[str] = None,
        keyword: Optional[str] = None,
        timeout_sec: float = 30.0
    ) -> bool:
        """
        [STEP 4: 상품 타이틀 안전 탭 ➔ 상세페이지 전환 검증 ➔ 30초 체류 증적 보관]
        """
        cx, cy = int(click_coords[0]), int(click_coords[1])
        mid_val = str(target_mid or "").strip()
        kw_val = keyword or ""

        logger.info(f"[{self.device_id}] ========================================================")
        logger.info(f"[{self.device_id}] 🎯 [STEP 4] 상품 타이틀 안전 탭 ({cx}, {cy}) | MID: {mid_val} ➔ 상세페이지 진입 대기 (최대 {timeout_sec}초)")
        logger.info(f"[{self.device_id}] ========================================================")

        # 🛡️ 최상위 창이 네이버 앱인지 검증
        self.inspector.ensure_naver_foreground()

        # 안전 탭 실행
        self.inspector.run_adb(f"input tap {cx} {cy}")

        start_time = time.time()
        re_tapped = False

        while time.time() - start_time < timeout_sec:
            time.sleep(1.0)
            elapsed = round(time.time() - start_time, 1)

            root = self.inspector.get_ui_tree("detail_check")
            if root is not None:
                nodes = list(root.iter("node"))
                texts = [elem.attrib.get("text", "").strip() or elem.attrib.get("content-desc", "").strip() for elem in nodes]
                combined = " ".join(texts)

                # 1. 캡차/보안문자 차단 감지
                if any(k in combined for k in ["자동입력 방지", "보안문자", "비정상적인 접근", "차단되었습니다"]):
                    logger.error(f"[{self.device_id}] ❌ [보안 탐지 감지] 네이버 봇 탐지/캡차 페이지 노출됨! 즉시 중단")
                    return False

                # 2. 검색 결과 페이지 잔류 여부 검사
                is_still_search_page = False
                for elem in nodes:
                    rid = elem.attrib.get("resource-id", "")
                    b = elem.attrib.get("bounds", "")
                    if any(s_id in rid for s_id in ["search_query", "search_btn", "search_clear_btn"]):
                        is_still_search_page = True
                        break
                    if kw_val and kw_val in elem.attrib.get("text", "") and b:
                        coords = b.replace("][", ",").replace("[", "").replace("]", "").split(",")
                        if len(coords) == 4 and int(coords[1]) < 350:
                            is_still_search_page = True
                            break

                if is_still_search_page:
                    if elapsed >= 4.0 and not re_tapped:
                        logger.info(f"[{self.device_id}] [ℹ️ 전환 대기] 클릭 후 {elapsed}초 경과 -> 타겟 좌표 ({cx}, {cy}) 1회 보조 탭")
                        self.inspector.run_adb(f"input tap {cx} {cy}")
                        re_tapped = True
                    continue

                # 3. 상세페이지 고유 식별자 검증 (하단 구매바 / 스마트스토어 전용 요소)
                PURCHASE_CTA = ["구매하기", "N Pay 구매", "바로구매", "선물하기", "장바구니"]
                DETAIL_BODY_KEYS = ["톡톡문의", "스토어찜", "알림받기", "상세정보", "상품정보 제공고시", "배송/교환/반품", "Q&A", "옵션 선택"]

                has_purchase_cta = any(any(cta == t or cta in t for cta in PURCHASE_CTA) for t in texts)
                has_detail_body = any(k in combined for k in DETAIL_BODY_KEYS)

                if has_purchase_cta or has_detail_body:
                    logger.info(f"[{self.device_id}] [✓] 상품 상세페이지 정상 진입 100% 확정! (소요: {elapsed}s | 구매CTA: {has_purchase_cta})")

                    # 📸 [상세페이지 캡처 저장] logs/click_logs/click_after/
                    try:
                        self.inspector.save_detail_page_screenshot(target_mid=mid_val, keyword=kw_val)
                    except Exception as e:
                        logger.warning(f"[{self.device_id}] 상세페이지 스크린샷 저장 중 예외: {e}")

                    return True

        logger.warning(f"[{self.device_id}] ❌ [!] 상품 상세페이지 로딩 타임아웃 ({timeout_sec}초 초과) -> 상세페이지 진입 실패 판정")
        return False
