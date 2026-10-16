#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/pipeline/utils/transition_waiter.py

Playwright/Puppeteer 스타일의 단일화된 범용 전환/대기 엔진 (Universal Transition Waiter)
- 8대 모든 클릭/이동 구간에 100% 공통 적용
- 화면(DOM) 렌더링 지연 없이 패킷(Network) 레벨에서 0.05초 초고속 판정
- 캡차(429/보안확인), 로그인(302/nid), 서버에러(500), 터치불발(Click Missed) 즉시 감지 (Fast-Fail)
"""

import time
import asyncio
import logging
from typing import Dict, Any, Optional, Union
from enum import Enum

from config.settings import TIMINGS
from src.browser.cdp_client import (
    AsyncCDPClient,
    CDPResponse,
    CaptchaBlockedException,
    LoginRedirectException
)
from src.device.adb_controller import fast_check_native_login_or_captcha

logger = logging.getLogger("TransitionWaiter")


class TransitionType(str, Enum):
    PAGE_NAV = "PAGE_NAV"             # 페이지/인텐트 대이동 (통검 더보기, 통검 카탈로그, 쇼핑 카탈로그)
    LANDING = "LANDING"               # 외부몰/스마트스토어 랜딩 (일반 상품 클릭, 판매처 스토어 클릭)
    IN_PAGE_FETCH = "IN_PAGE_FETCH"   # 인페이지 동적 갱신 (카탈로그 페이징, 쇼핑 2페이지 페이징)


class TransitionResult:
    def __init__(
        self,
        success: bool,
        status: str,
        error_message: Optional[str] = None,
        duration_sec: float = 0.0,
        final_url: str = "",
        response: Optional[CDPResponse] = None,
        details: Optional[Dict[str, Any]] = None,
        cdp: Optional[AsyncCDPClient] = None
    ):
        self.success = success
        self.status = status
        self.error_message = error_message
        self.duration_sec = duration_sec
        self.final_url = final_url
        self.response = response
        self.details = details or {}
        self.cdp = cdp

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "error_message": self.error_message,
            "duration_sec": round(self.duration_sec, 3),
            "final_url": self.final_url,
            "response_status": self.response.status if self.response else None,
            "details": self.details
        }

    def __repr__(self) -> str:
        return f"<TransitionResult status={self.status} success={self.success} dur={self.duration_sec:.2f}s url='{self.final_url[:60]}'>"


async def wait_for_transition(
    cdp: AsyncCDPClient,
    transition_type: Union[TransitionType, str],
    expected_pattern: str,
    timeout: float = TIMINGS.TRANSITION_DEFAULT_TIMEOUT,
    before_url: Optional[str] = None,
    packet_filter: Optional[str] = None,
    check_dom_fallback: bool = True,
    device_id: Optional[str] = None,
    cdp_port: Optional[int] = None
) -> TransitionResult:
    """
    [Playwright waitForResponse 기반 범용 전환 대기 함수]
    - transition_type: PAGE_NAV | LANDING | IN_PAGE_FETCH
    - expected_pattern: 기대하는 URL 패턴 (e.g. 'shopping.naver.com', 'smartstore.naver.com')
    - timeout: 최대 대기 시간 (초)
    - before_url: 클릭 직전의 URL (터치 불발/URL 미변화 감지용)
    - cdp_port: 신규 분리 탭(InAppBrowserActivity 등) 실시간 감지용 로컬 디버거 포트
    """
    t0 = time.time()
    t_type = TransitionType(transition_type) if isinstance(transition_type, str) else transition_type

    # 1. Before URL 확보
    start_url = before_url
    if not start_url:
        try:
            start_url = await cdp.evaluate("window.location.href", timeout=1.0)
        except Exception:
            start_url = ""

    logger.info(f"⏳ [전환 대기 시작: {t_type.value}] 목표 패턴: '{expected_pattern}' | 이전 URL: '{start_url[:60]}' | 타임아웃: {timeout}s")

    # 2. 패킷 감시 조건자 (Predicate) 정의
    filter_keyword = packet_filter or expected_pattern

    def _packet_matcher(resp: CDPResponse) -> bool:
        if filter_keyword in resp.url:
            return True
        if t_type == TransitionType.PAGE_NAV and ("shopping.naver.com" in resp.url or "where=m_shop" in resp.url or "msearch.shopping" in resp.url):
            return True
        if t_type == TransitionType.LANDING and ("smartstore.naver.com" in resp.url or "brand.naver.com" in resp.url or "products" in resp.url):
            return True
        return False

    # 3. 비동기 패킷 감시 태스크 생성 (Playwright waitForResponse, 클릭 시점 이후 패킷만 유효)
    packet_task = asyncio.create_task(
        cdp.wait_for_response(
            url_or_predicate=_packet_matcher,
            timeout=timeout,
            check_errors=True,
            since_timestamp=t0
        )
    )

    async def _safe_cancel_packet_task():
        """비동기 패킷 태스크 안전 취소 및 unhandled exception 수거"""
        if not packet_task.done():
            packet_task.cancel()
            try:
                await packet_task
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

    matched_resp = None
    cur_url = start_url

    # 4. 고속 하이브리드 루프 (패킷 태스크 대기 + 0.15초 Fast-Fail/상태 체크)
    deadline = t0 + timeout
    while time.time() < deadline:
        # A. 패킷 감시 태스크가 먼저 완료되었는지 즉시 확인
        if packet_task.done():
            try:
                matched_resp = packet_task.result()
                packet_url = matched_resp.url
                dur = time.time() - t0
                logger.info(f"⚡ [핵심 패킷 도착 완료 ({dur:.2f}s)] HTTP {matched_resp.status} | {packet_url[:80]}")

                # [전환 무결성 2차 검증] PAGE_NAV인 경우 실제 브라우저 URL이 변경되었는지 확인
                if t_type == TransitionType.PAGE_NAV:
                    navigated = False
                    for _ in range(8):  # 최대 0.8초 동안 실제 페이지 전환 확인
                        try:
                            page_u = await cdp.evaluate("window.location.href", timeout=0.4)
                            if page_u and any(k in page_u for k in [expected_pattern, "shopping.naver.com", "msearch.shopping", "where=m_shop", "/search/all"]):
                                cur_url = page_u
                                navigated = True
                                break
                        except Exception:
                            pass
                        if cdp_port:
                            try:
                                raw_list = urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=0.3).read().decode()
                                targets = json.loads(raw_list)
                                shop_t = next((t for t in targets if t.get("type") == "page" and any(k in t.get("url", "") for k in [expected_pattern, "shopping.naver.com", "msearch.shopping", "where=m_shop", "/search/all"])), None)
                                if shop_t:
                                    cur_url = shop_t.get("url", "")
                                    navigated = True
                                    break
                            except Exception:
                                pass
                        await asyncio.sleep(0.1)

                    if navigated:
                        return TransitionResult(
                            success=True,
                            status="SUCCESS",
                            duration_sec=dur,
                            final_url=cur_url,
                            response=matched_resp
                        )
                    else:
                        logger.warning(f"⚠️ [패킷 도착 후 네비게이션 지연] 패킷은 수신되었으나 실제 페이지 URL 미전환 ({cur_url}) -> 하이브리드 루프 계속 대기")
                else:
                    return TransitionResult(
                        success=True,
                        status="SUCCESS",
                        duration_sec=dur,
                        final_url=cur_url,
                        response=matched_resp
                    )
            except CaptchaBlockedException as ce:
                dur = time.time() - t0
                logger.critical(f"🚨 [패킷 레벨 캡차 즉시 감지 ({dur:.2f}s)] {ce}")
                return TransitionResult(
                    success=False,
                    status="CAPTCHA_BLOCKED",
                    error_message=str(ce),
                    duration_sec=dur,
                    final_url=ce.url
                )
            except LoginRedirectException as le:
                dur = time.time() - t0
                logger.warning(f"⚠️ [패킷 레벨 로그인 리다이렉트 즉시 감지 ({dur:.2f}s)] {le}")
                return TransitionResult(
                    success=False,
                    status="LOGIN_REQUIRED",
                    error_message=str(le),
                    duration_sec=dur,
                    final_url=le.redirect_url
                )
            except Exception as e:
                pass

        # B. 0.15초 대기
        await asyncio.sleep(TIMINGS.TRANSITION_POLL_INTERVAL)
        elapsed = time.time() - t0

        # B-2. [안드로이드 최상위 포커스 윈도우 초고속 감지 (50~100ms Fast-Fail)]
        if device_id:
            is_blocked, blk_type, reason = fast_check_native_login_or_captcha(device_id)
            if is_blocked:
                dur = time.time() - t0
                await _safe_cancel_packet_task()
                if blk_type == "LOGIN_REQUIRED":
                    logger.warning(f"⚠️ [네이티브 화면 로그인 감지 ({dur:.2f}s)] {reason}")
                else:
                    logger.critical(f"🚨 [네이티브 화면 캡차 감지 ({dur:.2f}s)] {reason}")
                return TransitionResult(
                    success=False,
                    status=blk_type,
                    error_message=reason,
                    duration_sec=dur,
                    final_url=cur_url
                )

        # B-3. [신규 웹뷰 탭 분리(InAppBrowserActivity 등) 초고속 실시간 감지]
        if cdp_port and elapsed >= 0.2:
            try:
                import urllib.request
                import json
                import websockets
                raw_list = urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=0.4).read().decode()
                targets = json.loads(raw_list)
                shop_t = next((
                    t for t in targets
                    if t.get("type") == "page"
                    and any(k in t.get("url", "") for k in [expected_pattern, "shopping.naver.com", "msearch.shopping", "where=m_shop", "/search/all", "/ns/search"])
                    and t.get("webSocketDebuggerUrl")
                ), None)

                if shop_t:
                    new_ws_url = shop_t["webSocketDebuggerUrl"]
                    cur_ws = getattr(cdp, "ws_url", "")
                    dur = time.time() - t0
                    if cur_ws and new_ws_url == cur_ws:
                        logger.info(f"⚡ [기존 웹뷰 쇼핑 안착 감지 ({dur:.2f}s)] {shop_t.get('url', '')[:70]}")
                        await _safe_cancel_packet_task()
                        return TransitionResult(
                            success=True,
                            status="SUCCESS",
                            duration_sec=dur,
                            final_url=shop_t.get("url", ""),
                            cdp=cdp
                        )
                    else:
                        logger.info(f"⚡ [신규 분리 쇼핑 탭 실시간 안착 감지 ({dur:.2f}s)] {shop_t.get('url', '')[:70]}")
                        new_ws = await websockets.connect(new_ws_url, ping_interval=None, open_timeout=5.0)
                        new_cdp = AsyncCDPClient(new_ws)
                        new_cdp.ws_url = new_ws_url
                        try:
                            await new_cdp.call("Network.enable")
                        except Exception:
                            pass
                        await _safe_cancel_packet_task()
                        return TransitionResult(
                            success=True,
                            status="SUCCESS",
                            duration_sec=dur,
                            final_url=shop_t.get("url", ""),
                            cdp=new_cdp
                        )
            except Exception:
                pass

        # C. [DOM/URL 2중 안전장치 검사] (DOM/인앱브라우저 인플레이스 캡차 등)
        if check_dom_fallback and elapsed >= 0.3:
            try:
                # 가벼운 DOM 헬스체크 JS 1회 실행
                dom_check_js = """
                (() => {
                    const u = window.location.href;

                    // 요소의 실제 화면 가시성(visible) 정밀 판정 함수
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 25 && rect.height > 25;
                    };

                    // 1. 정상 쇼핑 컨테이너 여부 (신/구 네이버 쇼핑 완벽 감지)
                    const hasShoppingContent = !!(
                        window.__NEXT_DATA__?.props?.pageProps ||
                        window.naver?.search?.ext?.newshopping?.shopping ||
                        document.querySelector('a[href*="products/"], a[href*="smartstore.naver.com"], a[href*="brand.naver.com"]') ||
                        document.querySelector('[class*="compositeCard"], [class*="basicProductCard"], [data-shp-contents-id]')
                    );

                    // 2. 실제 화면에 노출된 가시적 캡차 화면 여부 (히든 DOM 요소 오탐 배제)
                    let isCaptcha = false;
                    const isCaptchaUrl = (u.includes('/captcha') || u.includes('/challenge') || u.includes('security/challenge')) &&
                                         !u.includes('query=') && !u.includes('search.naver') && !u.includes('shopping.naver');

                    if (isCaptchaUrl) {
                        isCaptcha = true;
                    } else if (!hasShoppingContent) {
                        // 정상 쇼핑 컨텐츠가 없는 상태에서, 실제 사용자 화면에 렌더링된 가시적 캡차 폼/입력창 존재 여부
                        const captchaForm = document.querySelector('form[action*="captcha"], #captcha_form, .captcha_box, .receipt_captcha');
                        if (isVisible(captchaForm)) {
                            isCaptcha = true;
                        } else {
                            // 보안 확인 안내문과 함께 실제 입력 필드가 가시적으로 렌더링되어 있는지 정밀 판정
                            const bodyText = document.body ? (document.body.innerText || '') : '';
                            const hasCaptchaText = (bodyText.includes('보안 확인') || bodyText.includes('비정상적인 접근') || bodyText.includes('자동입력 방지')) &&
                                                   (bodyText.includes('문자를 입력') || bodyText.includes('영수증'));
                            const hasCaptchaInput = isVisible(document.querySelector('input#captcha_key, input[name*="captcha"], #captcha_img'));
                            if (hasCaptchaText && hasCaptchaInput) {
                                isCaptcha = true;
                            }
                        }
                    }

                    // 3. 로그인 화면 여부 (URL 및 실제 가시적인 로그인 폼)
                    let isLogin = false;
                    const isLoginUrl = u.includes('nidlogin.login') || (u.includes('nid.naver.com') && !u.includes('query='));
                    if (isLoginUrl) {
                        isLogin = true;
                    } else if (!hasShoppingContent) {
                        const loginForm = document.querySelector('form[name*="login"], #login_form, .login_form, [class*="login_box"]');
                        if (isVisible(loginForm)) {
                            isLogin = true;
                        }
                    }

                    // 4. 서버 오류 여부
                    const isError = (u.includes('error') && !u.includes('query=')) ||
                                    isVisible(document.querySelector('.error_content, [class*="error_page"]'));

                    return {
                        url: u,
                        isCaptcha,
                        isLogin,
                        isError,
                        hasShoppingContent
                    };
                })()
                """
                dom_stat = await cdp.evaluate(dom_check_js, timeout=0.8)
                if dom_stat and isinstance(dom_stat, dict):
                    cur_url = dom_stat.get("url", cur_url)

                    # [Fast-Fail 1] 실제 렌더링된 가시적 캡차 감지
                    if dom_stat.get("isCaptcha"):
                        dur = time.time() - t0
                        await _safe_cancel_packet_task()
                        logger.critical(f"🚨 [DOM 레벨 가시적 캡차 포착 ({dur:.2f}s)] 실제 보안 확인 폼 전면 렌더링 감지")
                        return TransitionResult(
                            success=False,
                            status="CAPTCHA_BLOCKED",
                            error_message="네이버 영수증 캡차(보안 확인) 발생",
                            duration_sec=dur,
                            final_url=cur_url
                        )

                    # [Fast-Fail 2] 로그인 창 감지
                    if dom_stat.get("isLogin"):
                        dur = time.time() - t0
                        await _safe_cancel_packet_task()
                        logger.warning(f"⚠️ [DOM 레벨 로그인 화면 포착 ({dur:.2f}s)] 비로그인 차단 감지")
                        return TransitionResult(
                            success=False,
                            status="LOGIN_REQUIRED",
                            error_message="네이버 로그인 창으로 전환됨",
                            duration_sec=dur,
                            final_url=cur_url
                        )

                    # [Fast-Fail 3] 서버 에러 감지
                    if dom_stat.get("isError"):
                        dur = time.time() - t0
                        await _safe_cancel_packet_task()
                        return TransitionResult(
                            success=False,
                            status="SERVER_ERROR",
                            error_message="네이버 서비스 일시 오류 페이지",
                            duration_sec=dur,
                            final_url=cur_url
                        )

                    # [조기 완료 Fast Path] 이미 쇼핑/상세 콘텐츠가 안착된 경우 패킷 기다릴 것 없이 조기 완료!
                    if expected_pattern in cur_url and dom_stat.get("hasShoppingContent"):
                        dur = time.time() - t0
                        await _safe_cancel_packet_task()
                        logger.info(f"⚡ [DOM 컨텐츠 안착 조기 확인 ({dur:.2f}s)] 목표 URL 및 데이터 로딩 완료: {cur_url[:70]}")
                        return TransitionResult(
                            success=True,
                            status="SUCCESS",
                            duration_sec=dur,
                            final_url=cur_url
                        )
            except Exception:
                pass

        # D. [터치 불발(Click Missed) 감지]
        # 설정 시점까지 URL도 그대로이고 최근 응답 패킷도 없으면 터치가 씹힌 것으로 조기 판정
        if elapsed >= TIMINGS.TRANSITION_CLICK_MISSED_THRESHOLD and start_url and cur_url == start_url:
            recent_matched = any(expected_pattern in r.url for r in cdp.recent_responses[-5:])
            if not recent_matched and elapsed >= 3.0:
                logger.warning(f"⚠️ [터치 불발 의심] {elapsed:.1f}초 경과 후에도 URL 미변화 및 관련 패킷 0건")

    # 5. 타임아웃 도달 시 정리
    await _safe_cancel_packet_task()

    dur = time.time() - t0
    # 터치가 전혀 안 먹혀서 URL이 시작점 그대로인 경우
    if start_url and cur_url == start_url:
        logger.error(f"❌ [전환 실패: 터치 불발] {dur:.2f}초 동안 URL 변경 없음 (시작: {start_url[:50]})")
        return TransitionResult(
            success=False,
            status="CLICK_MISSED",
            error_message="클릭 후 페이지 이동 없음 (터치 불발 또는 미반응)",
            duration_sec=dur,
            final_url=cur_url
        )

    logger.error(f"⏰ [전환 실패: 타임아웃] {dur:.2f}초 초과 (현재 URL: {cur_url[:60]})")
    return TransitionResult(
        success=False,
        status="TIMEOUT",
        error_message=f"전환 타임아웃 ({timeout}s 초과, 현재 URL: {cur_url})",
        duration_sec=dur,
        final_url=cur_url
    )
