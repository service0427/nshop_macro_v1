#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/pipeline/steps/step4_shop.py

Step 4: Shopping Tab Exploration & Pinpoint Strike
- Validates target presence via window.__NEXT_DATA__ / pagedSlot
- Fast-Fail: If target is not in Page 1 -> NOT_FOUND immediately
- Warm-up Action: Executes basic human gestures
- 📌 [절대 철칙 9: el.click() 영구 금지 & 100% CDP Real Touch 필수]
  좌표는 CDP getBoundingClientRect()로 정밀 추출하되, 클릭은 무조건 CDP Input.dispatchTouchEvent 실물 터치로만 수행!
  사유: JavaScript el.click() 사용 시 브라우저 터치 이벤트 및 FDS 필수 텔레메트리/비콘 패킷(WTM, nlog)이
  통째로 누락되어 네이버 FDS에 비정상 매크로로 탐지되어 로그인/캡차 유발 및 유효타가 박탈됨.
"""

import time
import json
import random
import asyncio
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from config.settings import TIMINGS
from src.browser.cdp_client import AsyncCDPClient
from src.pipeline.models import TaskInput, TaskResult
from src.pipeline.utils.cdp_touch import cdp_real_touch, save_stage_screenshot
from src.device.adb_controller import fast_check_native_login_or_captcha

logger = logging.getLogger("ConveyorExecutor")


async def dump_next_data_products(
    cdp: AsyncCDPClient,
    task: TaskInput,
    device_id: str,
    output_dir: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    [사용자 지침] __NEXT_DATA__ compositeProducts 전체 데이터를 통째로 JSON으로 영구 저장
    """
    safe_kw = (task.keyword or "").replace('"', '\\"')
    dump_js = f"""
    (() => {{
        let pp = window.__NEXT_DATA__?.props?.pageProps;
        if (!pp) {{
            try {{
                const el = document.getElementById('__NEXT_DATA__');
                if (el && el.textContent) {{
                    const d = JSON.parse(el.textContent);
                    pp = d?.props?.pageProps;
                }}
            }} catch(e) {{}}
        }}
        if (!pp) return null;
        const comp = pp.compositeProducts || pp.initialData?.products || {{}};
        const list = comp.list || pp.products || [];
        return {{
            query: pp.query || pp.keyword || pp.initialData?.query || "{safe_kw}",
            totalCount: comp.total || list.length,
            list: list
        }};
    }})()
    """
    for _ in range(6):
        try:
            raw_products_data = await cdp.evaluate(dump_js)
            if raw_products_data and raw_products_data.get("list"):
                if output_dir:
                    p_out = Path(output_dir) / "next_data_products.json"
                    with open(p_out, "w", encoding="utf-8") as f_dump:
                        json.dump(raw_products_data, f_dump, ensure_ascii=False, indent=2)
                    logger.info(f"💾 [__NEXT_DATA__ 통 JSON 영구 저장] 상품 {len(raw_products_data['list'])}개 -> {p_out}")

                harvest_dir = Path("logs/harvest/raw")
                harvest_dir.mkdir(parents=True, exist_ok=True)
                clean_kw = "".join(c for c in (task.keyword or "unknown") if c.isalnum() or c in (" ", "_", "-")).strip()
                h_out = harvest_dir / f"{clean_kw}_{device_id}_{int(time.time())}.json"
                with open(h_out, "w", encoding="utf-8") as f_h:
                    json.dump(raw_products_data, f_h, ensure_ascii=False, indent=2)
                return raw_products_data
        except Exception as e:
            logger.debug(f"__NEXT_DATA__ 덤프 예외: {e}")
        await asyncio.sleep(0.4)
    return None


