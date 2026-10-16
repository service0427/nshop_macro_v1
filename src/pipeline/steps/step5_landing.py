#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/pipeline/steps/step5_landing.py

Step 5: Landing Verification, Organic Dwell, and Clean Session Wrap-Up
- Sniffs external mall redirects (cr3/searchGate -> external mall: finish immediately)
- Verifies SmartStore/BrandStore landing and guards against HTTP 429 / error pages
- Takes after_landing verification screenshot
- Performs natural real-swipe dwell scrolling for dwell_seconds
- Sends Android Home key to flush navigator.sendBeacon(wcs/lcs)
- Forces app stop and finalizes audit log
"""

import time
import random
import math
import asyncio
import subprocess
import logging
from typing import Dict, Any, Optional
import urllib.request
import json
import websockets

from config.settings import TIMINGS, BLOCKED_DETAIL_IMAGE_URLS
from src.browser.cdp_client import AsyncCDPClient, find_product_page_debugger_url
from src.device.adb_controller import press_home_key, force_stop_app, fast_check_native_login_or_captcha
from src.pipeline.models import TaskInput, TaskResult
from src.pipeline.utils.cdp_touch import save_stage_screenshot

logger = logging.getLogger("ConveyorExecutor")


KNOWN_EXTERNAL_MALLS = {
    "쿠팡", "coupang", "11번가", "11st", "g마켓", "gmarket", "옥션", "auction",
    "위메프", "wemakeprice", "티몬", "tmon", "인터파크", "interpark",
    "ssg", "ssg닷컴", "롯데on", "롯데온", "gs shop", "gsshop",
    "cj온스타일", "cjonstyle", "현대hmall", "hmall", "홈앤쇼핑",
    "ns홈쇼핑", "공영쇼핑", "무신사", "에이블리", "지그재그", "오늘의집", "아이디어스", "하프클럽"
}


def is_known_external_mall_name(name: Optional[str]) -> bool:
    if not name:
        return False
    n = name.strip().lower()
    for em in KNOWN_EXTERNAL_MALLS:
        if em in n:
            return True
    return False


def is_external_mall_url(u: str) -> bool:
    if not u or not isinstance(u, str):
        return False
    u_lower = u.lower().strip()
    if u_lower in ("about:blank", "chrome://newtab", "chrome://"):
        return False

    # 1. 정적 스크립트/에셋/서비스워커/비콘 원천 배제 (.js, .css, .json, .png, sw.js 등)
    static_exts = ('.js', '.css', '.json', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp', '.woff', '.woff2', '.ttf')
    if any(u_lower.split('?')[0].endswith(ext) for ext in static_exts):
        return False
    if "/sw.js" in u_lower or "service-worker" in u_lower or "serviceworker" in u_lower:
        return False

    # 2. 네이버 내부 도메인 및 CDN/인프라 전체 배제 (pstatic.net, naver.com 등)
    naver_domains = (
        "naver.com", "pstatic.net", "navercorp.com", "line.me", "naver.jp", "pstatic.com"
    )
    for nd in naver_domains:
        if f"://{nd}" in u_lower or f".{nd}" in u_lower or f"//{nd}" in u_lower:
            return False

    # 3. 실제 외부 이커머스 쇼핑몰 도메인 또는 상품 경로 포함 여부 검증
    is_known = any(em in u_lower for em in [
        "coupang.com", "11st.co.kr", "gmarket.co.kr", "auction.co.kr", "wemakeprice.com",
        "tmon.co.kr", "interpark.com", "ssg.com", "lotteon.com", "gsshop.com",
        "cjonstyle.com", "hmall.com", "hnsmall.com", "nsmall.com", "musinsa.com",
        "a-bly.com", "zigzag.kr", "ohou.se", "idus.com", "halfclub.com"
    ])
    has_product_path = any(p in u_lower for p in ["/products/", "/product/", "/item/", "/goods/", "/vp/products/"])

    return (is_known or has_product_path) and (u_lower.startswith("http://") or u_lower.startswith("https://"))


async def apply_image_diet_and_layout_guard(cdp: AsyncCDPClient):
    """
    [스마트스토어 상세페이지 초경량 이미지 가상화 & 엑박 방지 가드 엔진]
    - 사용자 요구:
      1. 상세페이지 진입 시 메인영역(상세설명) 및 대문(대표 썸네일)의 대용량 이미지 다운로드 차단하여 기기/네트워크 부하 극적 경감
      2. 사이트 레이아웃이 틀어지지 않고 스크롤 높이 완벽 보존
      3. 엑박(Broken Image Icon) 원천 차단
      4. 체류 비콘(lcs, wcs, nlog 등) 100% 정상 통과
    """
    if not cdp:
        return

    # 1. CDP 레벨 대용량 이미지 URL 패턴 차단 (Network.setBlockedURLs)
    #    (주의: lcs.naver.com, wcs.naver.net, static-resource-smartstore 등 필수 비콘/CSS/JS는 절대 포함하지 않음!)
    try:
        await cdp.call("Network.enable")
        await cdp.call("Network.setBlockedURLs", {
            "urls": BLOCKED_DETAIL_IMAGE_URLS
        })
    except Exception as e:
        logger.warning(f"⚠️ [Image Diet] Network.setBlockedURLs 예외: {e}")

    # 2. DOM 레벨 엑박 원천 방지 및 CSS 레이아웃 가드 주입
    guard_js = """
    (() => {
        try {
            const TRANSPARENT_1X1 = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';

            // A. [엑박 원천 방지] 브라우저 이미지 에러(차단) 포착 시 1x1 투명 GIF로 교체
            //    -> 브라우저 깨진 이미지 아이콘(엑박) 100% 차단
            window.addEventListener('error', function(e) {
                if (e.target && e.target.tagName === 'IMG') {
                    e.target.src = TRANSPARENT_1X1;
                    e.target.style.backgroundColor = '#f8fafc';
                    e.target.style.objectFit = 'cover';
                    e.preventDefault();
                }
            }, true);

            // B. [CSS 레이아웃 가드] 상세 본문 및 대문 영역의 높이/배경 보존
            //    -> 이미지가 안 떠도 본문 높이가 실제 상세페이지처럼 수천 픽셀로 유지되어 스크롤 및 레이아웃 유지
            if (!document.getElementById('nshop-image-diet-style')) {
                const style = document.createElement('style');
                style.id = 'nshop-image-diet-style';
                style.textContent = `
                    /* 스마트스토어 상세 설명(스마트에디터 ONE) 본문 이미지 플레이스홀더 */
                    .se-image-resource,
                    .se-module-image,
                    .se-component-image,
                    div[class*="_introduce"] img,
                    div[class*="product_detail"] img {
                        background-color: #f8fafc !important;
                        min-height: 280px !important;
                        border-radius: 4px !important;
                        object-fit: cover !important;
                        visibility: visible !important;
                    }
                    /* 상품 대문 대표 썸네일 플레이스홀더 */
                    div[class*="represent_image"],
                    div[class*="image_area"],
                    div[class*="thumbnail"] {
                        background-color: #f1f5f9 !important;
                    }
                    div[class*="represent_image"] img,
                    div[class*="image_area"] img,
                    div[class*="thumbnail"] img {
                        background-color: #f1f5f9 !important;
                        object-fit: cover !important;
                    }
                `;
                (document.head || document.documentElement).appendChild(style);
            }

            // C. [Data URI 치환] 이미 DOM에 존재하는 대용량 이미지의 src 및 data-src 치환
            const replaceTargetImgs = () => {
                const imgs = document.querySelectorAll(
                    '.se-image-resource, .se-module-image img, div[class*="_introduce"] img, div[class*="product_detail"] img, div[class*="represent_image"] img, div[class*="thumbnail"] img'
                );
                imgs.forEach(img => {
                    const src = img.src || '';
                    if (src.includes('shop-phinf') || src.includes('post-phinf') || src.includes('seller-phinf') || src.includes('esmplus') || src.includes('cafe24')) {
                        img.src = TRANSPARENT_1X1;
                    }
                    if (img.dataset) {
                        if (img.dataset.src) img.dataset.src = TRANSPARENT_1X1;
                        if (img.dataset.lazySrc) img.dataset.lazySrc = TRANSPARENT_1X1;
                    }
                });
            };
            replaceTargetImgs();

            // D. MutationObserver로 지연 로딩(Lazy Loading) 이미지 동적 가로채기
            if (!window.__nshop_img_observer) {
                window.__nshop_img_observer = new MutationObserver(replaceTargetImgs);
                window.__nshop_img_observer.observe(document.body || document.documentElement, { childList: true, subtree: true });
            }

            return { success: true };
        } catch(err) {
            return { success: false, error: String(err) };
        }
    })()
    """
    try:
        await cdp.evaluate(guard_js)
        logger.info("🛡️ [초경량 이미지 가상화] 대용량 이미지 차단 및 엑박 방지 가드 주입 완료")
    except Exception as e:
        logger.warning(f"⚠️ [Image Diet] DOM 가드 주입 예외: {e}")


async def execute_landing_and_dwell(
    task: TaskInput,
    result: TaskResult,
    device_id: str,
    cdp_port: int,
    output_dir: Optional[str] = None,
    traffic_logger: Optional[Any] = None,
    cdp: Optional[AsyncCDPClient] = None,
    task_start_time: Optional[float] = None
) -> Dict[str, Any]:
    """
    Executes Step 5: Landing detection, dwell, and beacon flush.
    - [동적 체류 동기화]: 60초 기준 (60s - 경과시간) 만큼 동적으로 체류하여 모든 기기가 동시에 종료
    - [외부몰 체류 보장]: InAppBrowserActivity의 PageResume/PagePause 및 ExposureScroll(byUser: true) 정상 수집 보장
    """
    logger.info("⏳ [랜딩 감지] 상세페이지 / 외부몰 인앱브라우저 로딩 대기 중...")
    t0_landing = time.time()
    landing_ws = None
    landing_cdp = None
    ws_conn = None
    hydration_confirmed = False

    # 1. 탭 탐색 및 리다이렉트 스니핑 루프 (최대 12초, 0.3초 간격 패시브 감시)
    sniff_steps = max(1, int(TIMINGS.LANDING_SNIFF_MAX_WAIT / TIMINGS.LANDING_SNIFF_POLL_INTERVAL))
    for wait_iter in range(sniff_steps):
        await asyncio.sleep(TIMINGS.LANDING_SNIFF_POLL_INTERVAL)

        # A. Page.frameNavigated 수신 URL 패시브 검사 (외부몰 인앱브라우저 진입 확인)
        cur_u = getattr(cdp, "current_url", "") if cdp else ""
        if cur_u and is_external_mall_url(cur_u):
            logger.info(f"🌐 [외부몰 인앱브라우저 진입 확인] {cur_u[:75]} -> NLog 체류 및 실물 스크롤 진행")
            result.landing_url = cur_u
            hydration_confirmed = True
            break

        # 네이티브 화면 로그인/캡차 즉시 감지 (Fast-Fail)
        is_blocked, blk_type, reason = fast_check_native_login_or_captcha(device_id)
        if is_blocked:
            logger.warning(f"🚨 [랜딩 대기 중 네이티브 {blk_type} 감지] {reason}")
            result.success = False
            result.status = blk_type
            result.error_message = reason
            force_stop_app(device_id)
            return {"success": False, "status": blk_type, "error_message": reason}

        # B. CDP 네트워크 리다이렉트 실시간 스니핑
        if cdp and hasattr(cdp, "network_events"):
            for ev in reversed(cdp.network_events):
                dest = ev.get("to_url") or (ev.get("url") if ev.get("type") == "redirect" else "")
                if is_external_mall_url(dest):
                    logger.info(f"🌐 [외부몰 리다이렉트 진입 확인] {dest[:75]} -> NLog 체류 및 실물 스크롤 진행")
                    result.landing_url = dest
                    hydration_confirmed = True
                    break
            if hydration_confirmed:
                break

        # C. CDP 대상 탭 목록(/json/list) 실시간 스캔
        try:
            tab_data = urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=0.6).read().decode()
            tab_targets = json.loads(tab_data)
            for tb in tab_targets:
                if tb.get("type") != "page":
                    continue
                tb_url = tb.get("url", "")
                if is_external_mall_url(tb_url):
                    logger.info(f"🌐 [외부몰 웹뷰 탭 진입 확인] {tb_url[:75]} -> NLog 체류 및 실물 스크롤 진행")
                    result.landing_url = tb_url
                    hydration_confirmed = True
                    break
            if hydration_confirmed:
                break
        except Exception:
            pass

        # D. 인앱 브라우저 스마트스토어/네이버쇼핑 상세페이지 탭 탐색
        landing_ws = await find_product_page_debugger_url(cdp_port, timeout=0.2)
        if landing_ws:
            break

    # 2. 스마트스토어/브랜드스토어 탭 연결 및 DOM 수화(Hydration) 정밀 검증 루프
    landing_status: Dict[str, Any] = {}

    if not hydration_confirmed and landing_ws:
        try:
            ws_conn = await websockets.connect(landing_ws, ping_interval=None, open_timeout=5.0)
            landing_cdp = AsyncCDPClient(ws_conn)
            # [사이트 레이아웃 보존 & 엑박 방지 초경량 이미지 가상화 가드 엔진 주입]
            await apply_image_diet_and_layout_guard(landing_cdp)
            result.landing_url = await landing_cdp.evaluate("window.location.href")
            result.landing_title = await landing_cdp.evaluate("document.title")
            logger.info(f"🌐 [상세페이지 탭 진입 확인] '{result.landing_title}' | {result.landing_url}")

            # [수화(Hydration) 완료 및 차단/엑박 여부 정밀 감시 루프 (최대 10초)]
            # 실제 사용자가 상품을 인지하듯 구매버튼, 가격, 적립혜택이 렌더링될 때까지 대기
            check_dom_js = """
            (() => {
                const url = window.location.href;
                const title = (document.title || '').trim();
                const bodyText = (document.body ? document.body.innerText : '') || '';
                const isBlank = (url === 'about:blank' || !url || bodyText.length < 30);

                // 0. 로그인 요구 감지 (연령제한, 성인인증, 비로그인 차단 등)
                const isLogin = url.includes('nid.naver.com') ||
                                url.includes('nid.login') ||
                                title.includes('네이버 : 로그인') ||
                                title.includes('로그인') && (url.includes('nid') || url.includes('login')) ||
                                bodyText.includes('네이버 ID로 로그인') ||
                                bodyText.includes('로그인이 필요합니다') ||
                                bodyText.includes('로그인 후 이용');

                // 1. IP 차단, FDS 차단, 상품 삭제/품절/중지/에러 화면 검출 (즉시 실패)
                const blockedKeywords = [
                    '상품 정보를 표시할 수 없습니다',
                    '상품정보를 표시할 수 없습니다',
                    '판매가 중지된 상품입니다',
                    '존재하지 않는 상품입니다',
                    '일시적인 오류가 발생했습니다',
                    '현재 서비스 접속이 불가합니다',
                    '동시에 접속하는 이용자 수가 많거나',
                    '페이지를 찾을 수 없습니다',
                    '삭제되었거나 존재하지 않는',
                    '서비스에 접속할 수 없습니다'
                ];
                const isTitleError = title.includes('에러') || title.includes('오류') || title.includes('페이지를 찾을');
                const matchedBlockedKw = blockedKeywords.find(kw => bodyText.includes(kw)) || (isTitleError ? title : null);
                const isBlocked = !!matchedBlockedKw || isLogin;

                // 2. 핵심 구매 버튼 탐색 (스마트스토어 '구매하기'/'NPay' 및 카탈로그 '최저가 사러가기'/'사러가기')
                const allButtons = Array.from(document.querySelectorAll('button, a, div[role="button"]'));
                const buyBtn = allButtons.find(b => {
                    const t = (b.innerText || '').trim();
                    const hasBuyText = t.includes('구매하기') || t.includes('사러가기') || t.includes('NPay') || t.includes('바로구매') || t.includes('판매처') || (t.includes('장바구니') && t.includes('구매'));
                    const visible = b.offsetParent !== null || b.getBoundingClientRect().height > 20;
                    return hasBuyText && visible;
                });

                // 3. 실제 가격 텍스트 탐색 (숫자 + '원' 필수 매칭, 카탈로그 '최저 27,900원' 지원)
                const priceElements = Array.from(document.querySelectorAll('[class*="price"], [class*="Price"], [class*="lowest"], span[class*="_price"], em, strong'));
                const validPriceEl = priceElements.find(el => {
                    const t = (el.innerText || '').trim();
                    return (/\\d{1,3}(,\\d{3})*\\s*원/.test(t) || /\\d+\\s*원/.test(t)) && t.length < 35;
                });
                const priceText = validPriceEl ? (validPriceEl.innerText || '').trim().replace(/\\s+/g, ' ').substring(0, 30) : null;
                const hasPrice = !!validPriceEl;

                // 4. 후처리 위젯 탐색: "최대 적립 포인트" 또는 NPay 혜택
                const allSpans = Array.from(document.querySelectorAll('span, div, p, strong, em'));
                const pointEl = allSpans.find(el => {
                    const t = (el.innerText || '').trim();
                    return (t.includes('최대') && t.includes('적립')) || t.includes('포인트 최대') || t.includes('NPay 포인트');
                });
                const pointText = pointEl ? (pointEl.innerText || '').trim().replace(/\\s+/g, ' ').substring(0, 40) : null;

                // 5. 스토어명 및 메인 상품 이미지 탐색
                let storeEl = document.querySelector('[class*="StoreHeader_title"], [class*="StoreHeader_name"], [class*="channel_name"], [class*="store_name"], [class*="mall_name"], [class*="ChannelName"]');
                let storeName = storeEl ? (storeEl.innerText || '').trim().substring(0, 30) : null;
                if (!storeName && title.includes(' : ')) {
                    const parts = title.split(' : ');
                    if (parts.length > 1) storeName = parts[parts.length - 1].trim();
                }
                const imgEl = document.querySelector('img[src*="shop"], img[src*="phinf"], [class*="represent"] img, [class*="thumb"] img, [class*="product"] img');
                const hasImg = !!imgEl && (imgEl.naturalWidth > 50 || imgEl.getBoundingClientRect().width > 50);

                // 6. 정상 상세페이지 로딩 완료 여부 종합 판정:
                // - 차단/에러가 없고, 빈 페이지가 아니며,
                // - 실제 텍스트가 있는 구매 버튼(hasBuyBtn) 또는 실제 원 단위 가격(hasPrice)이 완벽히 렌더링되어야 함!
                const isReady = !isBlocked && !isBlank && (!!buyBtn || hasPrice);

                return {
                    url: url,
                    title: title,
                    isBlocked: isBlocked,
                    isLogin: isLogin,
                    blockedReason: matchedBlockedKw || (isLogin ? 'LOGIN_REQUIRED' : null),
                    isBlank: isBlank,
                    hasBuyBtn: !!buyBtn,
                    buyBtnText: buyBtn ? (buyBtn.innerText || '').trim().replace(/\\n/g, ' ').substring(0, 30) : null,
                    hasPrice: hasPrice,
                    priceText: priceText,
                    hasPoint: !!pointEl,
                    pointText: pointText,
                    storeName: storeName,
                    hasImg: hasImg,
                    isReady: isReady,
                    bodyLength: bodyText.length,
                    readyState: document.readyState
                };
            })()
            """

            hyd_steps = max(1, int(TIMINGS.LANDING_HYDRATION_MAX_WAIT / TIMINGS.LANDING_HYDRATION_POLL_INTERVAL))
            for chk_iter in range(hyd_steps):
                await asyncio.sleep(TIMINGS.LANDING_HYDRATION_POLL_INTERVAL)

                # A. 네이티브 화면 감시
                is_blocked_native, blk_type_native, reason_native = fast_check_native_login_or_captcha(device_id)
                if is_blocked_native:
                    logger.warning(f"🚨 [상세페이지 로드 중 네이티브 {blk_type_native} 감지] {reason_native}")
                    result.success = False
                    result.status = blk_type_native
                    result.login_detected = (blk_type_native == "LOGIN_REQUIRED")
                    result.error_message = reason_native
                    save_stage_screenshot(device_id, blk_type_native.lower(), task.task_id, output_dir)
                    force_stop_app(device_id)
                    return {"success": False, "status": blk_type_native, "error_message": reason_native}

                # B. DOM 상태 스캔
                try:
                    landing_status = await landing_cdp.evaluate(check_dom_js)
                except Exception as eval_err:
                    logger.debug(f"DOM 평가 대기 중: {eval_err}")
                    continue

                if not isinstance(landing_status, dict):
                    continue

                # 1) 로그인 요구 감지 시 -> 즉시 중단
                if landing_status.get("isLogin"):
                    logger.warning(f"🚨 [상세페이지 로그인 요구 감지] {landing_status.get('url')}")
                    result.success = False
                    result.status = "LOGIN_REQUIRED"
                    result.login_detected = True
                    result.error_message = f"상세페이지 진입 시 로그인 화면으로 리다이렉트 발생: {landing_status.get('url')}"
                    save_stage_screenshot(device_id, "landing_login_required", task.task_id, output_dir)
                    press_home_key(device_id)
                    force_stop_app(device_id)
                    return {"success": False, "status": "LOGIN_REQUIRED", "error_message": result.error_message}

                # 2) FDS/차단 화면 감지 시 -> 즉시 중단 (스크롤 일체 금지)
                if landing_status.get("isBlocked"):
                    reason = landing_status.get("blockedReason") or "차단 에러 화면"
                    logger.error(f"🚨 [상세페이지 차단 감지] 사유: '{reason}' (스크롤 생략 및 즉시 종료)")
                    result.success = False
                    result.status = "FDS_PAGE_BLOCKED" if "상품 정보" in reason else "PRODUCT_UNAVAILABLE"
                    result.error_message = f"상세페이지 차단 또는 상품 미존재 에러 발생: {reason}"
                    save_stage_screenshot(device_id, "landing_blocked", task.task_id, output_dir)
                    press_home_key(device_id)
                    force_stop_app(device_id)
                    return {"success": False, "status": result.status, "error_message": result.error_message}

                # 2) 정상 수화(Hydration) 완료 판정
                if landing_status.get("isReady"):
                    hydration_confirmed = True
                    buy_t = landing_status.get("buyBtnText") or "확인됨"
                    p_t = landing_status.get("priceText") or "확인됨"
                    pt_t = landing_status.get("pointText") or "-"
                    st_n = landing_status.get("storeName") or "-"
                    dur_hyd = (chk_iter + 1) * TIMINGS.LANDING_HYDRATION_POLL_INTERVAL
                    logger.info(f"🎉 [상세페이지 정상 로딩 완료 ({dur_hyd:.1f}s)] 구매버튼='{buy_t}' | 가격='{p_t}' | 포인트='{pt_t}' | 몰='{st_n}'")
                    if st_n and st_n != "-":
                        result.store_name = st_n
                    break

        except Exception as e:
            logger.warning(f"⚠️ [상세페이지 CDP 연결/검증 예외] {e}")

    # 3. 수화 미완료 판정 -> 외부몰인지 확인 후 스마트스토어 스켈레톤 타임아웃 처리
    if not hydration_confirmed:
        if result.landing_url and is_external_mall_url(result.landing_url):
            logger.info(f"🌐 [외부몰 도메인 확인 완료] {result.landing_url[:75]} -> NLog 체류 및 실물 스크롤 진행")
            hydration_confirmed = True
        else:
            logger.error(f"🚨 [상세페이지 수화 타임아웃] {TIMINGS.LANDING_HYDRATION_MAX_WAIT:.1f}초 경과 후에도 정상적인 구매버튼/가격 로딩 실패 (엑박/미완성 상태)")
            result.success = False
            result.status = "PRODUCT_HYDRATION_TIMEOUT"
            result.error_message = "상세페이지 하단 정상 데이터(구매버튼/가격) 로딩 실패 (타임아웃)"
            result.after_click_screenshot = save_stage_screenshot(device_id, "after_landing_failed", task.task_id, output_dir)
            press_home_key(device_id)
            force_stop_app(device_id)
            return {"success": False, "status": "PRODUCT_HYDRATION_TIMEOUT", "error_message": result.error_message}

    # 4. [인간 체류 패턴: 로그 정규분포(Log-Normal Distribution) 난수화 및 심층 실물 스와이프 (byUser: true 보장)]
    active_dwell_cdp = landing_cdp or cdp

    # [랜딩 무결성 최종 가드] 상세페이지/외부몰 미진입 상태(검색결과 잔류)에서 체류 진입 원천 차단
    current_active_url = result.landing_url or getattr(active_dwell_cdp, "current_url", "") or ""
    if any(s_domain in current_active_url for s_domain in ["msearch.shopping.naver.com/search", "m.search.naver.com/search"]):
        logger.critical(f"🚨 [랜딩 실패 감지] 상품 클릭 후에도 상세페이지로 이동하지 못하고 검색결과에 잔류 중 ({current_active_url}) -> False Positive 방지 LANDING_MISSED 실패 처리")
        result.success = False
        result.status = "LANDING_MISSED"
        result.error_message = f"상품 클릭 후 상세페이지로 이동하지 못하고 검색결과에 잔류 ({current_active_url})"
        result.after_click_screenshot = save_stage_screenshot(device_id, "landing_missed", task.task_id, output_dir)
        press_home_key(device_id)
        force_stop_app(device_id)
        return {"success": False, "status": "LANDING_MISSED", "error_message": result.error_message}

    if active_dwell_cdp:
        await apply_image_diet_and_layout_guard(active_dwell_cdp)

    result.after_click_screenshot = save_stage_screenshot(device_id, "after_landing", task.task_id, output_dir)

    actual_start_time = task_start_time or getattr(task, "task_start_time", None) or t0_landing
    elapsed_so_far = time.time() - actual_start_time

    # [과제 1: X(검색) + Y(체류) = 60초 선형 음의 상관관계 완전 파괴]
    # - 실제 인간 이커머스 체류 시간인 긴 꼬리 로그 정규분포(Log-Normal) 적용
    # - 중앙값(median) ~40초, 80% 구간: 25~50초, 유효 안전 범위: 20~58초
    median_dwell = float(getattr(task, "dwell_seconds", 0) or TIMINGS.DWELL_DEFAULT_SECONDS)
    if median_dwell <= 0 or median_dwell > 70:
        median_dwell = TIMINGS.DWELL_DEFAULT_SECONDS
    mu = math.log(median_dwell)
    raw_dwell = random.lognormvariate(mu, 0.28)
    dwell_dur = round(max(TIMINGS.DWELL_MIN_SECONDS, min(raw_dwell, TIMINGS.DWELL_MAX_SECONDS)), 1)

    logger.info(f"⏱️ [로그정규분포 체류 시간 산출] 검색소요: {elapsed_so_far:.1f}s | 상세체류목표: {dwell_dur:.1f}s (예상총소요: {elapsed_so_far + dwell_dur:.1f}s, X+Y 선형성 완전 해체)")

    # [과제 2: 스크롤 깊이(Scroll Depth) 심화 및 TagScanner ExposureImp 다회차 분산]
    # - 단순 찔끔 스크롤(1~2회) 배제: 체류시간에 비례하여 5~14회의 실물 제스처 분산 주입
    # - 가속 플링(Fling: dur 150~220ms, 이동 ~1100px)과 감속 탐색(Slow: dur 480~620ms, 이동 ~400px) 혼합
    # - 18% 확률로 이전 본문/옵션을 재확인하는 자연스러운 역방향(위로) 스크롤 주입
    # - 스와이프 간 2.0s ~ 5.5s 가변 '콘텐츠 인지/독해 일시정지(Reading Pause)' 적용
    t_dwell_start = time.time()
    num_swipes = max(5, int(dwell_dur // 4.2))
    base_interval = dwell_dur / num_swipes

    for loop_idx in range(num_swipes):
        cur_elapsed = time.time() - t_dwell_start
        if cur_elapsed >= dwell_dur:
            break

        # 방향 결정: 첫 2회는 무조건 아래로 탐색, 이후 18% 확률로 이전 내용 재확인(역방향 스크롤)
        is_scroll_down = (loop_idx < 2) or (random.random() >= 0.18)

        # 인간 손가락 터치 위치 지터 (중앙 기준 ±40px)
        sx = random.randint(490, 590)
        gesture_type = random.random()

        if is_scroll_down:
            if gesture_type < 0.25:
                # [빠른 플링(Fling)]: 리뷰/하단 스펙으로 훌쩍 건너뛰는 큰 스와이프 (Y축 900~1200px 이동)
                sy1 = random.randint(1750, 1950)
                sy2 = random.randint(650, 850)
                dur = random.randint(150, 220)
            elif gesture_type < 0.70:
                # [표준 스크롤]: 일반적인 페이지 훑어보기 (Y축 550~750px 이동)
                sy1 = random.randint(1550, 1750)
                sy2 = random.randint(950, 1150)
                dur = random.randint(320, 440)
            else:
                # [정밀 훑기(Slow Drift)]: 본문 텍스트/사진 유심히 보기 (Y축 300~450px 이동)
                sy1 = random.randint(1400, 1550)
                sy2 = random.randint(1050, 1200)
                dur = random.randint(480, 620)
        else:
            # [역방향 재확인(Upward Scroll)]: 방금 지나친 가격/옵션/이미지 다시 보기
            sy1 = random.randint(950, 1150)
            sy2 = random.randint(1450, 1680)
            dur = random.randint(340, 460)

        # Linux 커널/InputManager 레벨 실제 터치 이벤트 발송 -> NLog ExposureScroll의 byUser: true 100% 충족
        subprocess.run(f"adb -s {device_id} shell input swipe {sx} {sy1} {sx} {sy2} {dur}", shell=True, timeout=5.0)

        gesture_name = "FLING" if (is_scroll_down and gesture_type < 0.25) else ("STANDARD" if (is_scroll_down and gesture_type < 0.70) else ("SLOW_DRIFT" if is_scroll_down else "UPWARD_RECHECK"))
        # 인간형 콘텐츠 독해 일시정지 (Reading Pause: 가변 딜레이)
        pause = random.uniform(base_interval * 0.75, base_interval * 1.25)

        dwell_entry = {
            "swipe_idx": loop_idx + 1,
            "direction": "down" if is_scroll_down else "up",
            "gesture": gesture_name,
            "coord": {"sx": sx, "sy1": sy1, "sy2": sy2, "dur": dur},
            "pause_sec": round(pause, 2)
        }
        result.dwell_history.append(dwell_entry)
        result.action_history.append({
            "time": time.time(),
            "action": "DWELL_SWIPE",
            "details": dwell_entry
        })

        time_left = dwell_dur - (time.time() - t_dwell_start)
        if time_left > 0:
            await asyncio.sleep(min(pause, time_left))

    # 목표 체류시간까지 미세 잔여 시간 대기
    rem_time = dwell_dur - (time.time() - t_dwell_start)
    if rem_time > 0:
        await asyncio.sleep(rem_time)

    actual_dwell_spent = round(time.time() - t_dwell_start, 2)
    result.dwell_duration_seconds = actual_dwell_spent
    result.action_history.append({
        "time": time.time(),
        "action": "DWELL_COMPLETED",
        "dwell_seconds": actual_dwell_spent,
        "target_seconds": dwell_dur,
        "total_swipes": len(result.dwell_history)
    })
    logger.info(f"☕ [체류 완결] 실측 체류시간: {actual_dwell_spent}s (목표: {dwell_dur:.1f}s, 총 {len(result.dwell_history)}회 실물 스와이프 깊이 확보)")

    # 5. [사용자 엄명] 세션 정상 마감: Android Home 키 발송 -> InAppBrowser onPause (PagePause NLog 발송) -> 비콘 Flush -> 앱 강제 종료
    logger.info("🏠 [세션 정상 마감] Home 키 발송 -> InAppBrowser onPause (PagePause) & 종료 비콘(sendBeacon) 송신 유도...")
    press_home_key(device_id)
    await asyncio.sleep(TIMINGS.DWELL_HOME_BEACON_WAIT)
    force_stop_app(device_id)

    if ws_conn:
        try:
            await ws_conn.close()
        except Exception:
            pass

    result.success = True
    result.status = "SUCCESS"
    total_spent = round(time.time() - actual_start_time, 2)
    logger.info(f"🎉 [작업 완결 성공] Task #{task.task_id} 성공적으로 완결되었습니다! (검색: {elapsed_so_far:.1f}s + 체류: {actual_dwell_spent}s = 총 {total_spent}s)")

    return {"success": True, "status": "SUCCESS"}
