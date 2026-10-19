#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/pipeline/steps/step6_catalog.py

Step 6: Price Comparison Catalog (Category/Compare) Stage
- Extracts catalogProducts from Next.js RSC query cache (React Query hydration).
- Pins down target seller within:
  #content div[class*="sellerContainer_seller_container"] div[class*="productList_product_list"] > div:nth-child(n)
- Completely avoids top header & bottom floating bar interference.
- Executes 100% Chromium CDP Real Touch (Input.dispatchTouchEvent).
- Complies strictly with [Rule 9] (No JS click) and [Rule 1] (Organic Only).
"""

import os
import sys
import time
import json
import random
import asyncio
import urllib.request
import websockets
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from config.settings import TIMINGS
from src.browser.cdp_client import AsyncCDPClient
from src.device.adb_controller import fast_check_native_login_or_captcha
from src.pipeline.models import TaskInput, TaskResult
from src.pipeline.utils.cdp_touch import cdp_real_touch, save_stage_screenshot
from src.pipeline.utils.dom_stabilizer import wait_for_element_settled

logger = logging.getLogger("ConveyorExecutor")


async def execute_catalog_stage(
    task: TaskInput,
    result: TaskResult,
    cdp: AsyncCDPClient,
    device_id: str,
    cdp_port: int,
    output_dir: Optional[str] = None,
    traffic_logger: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Price comparison catalog stage execution.
    Returns:
    {
        "status": "SUCCESS" | "SELLER_NOT_FOUND" | "CATALOG_TIMEOUT" | ...,
        "success": bool,
        "cdp": AsyncCDPClient (active CDP for product detail page),
        "target_seller": Dict[str, Any]
    }
    """
    t_start = time.time()
    logger.info(f"🏷️ [카탈로그 스테이지 시작] 단말기: {device_id} | 카탈로그 MID: {task.nv_mid} | 타겟 판매처 MID: {task.compare_id or getattr(task, 'target_id', None)}")

    # 1. 카탈로그 상세 화면(/catalog/) CDP 웹뷰 포착
    catalog_cdp = cdp
    active_ws = None
    target_catalog_url = None

    for wait_i in range(25):  # 최대 10초 대기
        await asyncio.sleep(0.4)

        # 네이티브 차단 감지
        is_blocked, blk_type, reason = fast_check_native_login_or_captcha(device_id)
        if is_blocked:
            logger.warning(f"🚨 [카탈로그 진입 중 네이티브 {blk_type} 감지] {reason}")
            return {"status": blk_type, "success": False, "error_message": reason}

        # CDP 대상 웹뷰 목록 스캔
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{cdp_port}/json/list")
            with urllib.request.urlopen(req, timeout=2) as r:
                targets = json.loads(r.read().decode())
                for t in targets:
                    if t.get("type") != "page":
                        continue
                    url = t.get("url", "")
                    if "/catalog/" in url or "msearch.shopping.naver.com/catalog" in url:
                        target_catalog_url = url
                        ws_url = t.get("webSocketDebuggerUrl")
                        if ws_url:
                            active_ws = await websockets.connect(ws_url, max_size=10 * 1024 * 1024)
                            catalog_cdp = AsyncCDPClient(active_ws)
                            logger.info(f"🔗 [카탈로그 전용 웹뷰 포착 및 연결 성공] URL: {url}")
                            break
                if active_ws:
                    break
        except Exception as e:
            logger.debug(f"CDP json/list polling: {e}")

        # 기존 CDP 탭 URL 확인
        try:
            curr_url = await cdp.evaluate("window.location.href")
            if curr_url and "/catalog/" in curr_url:
                target_catalog_url = curr_url
                catalog_cdp = cdp
                logger.info(f"🔗 [기존 웹뷰 카탈로그 페이지 안착 확인] URL: {curr_url}")
                break
        except Exception:
            pass

    if not target_catalog_url:
        logger.warning("⚠️ [카탈로그 페이지 감지 타임아웃] /catalog/ URL을 찾지 못함 -> 현재 활성 웹뷰로 진행")

    # 2. DOM 수화 및 Next.js 렌더링 완료 대기
    logger.info("⏳ [카탈로그 렌더링 수화 대기] Next.js RSC 캐시 및 DOM 로딩 대기...")
    dom_ready = False
    for r_iter in range(15):
        await asyncio.sleep(0.4)
        check_js = """
        (() => {
            const hasNextF = Array.isArray(window.self && window.self.__next_f) && window.self.__next_f.length > 5;
            const hasList = !!document.querySelector('div[class*="productList_product_list"], div[class*="sellerContainer_seller_container"]');
            const bodyLen = (document.body && document.body.innerText) ? document.body.innerText.length : 0;
            return { ready: hasList && bodyLen > 100, hasNextF, bodyLen };
        })()
        """
        try:
            chk = await catalog_cdp.evaluate(check_js)
            if chk and chk.get("ready"):
                dom_ready = True
                logger.info(f"⚡ [카탈로그 DOM 수화 완료] bodyLen={chk.get('bodyLen')} | hasNextF={chk.get('hasNextF')}")
                break
        except Exception:
            pass

    # 3. Next.js RSC 쿼리 캐시(catalogProducts) 정밀 추출 (사용자 제공 최적화 알고리즘)
    rsc_extract_js = """
    (() => {
        const scripts = Array.from(document.querySelectorAll('script'));
        let targetProducts = null;

        for (const script of scripts) {
            const text = script.textContent || '';
            if (!text.includes('self.__next_f.push')) continue;

            const matches = text.matchAll(/self\\.__next_f\\.push\\(\\[1,\\s*"(.*?)"\\]\\)/gs);
            for (const match of matches) {
                try {
                    const rawChunk = JSON.parse(`"${match[1]}"`);
                    const colonIdx = rawChunk.indexOf(':');
                    if (colonIdx === -1) continue;

                    const jsonStr = rawChunk.slice(colonIdx + 1);
                    const parsed = JSON.parse(jsonStr);
                    const queries = parsed?.[3]?.state?.queries;

                    if (Array.isArray(queries)) {
                        const prodQuery = queries.find(q => q?.queryKey?.[0] === 'catalogProducts' && q?.state?.data?.products);
                        if (prodQuery?.state?.data?.products?.length > 0) {
                            targetProducts = prodQuery.state.data.products;
                            break;
                        }
                    }
                } catch (e) {}
            }
            if (targetProducts) break;
        }

        // Script 태그 파싱 실패 시 메모리 window.self.__next_f 직접 스캔 폴백
        if (!targetProducts && Array.isArray(window.self && window.self.__next_f)) {
            for (const item of window.self.__next_f) {
                if (item[0] !== 1 || !item[1]) continue;
                const rawChunk = String(item[1]);
                const colonIdx = rawChunk.indexOf(':');
                if (colonIdx === -1) continue;
                try {
                    const jsonStr = rawChunk.slice(colonIdx + 1);
                    const parsed = JSON.parse(jsonStr);
                    const queries = parsed?.[3]?.state?.queries;
                    if (Array.isArray(queries)) {
                        const prodQuery = queries.find(q => q?.queryKey?.[0] === 'catalogProducts' && q?.state?.data?.products);
                        if (prodQuery?.state?.data?.products?.length > 0) {
                            targetProducts = prodQuery.state.data.products;
                            break;
                        }
                    }
                } catch (e) {}
            }
        }

        if (!targetProducts) {
            return { found: false, count: 0, products: [] };
        }

        return {
            found: true,
            count: targetProducts.length,
            products: targetProducts.map((p, idx) => ({
                idx: idx + 1,
                nvMid: String(p.nvMid || ''),
                matchNvMid: String(p.matchNvMid || ''),
                mallProductId: String(p.mallProductId || ''),
                mallName: String(p.mallName || p.mallInfo?.name || ''),
                price: p.price,
                productName: p.productName || '',
                isSmartStore: !!p.isSmartStoreProduct,
                mobileUrl: p.mobileProductUrl || p.pcProductUrl || ''
            }))
        };
    })()
    """

    rsc_data = await catalog_cdp.evaluate(rsc_extract_js)
    if not rsc_data or not rsc_data.get("found"):
        logger.warning("⚠️ [Next.js RSC 캐시 추출 실패] DOM 기반 직접 탐색으로 폴백 진행")
        products_list = []
    else:
        products_list = rsc_data.get("products", [])
        logger.info(f"📊 [RSC 캐시 상품 {len(products_list)}개 추출 성공] 타겟 판매처 매칭 시작...")

    # 4. [향후 확장 지원: API filter_selector 사전 클릭]
    filter_selector = getattr(task, "filter_selector", None)
    if filter_selector:
        logger.info(f"🔍 [카탈로그 필터 사전 적용] 셀렉터: '{filter_selector}' 탐색 및 사전 터치 시도...")
        try:
            filter_click_js = f"""
            (() => {{
                const fEl = document.querySelector("{filter_selector}");
                if (!fEl) return {{ found: false }};
                fEl.scrollIntoView({{ block: 'center', behavior: 'instant' }});
                const r = fEl.getBoundingClientRect();
                return {{ found: true, x: r.left + r.width / 2, y: r.top + r.height / 2 }};
            }})()
            """
            f_res = await catalog_cdp.evaluate(filter_click_js)
            if f_res and f_res.get("found"):
                await cdp_real_touch(
                    cdp=catalog_cdp,
                    device_id=device_id,
                    task_id=task.task_id,
                    action_name="CATALOG_FILTER_PRESET",
                    click_x=f_res["x"],
                    click_y=f_res["y"],
                    output_dir=output_dir,
                    capture_screenshot=False,
                    use_jitter=False
                )
                await asyncio.sleep(1.2)  # 필터 반영 대기
                logger.info("✅ [카탈로그 필터 사전 적용 완료]")
        except Exception as e:
            logger.warning(f"⚠️ [카탈로그 필터 적용 중 예외 (무시)]: {e}")

    # 5. 타겟 판매처 식별 (사용자 규격: nv_mid=진짜상품ID, compare_id=카탈로그ID)
    is_compare_mode = False
    if task.compare_id:
        try:
            cid = int(str(task.compare_id).strip())
            if cid > 0:
                is_compare_mode = True
        except ValueError:
            pass

    if is_compare_mode:
        target_seller_mid = str(task.nv_mid).strip()
    else:
        target_seller_mid = str(getattr(task, "target_id", None) or task.compare_id or task.nv_mid).strip()

    target_store_name = (task.store_name or "").strip()

    matched_product = None
    target_idx = None

    # 1차: RSC 1페이지(1~10위) nvMid 또는 mallProductId 정확 일치 탐색
    for p in products_list:
        if target_seller_mid and (p.get("nvMid") == target_seller_mid or p.get("mallProductId") == target_seller_mid):
            matched_product = p
            target_idx = p.get("idx")
            logger.info(f"🎯 [RSC 1차 MID 매칭 성공!] {target_idx}번째: 몰명='{p.get('mallName')}' | nvMid={p.get('nvMid')} | mallProductId={p.get('mallProductId')}")
            break

    # 2차: MID 불일치 시 스토어명 매칭
    if not matched_product and target_store_name:
        for p in products_list:
            if target_store_name.lower() in p.get("mallName", "").lower():
                matched_product = p
                target_idx = p.get("idx")
                logger.info(f"🎯 [RSC 2차 몰명 매칭 성공!] {target_idx}번째: 몰명='{p.get('mallName')}' | nvMid={p.get('nvMid')}")
                break

    # 6. [3단계 하이브리드 타겟 조준: 본문 리스트 1순위 ➔ 하단/상단 플로팅 버튼 2순위 구제 ➔ Fast-Fail]
    measure_and_expose_js = f"""
    (async () => {{
        const targetIdx = {target_idx if target_idx is not None else 0};
        const targetMid = "{target_seller_mid}";
        const storeName = "{target_store_name}";

        // 1. 판매처 리스트 컨테이너 특정
        const container = document.querySelector('#content div[class*="sellerContainer_seller_container"] div[class*="productList_product_list"], div[class*="productList_product_list"]');
        let targetRow = null;
        let isFloatingTarget = false;

        // [1순위 탐색]: 본문 1페이지(1~10위) 리스트 내부에서 타겟 행 특정
        if (container) {{
            if (targetIdx > 0) {{
                targetRow = container.querySelector(`:scope > div:nth-child(${{targetIdx}}), :scope > div:nth-of-type(${{targetIdx}})`);
            }}
            if (!targetRow) {{
                const rows = Array.from(container.children);
                for (let i = 0; i < rows.length; i++) {{
                    const r = rows[i];
                    const text = r.innerText || '';
                    const a = r.querySelector('a');
                    const href = a ? a.href : '';
                    if (targetMid && (href.includes(targetMid) || text.includes(targetMid))) {{
                        targetRow = r;
                        break;
                    }}
                    if (storeName && text.includes(storeName)) {{
                        targetRow = r;
                        break;
                    }}
                }}
            }}
        }}

        // [2순위 탐색: 구원 투수]: 1페이지 리스트에 없지만, 하단 플로팅 버튼(공식인증 / 최저가)이나 상단 요약에 내 상품이 걸려 있는가?
        if (!targetRow) {{
            const candidateBtns = Array.from(document.querySelectorAll('button, a, div[role="button"]'));
            for (const el of candidateBtns) {{
                const text = el.innerText || '';
                const href = el.href || el.getAttribute('data-url') || '';
                const isCertBtn = text.includes('공식인증') || text.includes('공식스토어') || text.includes('브랜드인증');
                const isLowestBtn = text.includes('최저가') || text.includes('사러가기');

                if (isCertBtn || isLowestBtn) {{
                    let isMatch = false;
                    if (targetMid && (href.includes(targetMid) || text.includes(targetMid))) {{
                        isMatch = true;
                    }}
                    if (storeName && text.includes(storeName)) {{
                        isMatch = true;
                    }}
                    if (isMatch) {{
                        targetRow = el;
                        isFloatingTarget = true;
                        break;
                    }}
                }}
            }}
        }}

        // [3순위: 둘 다 없으면 무리한 2·3페이지 페이징 스크롤 없이 Fast-Fail]
        if (!targetRow) {{
            return {{ ok: false, reason: "TARGET_NOT_FOUND_IN_PAGE1_OR_FLOATING" }};
        }}

        // 뷰포트 배치 (하단 고정 플로팅 버튼이 아닌 경우에만 scrollIntoView)
        if (!isFloatingTarget) {{
            targetRow.scrollIntoView({{ block: 'center', inline: 'center', behavior: 'instant' }});
            await new Promise(res => setTimeout(res, 200));
        }}

        // 클릭 대상 태그 특정 (구매/상세 링크 우선 매칭)
        const clickEl = targetRow.querySelector('a[class*="buy"], a[class*="link_mall"], a[class*="link"], a[href*="cr.shopping"], a[href*="smartstore"], a[href*="/products/"]') ||
                        targetRow.querySelector('a') ||
                        targetRow;
        clickEl.setAttribute('data-macro-target', 'catalog_target_seller');
        let finalRect = clickEl.getBoundingClientRect();

        const winH = window.innerHeight || 800;
        const winW = window.innerWidth || 360;
        const SAFE_TOP = 110;
        const SAFE_BOTTOM = winH - 90;

        if (!isFloatingTarget && (finalRect.width <= 0 || finalRect.height <= 0 || finalRect.top < SAFE_TOP || finalRect.bottom > SAFE_BOTTOM)) {{
            targetRow.scrollIntoView({{ block: 'center', behavior: 'instant' }});
            await new Promise(res => setTimeout(res, 150));
            finalRect = clickEl.getBoundingClientRect();
        }}

        // [FDS 돌파 가우시안 정규분포 난수]
        const sampleGaussian = (mean, stdDev, minVal, maxVal) => {{
            let u = 0, v = 0;
            while (u === 0) u = Math.random();
            while (v === 0) v = Math.random();
            let z = Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
            let val = mean + z * stdDev;
            return Math.max(minVal, Math.min(val, maxVal));
        }};

        const rx = sampleGaussian(0.50, 0.12, 0.20, 0.80);
        const ry = sampleGaussian(0.50, 0.10, 0.25, 0.75);

        let clickX = finalRect.left + finalRect.width * rx;
        let clickY = finalRect.top + finalRect.height * ry;

        clickX = Math.max(30.0, Math.min(clickX, winW - 30.0));
        if (isFloatingTarget) {{
            clickY = Math.max(winH - 85.0, Math.min(clickY, winH - 25.0));
        }} else {{
            clickY = Math.max(SAFE_TOP + 10.0, Math.min(clickY, SAFE_BOTTOM - 10.0));
        }}

        return {{
            ok: true,
            isFloatingTarget: isFloatingTarget,
            clickX: Math.round(clickX * 10) / 10,
            clickY: Math.round(clickY * 10) / 10,
            rect: {{
                top: Math.round(finalRect.top),
                left: Math.round(finalRect.left),
                width: Math.round(finalRect.width),
                height: Math.round(finalRect.height)
            }},
            tagName: clickEl.tagName,
            className: clickEl.className || '',
            innerText: (targetRow.innerText || '').slice(0, 100).replace(/\\s+/g, ' ')
        }};
    }})()
    """

    measure_res = await catalog_cdp.evaluate(measure_and_expose_js)
    if not measure_res or not measure_res.get("ok"):
        err_msg = measure_res.get("reason", "TARGET_MEASURE_FAILED") if measure_res else "EVAL_FAILED"
        logger.error(f"❌ [카탈로그 판매처 좌표 측정 실패] {err_msg}")
        return {"status": "MEASURE_FAILED", "success": False, "error_message": err_msg}

    click_x = measure_res["clickX"]
    click_y = measure_res["clickY"]
    rect = measure_res["rect"]
    logger.info(f"🎯 [카탈로그 판매처 핀포인트 조준 완료] 좌표=({click_x}, {click_y}) | 크기=({rect['width']}x{rect['height']}) | 텍스트='{measure_res.get('innerText')}'")

    # 6. target_found 스크린샷 증빙
    result.target_found_screenshot = save_stage_screenshot(device_id, "catalog_target_found", task.task_id, output_dir)
    result.touch_coordinates = {"x": click_x, "y": click_y}
    result.click_action = "CATALOG_SELLER_TARGET"
    if matched_product:
        result.store_name = matched_product.get("mallName")
    result.target_type = "CATALOG_SELLER"

    # 📌 [DOM 레이아웃 안정화] 카탈로그 판매처 위치/크기 1.0초 간격 최대 3회 정착 검증
    stabilize_res = await wait_for_element_settled(
        cdp=catalog_cdp,
        target_selector_expr='[data-macro-target="catalog_target_seller"]',
        max_retries=3,
        interval_sec=1.0,
        tolerance_px=2.0,
        action_label="CATALOG_SELLER"
    )
    if not stabilize_res.get("success"):
        logger.error(f"❌ [카탈로그 판매처 정착 실패] 사유: {stabilize_res.get('error')}")
        return {
            "status": "CATALOG_ALIGN_FAILED",
            "success": False,
            "error_message": f"카탈로그 판매처 위치 불안정 또는 조준 불일치 ({stabilize_res.get('error')})"
        }
    click_x = stabilize_res["x"]
    click_y = stabilize_res["y"]

    # 7. [절대 철칙 9] 100% Chromium CDP Real Touch (Input.dispatchTouchEvent) 발송!
    touch_res = await cdp_real_touch(
        cdp=catalog_cdp,
        device_id=device_id,
        task_id=task.task_id,
        action_name="CATALOG_SELLER_TARGET",
        click_x=click_x,
        click_y=click_y,
        output_dir=output_dir,
        capture_screenshot=True,
        use_jitter=True
    )

    result.before_click_screenshot = touch_res.get("capture_path")
    result.click_success = touch_res.get("success", False)
    if not result.click_success:
        result.click_fail_reason = touch_res.get("reason", "TOUCH_FAILED")
        logger.error(f"❌ [카탈로그 판매처 실물 터치 실패] {result.click_fail_reason}")
        return {"status": "TOUCH_FAILED", "success": False, "error_message": result.click_fail_reason}

    logger.info(f"⚡ [카탈로그 판매처 실물 터치 성공] 좌표: ({click_x}, {click_y}) -> 스마트스토어/상세페이지 전환 대기...")

    if traffic_logger:
        traffic_logger.record_event("CATALOG_SELLER_TOUCH", f"Touch seller nvMid={target_seller_mid}", {
            "x": click_x,
            "y": click_y,
            "action": "CATALOG_SELLER_TARGET",
            "matched_product": matched_product,
            "rect": rect
        })

    # 8. 스마트스토어 상세페이지 전환 대기 및 인계
    # 새 창이 열렸는지 확인하기 위해 cdp_port를 통해 스마트스토어 웹뷰 타겟 탐색
    product_cdp = catalog_cdp
    for wait_prod_i in range(20):  # 최대 8초 대기
        await asyncio.sleep(0.4)
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{cdp_port}/json/list")
            with urllib.request.urlopen(req, timeout=2) as r:
                targets = json.loads(r.read().decode())
                for t in targets:
                    if t.get("type") != "page":
                        continue
                    url = t.get("url", "")
                    if "smartstore.naver.com" in url or "brand.naver.com" in url or "/products/" in url:
                        ws_url = t.get("webSocketDebuggerUrl")
                        if ws_url:
                            new_ws = await websockets.connect(ws_url, max_size=10 * 1024 * 1024)
                            product_cdp = AsyncCDPClient(new_ws)
                            logger.info(f"🚀 [스마트스토어 랜딩 웹뷰 전환 성공!] URL: {url}")
                            break
                if product_cdp != catalog_cdp:
                    break
        except Exception:
            pass

        try:
            curr_url = await catalog_cdp.evaluate("window.location.href")
            if curr_url and ("smartstore.naver.com" in curr_url or "brand.naver.com" in curr_url or "/products/" in curr_url):
                logger.info(f"🚀 [동일 웹뷰 내 스마트스토어 랜딩 전환 확인!] URL: {curr_url}")
                product_cdp = catalog_cdp
                break
        except Exception:
            pass

    return {
        "status": "SUCCESS",
        "success": True,
        "cdp": product_cdp,
        "target_seller": matched_product
    }