async def execute_shopping_stage(
    task: TaskInput,
    result: TaskResult,
    cdp: AsyncCDPClient,
    device_id: str,
    output_dir: Optional[str] = None,
    traffic_logger: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Executes Step 4: Shopping tab __NEXT_DATA__ check, warmup, and CDP strike.
    """
    t0_shop = time.time()

    # 0. 쇼핑 탭 진입 상태 사전 무결성 검증 (통합검색 화면 잔류 시 헛스크롤 원천 차단)
    try:
        cur_url = await cdp.evaluate("window.location.href") or ""
        if "m.search.naver.com" in cur_url and not any(k in cur_url for k in ["shopping.naver.com", "tab=shop"]):
            logger.warning(f"⚠️ [쇼핑탭 진입 감시] 브라우저가 아직 통합검색 화면에 잔류 중입니다: {cur_url} (0.8s 완충 대기)")
            await asyncio.sleep(0.8)
            cur_url = await cdp.evaluate("window.location.href") or ""
            if "m.search.naver.com" in cur_url and not any(k in cur_url for k in ["shopping.naver.com", "tab=shop"]):
                logger.error(f"❌ [쇼핑탭 진입 실패] 쇼핑 화면으로 전이되지 않고 통합검색에 고착되었습니다: {cur_url}")
                return {
                    "success": False,
                    "status": "SHOP_NAV_FAILED",
                    "error_message": f"쇼핑 화면 미전이 (통합검색 잔류: {cur_url})"
                }
    except Exception as e:
        logger.debug(f"쇼핑탭 진입 URL 사전 확인 예외 (무시): {e}")

    # 1. 쇼핑 탭 초기 안정화, 캡차 감지 및 __NEXT_DATA__ 타겟 사전 확인
    logger.info("⏳ [쇼핑 탭 초기 로드 검증] __NEXT_DATA__ 타겟 존재 사전 검증 중...")
    target_info = None
    target_rank = task.target_rank
    target_title = None
    is_catalog_target = False

    compare_mid = task.compare_id or getattr(task, "target_id", None) or ""
    check_next_data_js = f"""
    (() => {{
        const targetMid = "{task.nv_mid or ''}";
        const compareMid = "{compare_mid}";
        const targetRank = {task.target_rank if task.target_rank is not None else 'null'};

        // 요소 가시성 판정
        const isVisible = (el) => {{
            if (!el) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 25 && rect.height > 25;
        }};

        // 1. Next.js __NEXT_DATA__ 검사 (정상 쇼핑 데이터가 있으면 캡차가 아님)
        let pp = window.__NEXT_DATA__?.props?.pageProps;
        if (!pp) {{
            try {{
                const el = document.getElementById('__NEXT_DATA__');
                if (el && el.textContent) {{
                    const d = JSON.parse(el.textContent);
                    pp = d?.props?.pageProps;
                }}
            }} catch(e) {{}}
        }}
        pp = pp || {{}};
        const comp = pp.compositeProducts || pp.initialData?.products || {{}};
        const list = comp.list || pp.products || [];

        // 2. DOM 캡차 검사 (쇼핑 데이터가 없을 때만 가시적 캡차 폼 정밀 검사)
        if (!list || list.length === 0) {{
            const u = window.location.href;
            const isCaptchaUrl = (u.includes('/captcha') || u.includes('/challenge')) && !u.includes('query=') && !u.includes('search.naver') && !u.includes('shopping.naver');
            const captchaForm = document.querySelector('form[action*="captcha"], #captcha_form, .receipt_captcha');
            if (isCaptchaUrl || isVisible(captchaForm)) {{
                return {{ isCaptcha: true }};
            }}
        }}

        if (list && list.length > 0) {{
            let organicCounter = 0;
            let directHit = null;
            let catalogHit = null;

            for (let i = 0; i < list.length; i++) {{
                const card = list[i];
                // [양성 식별자 1] 엔트리 타입: type == 'product' (supersaving, ad 등 원천 배제)
                if (card && card.type && card.type !== 'product') continue;

                const it = card.item || card;
                // [양성 식별자 2] 컬렉션: collection == 'product'
                if (it.collection && it.collection !== 'product') continue;

                // [양성 식별자 3] 광고성 플래그 원천 배제
                if (it.ad || it.isAd || it.adProductInfoEnabled || it.adcrUrl) continue;

                // [양성 식별자 4] 슈퍼적립/유료 프로모션 원천 배제
                if (it.promotion && String(it.promotion).includes('SUPER_POINT')) continue;

                organicCounter++;
                const itId = String(it.id || it.nvMid || it.channelProductId || '');
                const itCatId = String(it.catalogMatchingId || '');
                const itRank = (typeof it.rank === 'number' && it.rank > 0) ? it.rank : organicCounter;
                const isCat = (it.mallCount > 1) || !!itCatId;

                // 1순위: 내 상품(targetMid)이 단독 카드(!isCat)로 바로 노출된 경우 -> Direct Hit!
                if (targetMid && (itId === targetMid) && !isCat) {{
                    directHit = {{
                        found: true,
                        rank: itRank,
                        nvMid: itId,
                        catalogId: itCatId || '',
                        title: it.productTitle || it.productName || it.title || '',
                        mallName: it.mallName || it.channelName || '',
                        isCatalog: false,
                        totalCount: list.length,
                        isDirectSellerHit: true
                    }};
                    break;
                }}

                // 2순위: 카탈로그 카드 매칭 (compareMid 또는 targetMid)
                const isMatchCatalog = (compareMid && (itId === compareMid || itCatId === compareMid)) ||
                                       (targetMid && (itId === targetMid || itCatId === targetMid));
                if (!catalogHit && isMatchCatalog) {{
                    catalogHit = {{
                        found: true,
                        rank: itRank,
                        nvMid: itId || compareMid || targetMid,
                        catalogId: itCatId || '',
                        title: it.productTitle || it.productName || it.title || '',
                        mallName: it.mallName || it.channelName || '',
                        isCatalog: isCat,
                        totalCount: list.length
                    }};
                }}

                if (!directHit && !catalogHit && !targetMid && targetRank !== null && itRank === targetRank) {{
                    return {{
                        found: true,
                        rank: itRank,
                        nvMid: itId,
                        title: it.productTitle || it.productName || it.title || '',
                        mallName: it.mallName || it.channelName || '',
                        isCatalog: isCat,
                        totalCount: list.length
                    }};
                }}
            }}

            if (directHit) return directHit;
            if (catalogHit) return catalogHit;

            // 1페이지 데이터가 로드되었는데도 타겟이 없다면 -> 1페이지에 없음!
            if (list.length >= 20 || (pp.initialData?.products?.total && list.length >= pp.initialData.products.total)) {{
                return {{ found: false, notInPage1: true, ready: true, totalCount: list.length }};
            }}
        }}

        // 3. pagedSlot 검사 (m_shop 탭)
        const ps = window.naver?.search?.ext?.newshopping?.shopping?._INITIAL_STATE?.initProps?.pagedSlot;
        if (ps && Array.isArray(ps) && ps.length > 0) {{
            let pRank = 0;
            for (let pIdx = 0; pIdx < ps.length; pIdx++) {{
                const slots = ps[pIdx].slots || [];
                for (let sIdx = 0; sIdx < slots.length; sIdx++) {{
                    const d = slots[sIdx].data || {{}};
                    const isAd = (d.sourceType === 'AD') || (d.cardType === 'AD_CARD') || !!d.isAd;
                    if (isAd) continue;

                    pRank++;
                    const sId = String(d.nvMid || d.channelProductId || '');
                    if (targetMid && sId === targetMid) {{
                        return {{
                            found: true,
                            rank: d.rank || pRank,
                            nvMid: sId,
                            title: (d.productName || '').replace(/<[^>]+>/g, ''),
                            mallName: d.mallName || '',
                            isCatalog: (d.cardType === 'CATALOG_CARD') || !!d.catalogMatchingId || (d.mallCount > 1),
                            totalCount: pRank
                        }};
                    }}
                }}
            }}
        }}

        return {{
            found: false,
            ready: (list && list.length > 0) || (ps && ps.length > 0),
            totalCount: list.length || 0
        }};
    }})()
    """

    next_data_steps = max(1, int(TIMINGS.SHOP_NEXT_DATA_MAX_WAIT / TIMINGS.SHOP_NEXT_DATA_POLL_INTERVAL))
    for wait_iter in range(next_data_steps):  # __NEXT_DATA__ 적응형 완충 대기
        await asyncio.sleep(TIMINGS.SHOP_NEXT_DATA_POLL_INTERVAL)
        # 네이티브 로그인/캡차 즉시 감지 (Fast-Fail: ADB 경합 완화를 위해 6회(1.8초)마다 1회 점검)
        if wait_iter % 6 == 0:
            is_blocked, blk_type, reason = fast_check_native_login_or_captcha(device_id)
            if is_blocked:
                logger.warning(f"🚨 [쇼핑탭 대기 중 네이티브 {blk_type} 감지] {reason}")
                save_stage_screenshot(device_id, blk_type.lower(), task.task_id, output_dir)
                if traffic_logger:
                    traffic_logger.record_event(blk_type, reason, {"url": "SHOPPING_TAB", "error": reason})
                return {
                    "success": False,
                    "status": blk_type,
                    "error_message": reason
                }

        try:
            chk_res = await cdp.evaluate(check_next_data_js)
            if chk_res and chk_res.get("isCaptcha"):
                logger.critical("🚨 [쇼핑탭 캡차 차단 즉시 감지] 화면에 영수증 캡차/보안확인이 노출되었습니다.")
                captcha_png = save_stage_screenshot(device_id, "captcha_blocked_shop", task.task_id, output_dir)

                # [사용자 지침] 캡차 퀴즈 문제, 질문 텍스트 및 이미지 추출하여 영구 보존
                captcha_details = {}
                try:
                    extract_captcha_js = """
                    (() => {
                        const img = document.querySelector('img[src*="captcha"], img[src*="challenge"], .captcha_img, #captcha_img, img.receipt');
                        const qEl = document.querySelector('.question, .guide_text, .desc, .title, [class*="desc"], [class*="guide"], [class*="question"]');
                        const input = document.querySelector('input[type="text"], input[name*="captcha"], #captcha_val, input[class*="captcha"]');
                        const form = document.querySelector('form[action*="captcha"], #captcha_form, .receipt_captcha');
                        return {
                            url: window.location.href,
                            question: qEl ? qEl.innerText.trim() : "",
                            img_src: img ? img.src : "",
                            input_selector: input ? (input.id ? '#' + input.id : (input.name ? 'input[name="' + input.name + '"]' : 'input')) : "",
                            form_html: form ? form.outerHTML.slice(0, 3000) : (document.body ? document.body.innerHTML.slice(0, 3000) : "")
                        };
                    })()
                    """
                    captcha_details = await cdp.evaluate(extract_captcha_js) or {}
                    info_path = Path(output_dir) / f"captcha_info_task{task.task_id}_{time.strftime('%Y%m%d_%H%M%S')}.json"
                    with open(info_path, "w", encoding="utf-8") as f_cap:
                        json.dump(captcha_details, f_cap, ensure_ascii=False, indent=2)
                    logger.info(f"💾 [캡차 퀴즈 데이터 보존 완료] 질문: '{captcha_details.get('question')}' | 이미지: {captcha_details.get('img_src')} -> {info_path}")
                except Exception as cap_err:
                    logger.warning(f"[-] 캡차 데이터 추출 예외: {cap_err}")

                if traffic_logger:
                    traffic_logger.record_event("CAPTCHA_BLOCKED", "Captcha Detected in Shopping Tab", {
                        "device_id": device_id,
                        "task_id": task.task_id,
                        "captcha_details": captcha_details,
                        "screenshot": captcha_png
                    })
                return {
                    "success": False,
                    "status": "CAPTCHA_BLOCKED",
                    "error_message": "쇼핑탭 결과 화면에서 네이버 영수증 캡차(보안 확인) 발생"
                }

            if task.target_rank == 999 and chk_res and (chk_res.get("ready") or chk_res.get("notInPage1") or chk_res.get("totalCount", 0) > 0):
                logger.info(f"⚡ [수집 모드 조기 덤프] 쇼핑 상품 데이터 로드 완료 ({chk_res.get('totalCount')}개) -> 즉시 덤프 후 조기 종료")
                await dump_next_data_products(cdp, task, device_id, output_dir)
                result.js_target_found = True
                result.js_total_count = chk_res.get("totalCount")
                result.js_search_type = "SHOPPING"
                result.shopping_rank = 40
                result.success = True
                result.status = "SUCCESS"
                return {
                    "success": True,
                    "status": "SUCCESS",
                    "shopping_rank": 40,
                    "error_message": None
                }

            if chk_res and chk_res.get("found"):
                target_info = chk_res
                target_rank = chk_res.get("rank")
                target_title = chk_res.get("title")
                is_catalog_target = bool(chk_res.get("isCatalog", False))
                result.shopping_rank = target_rank
                result.shopping_page = 1
                result.js_target_found = True
                result.js_target_rank = target_rank
                result.js_total_count = chk_res.get("totalCount")
                result.js_search_type = "SHOPPING"
                print(f"🎯 [__NEXT_DATA__ 타겟 사전 확인 완료] {target_rank}위 | '{target_title}' (카탈로그={is_catalog_target}) -> DOM 40개 노출 스크롤 시작")
                logger.info(f"🎯 [__NEXT_DATA__ 타겟 사전 확인 완료] {target_rank}위 | '{target_title}' (카탈로그={is_catalog_target}) -> DOM 40개 노출 스크롤 시작")
                logger.info(f"🔍 [쇼핑탭 JS 타겟 탐색] 발견=True | 순위={target_rank}위 | 전체상품={result.js_total_count}개 | 제목='{target_title}'")
                await dump_next_data_products(cdp, task, device_id, output_dir)
                break

            if chk_res and chk_res.get("notInPage1"):
                result.js_target_found = False
                result.js_total_count = chk_res.get("totalCount")
                result.js_search_type = "SHOPPING"
                result.scroll_count = 0
                result.click_success = False
                result.click_fail_reason = "NOT_IN_PAGE1_DATA"
                logger.warning(f"⚠️ [쇼핑 1페이지 타겟 미존재] __NEXT_DATA__ {chk_res.get('totalCount')}개 상품 데이터 전수 검사 완료 -> 타겟(MID: {task.nv_mid}) 미포함 즉시 확정 (스크롤 생략)")
                await dump_next_data_products(cdp, task, device_id, output_dir)
                return {
                    "success": False,
                    "status": "NOT_FOUND",
                    "error_message": f"쇼핑탭 1페이지 데이터({chk_res.get('totalCount')}개)에 타겟(MID: {task.nv_mid}) 미존재"
                }
        except Exception:
            pass

    # [사용자 엄명: 불필요한 스크롤 방지] JS 데이터 전수 검사 후 타겟 미발견 시 -> 무의미한 스크롤 일체 생략하고 즉시 종료
    if not target_info:
        total_seen = chk_res.get("totalCount", 0) if chk_res else 0
        result.js_target_found = False
        result.js_total_count = total_seen
        result.js_search_type = "SHOPPING"
        result.scroll_count = 0
        result.click_success = False
        result.click_fail_reason = "NOT_IN_PAGE1_DATA"
        logger.warning(f"⚠️ [쇼핑 1페이지 타겟 미존재 확정] JS 데이터 {total_seen}개 상품 전수 검사 결과 타겟(MID: {task.nv_mid}) 없음 -> 불필요한 스크롤 생략 및 즉시 종료")
        await dump_next_data_products(cdp, task, device_id, output_dir)
        return {
            "success": False,
            "status": "NOT_FOUND",
            "error_message": f"쇼핑탭 1페이지 데이터({total_seen}개)에 타겟(MID: {task.nv_mid}) 미존재 (스크롤 생략)"
        }

    search_mid = (target_info.get("nvMid") if target_info else "") or task.nv_mid
    target_cat_id = (target_info.get("catalogId") or "") if target_info else ""
    compare_mid = task.compare_id or getattr(task, "target_id", None) or ""

    # 2. [사용자 지침] 오가닉 상품 40개 탐색 및 타겟 조기 발견(Early Exit) 스크롤 루프
    check_target_early_js = f"""
    (() => {{
        const searchMid = "{search_mid}";
        const targetMid = "{task.nv_mid or ''}";
        const compareMid = "{compare_mid}";
        const catId = "{target_cat_id}";

        let targetCard = null;
        for (let m of [searchMid, compareMid, targetMid, catId]) {{
            if (!m) continue;
            targetCard = document.querySelector('div[id="_sr_lst_' + m + '"][class^="product_list_item__"]') ||
                         document.getElementById('_sr_lst_' + m) ||
                         document.querySelector('[data-nv-mid="' + m + '"]') ||
                         document.querySelector('[data-id="' + m + '"]');
            if (targetCard) break;
        }}
        if (!targetCard) {{
            for (let m of [searchMid, compareMid, targetMid]) {{
                if (!m) continue;
                const link = document.querySelector('a[href*="' + m + '"]');
                if (link) {{
                    targetCard = link.closest('div[class^="product_list_item__"]') || link.closest('li');
                    if (targetCard) break;
                }}
            }}
        }}

        const organicCards = Array.from(
            document.querySelectorAll('div[class*="listContainer_list_inner"] > div[class^="product_list_item__"]')
        );
        const organicIds = organicCards.map(el => (el.id || '').replace('_sr_lst_', '').trim());
        const detectedRank = targetCard ? (organicCards.indexOf(targetCard) + 1) : 0;

        return {{
            found: !!targetCard,
            count: organicCards.length,
            rank: detectedRank > 0 ? detectedRank : (organicIds.indexOf(searchMid) + 1)
        }};
    }})()
    """

    print("📜 [쇼핑탭 타겟 탐색 및 노출 스크롤 시작] 조기 발견(Early Exit) 및 최대 확장 스크롤...")
    logger.info("📜 [쇼핑탭 타겟 탐색 및 노출 스크롤 시작] 조기 발견(Early Exit) 및 최대 확장 스크롤...")

    result.scroll_count = 0
    early_stat = await cdp.evaluate(check_target_early_js) or {}
    cur_count = early_stat.get("count", 0)
    target_already_in_dom = bool(early_stat.get("found"))
    target_early_rank = early_stat.get("rank", 0)

    print(f"📊 [초기 노출 상태] 오가닉 {cur_count}개 렌더링 확인 (타겟 DOM 존재: {target_already_in_dom})")
    logger.info(f"📊 [초기 노출 상태] 오가닉 {cur_count}개 렌더링 확인 (타겟 DOM 존재: {target_already_in_dom})")

    result.action_history.append({
        "time": time.time(),
        "action": "SHOPPING_INIT_CHECK",
        "rendered_count": cur_count,
        "target_in_dom": target_already_in_dom,
        "rank": target_early_rank
    })

    if target_already_in_dom:
        print(f"🎯 [타겟 DOM 조기 포착] 초기 렌더링({cur_count}개)에 이미 {target_early_rank}위로 존재 -> 추가 스크롤 생략하고 즉시 조준!")
        logger.info(f"🎯 [타겟 DOM 조기 포착] 초기 렌더링({cur_count}개)에 이미 {target_early_rank}위로 존재 -> 추가 스크롤 생략하고 즉시 조준!")
    else:
        for scroll_idx in range(1, TIMINGS.SHOP_MAX_SCROLL_COUNT + 1):  # 최대 확장 스크롤 (QoS 대역폭 저하 완충)
            result.scroll_count += 1
            print(f"👇 [쇼핑탭 확장 스크롤 {scroll_idx}/{TIMINGS.SHOP_MAX_SCROLL_COUNT}] 타겟 탐색 및 노출 확장을 위한 스크롤 (현재: {cur_count}개)...")
            logger.info(f"👇 [쇼핑탭 확장 스크롤 {scroll_idx}/{TIMINGS.SHOP_MAX_SCROLL_COUNT}] 타겟 탐색 및 노출 확장을 위한 스크롤 (현재: {cur_count}개)...")

            scroll_js = """
            (() => {
                window.scrollBy({ top: 2500, behavior: 'instant' });
                if (document.scrollingElement) document.scrollingElement.scrollTop += 2500;
            })()
            """
            await cdp.evaluate(scroll_js)
            subprocess.run(
                f"adb -s {device_id} shell 'input swipe 540 2100 540 400 160; sleep 0.05; input swipe 540 2100 540 400 160'",
                shell=True
            )

            # 네이버 쇼핑 인피니트 스크롤 비동기 AJAX 렌더링 대기 (QoS 감안 적응형 대기)
            prev_cnt = cur_count
            ajax_steps = max(1, int(TIMINGS.SHOP_SCROLL_AJAX_MAX_WAIT / TIMINGS.SHOP_SCROLL_AJAX_POLL_INTERVAL))
            for _ in range(ajax_steps):
                await asyncio.sleep(TIMINGS.SHOP_SCROLL_AJAX_POLL_INTERVAL)
                scroll_stat = await cdp.evaluate(check_target_early_js) or {}
                cur_count = scroll_stat.get("count", 0)
                if scroll_stat.get("found"):
                    target_already_in_dom = True
                    target_early_rank = scroll_stat.get("rank", 0)
                    break
                if cur_count >= prev_cnt + 5:
                    break

            print(f"📊 [스크롤 {scroll_idx}회차 결과] 오가닉 {cur_count}개 렌더링 (타겟 발견: {target_already_in_dom})")
            logger.info(f"📊 [스크롤 {scroll_idx}회차 결과] 오가닉 {cur_count}개 렌더링 (타겟 발견: {target_already_in_dom})")

            result.action_history.append({
                "time": time.time(),
                "action": f"SHOPPING_SCROLL_{scroll_idx}",
                "rendered_count": cur_count,
                "target_in_dom": target_already_in_dom,
                "rank": target_early_rank
            })

            if target_already_in_dom:
                print(f"🎯 [타겟 DOM 조기 포착] 스크롤 {scroll_idx}회차({cur_count}개 노출 중 {target_early_rank}위)에서 타겟 발견 -> 추가 스크롤 즉시 중단 및 조준 진입!")
                logger.info(f"🎯 [타겟 DOM 조기 포착] 스크롤 {scroll_idx}회차({cur_count}개 노출 중 {target_early_rank}위)에서 타겟 발견 -> 추가 스크롤 즉시 중단 및 조준 진입!")
                break

            if cur_count >= 40:
                print(f"✅ [오가닉 40개 노출 달성] {cur_count}개 렌더링 완료 -> 스크롤 종료 및 타겟 조준 진입")
                logger.info(f"✅ [오가닉 40개 노출 달성] {cur_count}개 렌더링 완료 -> 스크롤 종료 및 타겟 조준 진입")
                break

    # 40개 노출 또는 타겟 발견 후 레이아웃 완전 정착 대기
    await asyncio.sleep(TIMINGS.SHOP_POST_SCROLL_SETTLE)

    # 3. [사용자 지침] 40개 완성 DOM에서 직관적 querySelector로 타겟 카드 직접 조준 (다각도 폴백)
    pinpoint_target_js = f"""
    (() => {{
        const searchMid = "{search_mid}";
        const targetMid = "{task.nv_mid or ''}";
        const compareMid = "{compare_mid}";
        const catId = "{target_cat_id}";
        const targetRank = {task.target_rank if task.target_rank is not None else 'null'};

        // 1. [사용자 지침] 오가닉 상품 카드 목록 수집
        const organicCards = Array.from(
            document.querySelectorAll('div[class*="listContainer_list_inner"] > div[class^="product_list_item__"]')
        );
        const organicIds = organicCards.map(el => (el.id || '').replace('_sr_lst_', '').trim());

        // [절대 철칙 1] 광고 정밀 2중 검증기 (CPC / 파워링크 / 쇼핑검색광고 100% 원천 차단 - DOM 속성 단독)
        const isAdCard = (el) => {{
            if (!el) return false;
            // 1. Ad links (네이버 공식 광고 링크)
            if (el.querySelector('a[href*="adcr."], a[href*="/adcr/"], a[href*="ader."], a[href*="powerlink"], a[href*="ad.search"]')) {{
                return true;
            }}
            // 2. nlog / slog attributes
            const nlogArea = (el.getAttribute('data-nlog-area') || '').toLowerCase();
            if (nlogArea.startsWith('ad') || nlogArea.includes('.ad.') || nlogArea.includes('epl') || nlogArea.includes('pwl')) {{
                return true;
            }}
            const nlogParams = el.getAttribute('data-nlog-params') || '';
            if (nlogParams.includes('"is_ad":true') || nlogParams.includes('"is_ad":"true"') || nlogParams.includes('"isAd":true')) {{
                return true;
            }}
            const slog = (el.getAttribute('data-slog-container') || el.closest('[data-slog-container]')?.getAttribute('data-slog-container') || '').toLowerCase();
            if (slog.includes('epl') || slog.includes('_ad') || slog.includes('ad_') || slog.includes('power')) {{
                return true;
            }}
            // 3. Class names and badge elements
            const cls = ((el.className || '') + ' ' + Array.from(el.querySelectorAll('[class]')).map(c => c.className).join(' ')).toLowerCase();
            if (/(^|\\s|_|-)(ad_badge|adbadge|ad_icon|adicon|ad_item|aditem|commercial_ad|ad_product|sponsor)($|\\s|_|-)/.test(cls)) {{
                return true;
            }}
            if (el.querySelector('[class*="ad_badge"], [class*="adbadge"], [class*="ad_icon"], [data-ad]')) {{
                return true;
            }}
            return false;
        }};

        // 2. [Chromium Blink DOM querySelector 단독 매칭]
        let targetCard = null;
        let matchedCriteria = "";

        for (let m of [searchMid, compareMid, targetMid, catId]) {{
            if (!m) continue;
            const c = document.querySelector('div[id="_sr_lst_' + m + '"][class^="product_list_item__"]') ||
                      document.getElementById('_sr_lst_' + m) ||
                      document.querySelector('[data-nv-mid="' + m + '"]') ||
                      document.querySelector('[data-id="' + m + '"]');
            if (c && !isAdCard(c)) {{
                targetCard = c;
                matchedCriteria = `Direct ID #_sr_lst_${{m}}`;
                break;
            }}
        }}

        if (!targetCard) {{
            for (let m of [searchMid, compareMid, targetMid]) {{
                if (!m) continue;
                const allLinks = Array.from(document.querySelectorAll('a[href*="' + m + '"]'));
                for (let link of allLinks) {{
                    const c = link.closest('div[class^="product_list_item__"]') || link.closest('li');
                    if (c && !isAdCard(c)) {{
                        targetCard = c;
                        matchedCriteria = `Link href with mid='${{m}}'`;
                        break;
                    }}
                }}
                if (targetCard) break;
            }}
        }}

        if (!targetCard) {{
            return {{ found: false, error: "TARGET_NOT_FOUND_IN_40_ITEMS", totalCount: organicCards.length }};
        }}

        // [광고 최종 차단 검증]
        if (isAdCard(targetCard)) {{
            return {{ found: false, isAdBlocked: true, reason: "TARGET_CARD_IS_AD" }};
        }}

        let finalRank = organicCards.indexOf(targetCard) + 1;
        if (finalRank <= 0) {{
            finalRank = organicIds.indexOf(targetMid) + 1;
        }}

        const winH = window.innerHeight || 800;
        const winW = window.innerWidth || 360;
        const SAFE_TOP = 110;
        const SAFE_BOTTOM = winH - 85;

        // [코치마크/가림막 툴팁 원천 제거] "버튼을 눌러서 상품사진·동영상을 확인하세요!" 등 가림막 팝업 제거
        try {{
            document.querySelectorAll('div[class*="tooltip"], div[class*="coach"], div[class*="guide"], div[class*="balloon"]').forEach(el => {{ try {{ el.remove(); }} catch(ign) {{}} }});
        }} catch(e) {{}}

        // 3. 타겟 상품 뷰포트 위치 검사 (이미 안전 영역에 완벽히 들어와 있으면 불필요한 scrollIntoView 생략)
        let offsetPx = 0;
        const initRect = targetCard.getBoundingClientRect();
        if (initRect.top < SAFE_TOP || initRect.bottom > SAFE_BOTTOM) {{
            targetCard.scrollIntoView({{ block: 'center', inline: 'center', behavior: 'instant' }});
            // [사용자 지침] 위아래 1~50px 미세 랜덤 스크롤
            const offsetDir = Math.random() < 0.5 ? -1 : 1;
            offsetPx = offsetDir * (Math.floor(Math.random() * 50) + 1);
            window.scrollBy({{ top: offsetPx, behavior: 'instant' }});
        }}

        // 4. 클릭 대상 요소(제목 링크 최우선 추출, 몰/리뷰 div 요소 배제)
        const titleEl = targetCard.querySelector('a[class*="product_link_title"], [class*="product_link_title"] a') ||
                        targetCard.querySelector('a[class*="product_title"], [class*="product_title"] a') ||
                        targetCard.querySelector('a[class*="product_info_tit"], [class*="product_info_tit"] a') ||
                        targetCard.querySelector('a[class*="title"], [class*="title"] a, a[class*="tit"]') ||
                        targetCard.querySelector('a[data-nclick*="title"], a[data-nlog-area*="title"], a[data-nclick*="item"], a[data-nlog-area*="item"]') ||
                        targetCard.querySelector('a[href*="/products/"], a[href*="smartstore.naver.com"], a[href*="brand.naver.com"], a[href*="cr3.shopping.naver.com"], a[href*="cr.shopping.naver.com"]') ||
                        targetCard.querySelector('a[class*="product_link_image"]') ||
                        targetCard.querySelector('a:not([class*="mall"]):not([class*="seller"])') ||
                        targetCard.querySelector('a');

        const clickEl = titleEl || targetCard;
        if (isAdCard(clickEl)) {{
            return {{ found: false, isAdBlocked: true, reason: "CLICK_EL_IS_AD" }};
        }}
        const titleText = (titleEl ? titleEl.innerText : (targetCard.querySelector('[class*="title"]')?.innerText || targetCard.innerText || '')).trim().slice(0, 45);

        let r = clickEl.getBoundingClientRect();
        if (!r.width || !r.height) {{
            r = targetCard.getBoundingClientRect();
        }}

        if (r.top < SAFE_TOP) {{
            window.scrollBy({{ top: r.top - SAFE_TOP - 15, behavior: 'instant' }});
            r = clickEl.getBoundingClientRect();
        }} else if (r.bottom > SAFE_BOTTOM) {{
            window.scrollBy({{ top: r.bottom - SAFE_BOTTOM + 15, behavior: 'instant' }});
            r = clickEl.getBoundingClientRect();
        }}

        // [FDS 돌파 핵심] Box-Muller 가우시안 정규분포(Gaussian Normal Distribution) 난수 생성
        const sampleGaussian = (mean, stdDev, minVal, maxVal) => {{
            let u = 0, v = 0;
            while (u === 0) u = Math.random();
            while (v === 0) v = Math.random();
            let z = Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
            let val = mean + z * stdDev;
            return Math.max(minVal, Math.min(val, maxVal));
        }};

        // 인간 시선과 손가락이 제목 텍스트 중심부와 시작부에 집중되는 종형 곡선(Bell Curve) 적용
        const randXRatio = sampleGaussian(0.45, 0.12, 0.18, 0.78);
        const randYRatio = sampleGaussian(0.50, 0.10, 0.22, 0.75);
        let clickX = r.left + r.width * randXRatio;
        let clickY = r.top + r.height * randYRatio;

        clickX = Math.max(25.0, Math.min(clickX, winW - 25.0));
        clickY = Math.max(SAFE_TOP + 10.0, Math.min(clickY, SAFE_BOTTOM - 10.0));

        const isCatalog = !!targetCard.querySelector('[class*="catalog"], [class*="mallCount"], [class*="mall_count"], [class*="price_compare"]') ||
                          (clickEl.getAttribute('href') || '').includes('catalog');

        const mallEl = targetCard.querySelector('[class*="mall_name"], [class*="mallName"], [class*="seller"], [class*="mall"], [class*="channel"]');
        const mallName = mallEl ? (mallEl.innerText || '').trim() : '';

        const preRank = {result.js_target_rank if result.js_target_rank else 'null'};
        finalRank = organicCards.indexOf(targetCard) + 1;
        if (finalRank <= 0) {{
            finalRank = organicIds.indexOf(targetMid) + 1;
        }}
        if (finalRank <= 0 && preRank) {{
            finalRank = preRank;
        }}

        return {{
            found: true,
            currentUrl: window.location.href,
            matchedSelector: matchedCriteria,
            elementInfo: {{
                tagName: clickEl.tagName,
                id: clickEl.id || '',
                className: clickEl.className || '',
                href: clickEl.href || clickEl.getAttribute('href') || '',
                text: (clickEl.innerText || '').trim().slice(0, 80)
            }},
            cardInfo: {{
                tagName: targetCard.tagName,
                id: targetCard.id || '',
                className: targetCard.className || '',
                outerHtmlPreview: (targetCard.outerHTML || '').slice(0, 200)
            }},
            rank: finalRank > 0 ? finalRank : (preRank || 1),
            nvMid: targetMid || (targetCard.id || '').replace('_sr_lst_', ''),
            clickX: Math.round(clickX * 10) / 10,
            clickY: Math.round(clickY * 10) / 10,
            title: titleText,
            mallName: mallName,
            isCatalog: isCatalog,
            offsetPx: offsetPx,
            renderedCount: organicCards.length
        }};
    }})()
    """

    card_res = await cdp.evaluate(pinpoint_target_js)

    # [핵심 보강] 타겟 미발견 시 1회 지연 로딩 흔들기(Last-Gasp Retry)로 누락 방지
    if not card_res or not card_res.get("found"):
        logger.info("🔄 [쇼핑탭 DOM 재확인 (Last-Gasp Settle)] 레이아웃 흔들기 후 1회 추가 조준 시도...")
        await cdp.evaluate("window.scrollBy({ top: -350, behavior: 'instant' });")
        await asyncio.sleep(0.3)
        await cdp.evaluate("window.scrollBy({ top: 700, behavior: 'instant' });")
        await asyncio.sleep(0.4)
        card_res = await cdp.evaluate(pinpoint_target_js)

    if card_res and card_res.get("isAdBlocked"):
        logger.critical(f"🛑 [광고 클릭 원천 차단] 타겟으로 조준된 카드가 광고로 감지되었습니다: {card_res.get('reason')} -> 클릭 배제 및 안전 중단")
        return {
            "success": False,
            "status": "AD_CLICK_PREVENTED",
            "error_message": f"타겟 상품이 광고 카드로 감지되어 클릭 배제 ({card_res.get('reason')})"
        }

    if not card_res or not card_res.get("found"):
        result.click_success = False
        result.click_fail_reason = card_res.get("error") if card_res else "TARGET_NOT_FOUND_IN_DOM"
        logger.warning(f"⚠️ [쇼핑탭 DOM 타겟 조준 실패] JS에서는 {result.js_target_rank}위로 확인되었으나 {result.scroll_count}회 스크롤 후에도 DOM 조준 실패: {card_res}")
        return {
            "success": False,
            "status": "NOT_FOUND",
            "error_message": f"쇼핑탭 DOM 타겟 조준 실패 (스크롤 {result.scroll_count}회 진행)"
        }

    target_rank = card_res.get("rank")
    # [정밀 보정] DOM 인덱스 미스매치로 인한 허위 1위 방지: 사전 검증된 __NEXT_DATA__ 순위(js_target_rank) 최우선 보존
    if result.js_target_rank and (target_rank is None or (target_rank == 1 and result.js_target_rank > 1)):
        target_rank = result.js_target_rank
    elif not target_rank and result.js_target_rank:
        target_rank = result.js_target_rank

    result.shopping_rank = target_rank
    result.shopping_page = 1
    result.match_type = "SHOPPING"
    result.search_type = "msearch"
    result.click_source = "SHOPPING_TAB (msearch.shopping.naver.com)"
    result.click_action = "SHOPPING_1P_TARGET"
    detected_mall = card_res.get("mallName") or (target_info.get("mallName") if target_info else None)
    if detected_mall:
        result.store_name = detected_mall

    click_x = card_res["clickX"]
    click_y = card_res["clickY"]
    current_page_url = card_res.get("currentUrl") or ""
    matched_selector = card_res.get("matchedSelector") or ""
    element_info = card_res.get("elementInfo") or {}

    # [사용자 요구사항]: 클릭 직전 타겟 상품의 수집된 전체 정보 JSON 구성 및 로그 기록
    product_data = {
        "nv_mid": card_res.get("nvMid") or task.nv_mid,
        "product_name": card_res.get("title") or (target_info.get("title") if target_info else ""),
        "mall_name": result.store_name or "-",
        "rank": target_rank,
        "page": 1,
        "is_catalog": bool(card_res.get("isCatalog", False)),
        "is_ad": False,
        "current_page_url": current_page_url,
        "matched_selector": matched_selector,
        "element_tag": element_info.get("tagName"),
        "element_class": element_info.get("className"),
        "element_href": element_info.get("href"),
        "element_text": element_info.get("text"),
        "rendered_count": card_res.get("renderedCount"),
        "raw_next_data": target_info
    }

    logger.info("=================================================================================")
    logger.info(f"📍 [클릭 직전 URL] {current_page_url}")
    logger.info(f"🔍 [조준 셀렉터] {matched_selector}")
    logger.info(f"🏷️ [클릭 대상 엘리먼트] Tag=<{element_info.get('tagName')}> | Class='{element_info.get('className')}' | Href='{element_info.get('href')}'")
    logger.info(f"📦 [수집된 상품 정보 전체 JSON]:\n{json.dumps(product_data, ensure_ascii=False, indent=2)}")
    logger.info("=================================================================================")

    # [하드웨어급 프리터치 인터락] 실물 터치 직전 좌표(x, y) 상의 엘리먼트 2차 광고 검증 (DOM 속성 단독)
    interlock_js = f"""
    (() => {{
        const el = document.elementFromPoint({click_x}, {click_y});
        if (!el) return {{ ok: true }};
        const adEl = el.closest('a[href*="adcr."], a[href*="ader."], [class*="ad_badge"], [class*="adbadge"], [class*="ad_icon"], [data-ad], [data-nlog-area*="ad"]');
        if (adEl) {{
            return {{ ok: false, reason: "INTERLOCK_DETECTED_AD_ELEMENT", tag: adEl.tagName, class: adEl.className }};
        }}
        const card = el.closest('div[class^="product_list_item__"], li');
        if (card) {{
            const cCls = (card.className || '').toLowerCase();
            if (cCls.includes('ad_') || cCls.includes('_ad') || cCls.includes('sponsor') || cCls.includes('epl')) {{
                return {{ ok: false, reason: "INTERLOCK_DETECTED_AD_CLASS", class: cCls }};
            }}
            const nlog = card.getAttribute('data-nlog-params') || '';
            if (nlog.includes('"is_ad":true') || nlog.includes('"is_ad":"true"') || nlog.includes('"isAd":true')) {{
                return {{ ok: false, reason: "INTERLOCK_DETECTED_AD_NLOG" }};
            }}
        }}
        return {{ ok: true }};
    }})()
    """
    interlock_res = await cdp.evaluate(interlock_js)
    if interlock_res and not interlock_res.get("ok"):
        logger.critical(f"🛑 [하드웨어급 프리터치 인터락 작동] 쇼핑탭 좌표 ({click_x:.1f}, {click_y:.1f})가 광고로 감지되어 터치를 원천 중단합니다! 이유: {interlock_res}")
        if traffic_logger:
            traffic_logger.record_event("AD_INTERLOCK_ABORT", f"Abort touch on ad in shop tab: {interlock_res}", interlock_res)
        return {
            "success": False,
            "status": "AD_CLICK_PREVENTED",
            "error_message": f"프리터치 인터락에 의해 광고 터치 원천 차단: {interlock_res}"
        }

    # 4. 조준 완료 및 증빙 캡처
    result.touch_coordinates = {"x": click_x, "y": click_y}
    save_stage_screenshot(device_id, "target_found", task.task_id, output_dir)
    logger.info(f"🎯 [쇼핑탭 타겟 조준 완료] 좌표: ({click_x:.1f}, {click_y:.1f}) | 변위: {card_res.get('offsetPx')}px | 제목: '{card_res.get('title')}'")

    # 5. 리얼 터치 발송 - 상품 클릭은 지터 유지 (use_jitter=True)
    touch_res = await cdp_real_touch(
        cdp=cdp,
        device_id=device_id,
        task_id=task.task_id,
        action_name="SHOPPING_1P_TARGET",
        click_x=click_x,
        click_y=click_y,
        output_dir=output_dir,
        capture_screenshot=True,
        use_jitter=True
    )
    result.before_click_screenshot = touch_res.get("capture_path")
    result.click_success = touch_res.get("success", False)
    result.click_action = "SHOPPING_1P_TARGET"
    if not result.click_success:
        result.click_fail_reason = touch_res.get("reason", "SHOPPING_CLICK_FAILED")
    logger.info(f"🎯 [쇼핑탭 클릭 실행 결과] 성공={result.click_success} | 좌표=({click_x:.1f}, {click_y:.1f}) | 지터={touch_res.get('use_jitter')} | 누적스크롤={result.scroll_count}회")

    result.action_history.append({
        "time": time.time(),
        "action": "SHOPPING_1P_TARGET",
        "target_rank": target_rank,
        "coord": {"x": click_x, "y": click_y},
        "current_url": current_page_url,
        "matched_selector": matched_selector,
        "product_data": product_data,
        "details": touch_res
    })
    result.jitter_history.append({
        "time": time.time(),
        "action": "SHOPPING_1P_TARGET",
        "use_jitter": touch_res.get("use_jitter", True),
        "hold_ms": touch_res.get("hold_ms"),
        "pre_touch_delay": touch_res.get("pre_touch_delay")
    })
    if traffic_logger:
        traffic_logger.record_event("TARGET_TOUCH", f"Touch Shopping Target: nv_mid={task.nv_mid}", {
            "x": click_x,
            "y": click_y,
            "action": "SHOPPING_1P_TARGET",
            "page_url": current_page_url,
            "matched_selector": matched_selector,
            "element_info": element_info,
            "product_data": product_data
        })

    is_catalog = bool(card_res.get("isCatalog", False))
    if is_catalog:
        if task.compare_id or getattr(task, "target_id", None):
            logger.info("📦 [카탈로그 상품 지침] 쇼핑탭 카탈로그 카드 클릭 완료 -> Step 6 카탈로그 판매처 탐색으로 인계")
            return {
                "success": True,
                "status": "CATALOG_ENTRY",
                "is_catalog": True,
                "touch_coords": {"x": click_x, "y": click_y}
            }
        else:
            logger.info("📦 [카탈로그 상품 지침] 쇼핑탭 판매처 묶음 상품 클릭 완료 -> 카탈로그 상세 탐색 미지정 시 즉시 성공 처리")
            result.status = "SUCCESS"
            result.success = True
            return {
                "success": True,
                "status": "SUCCESS",
                "is_catalog": True,
                "touch_coords": {"x": click_x, "y": click_y}
            }

    return {
        "success": True,
        "status": "TARGET_CLICKED",
        "is_catalog": False,
        "touch_coords": {"x": click_x, "y": click_y}
    }
