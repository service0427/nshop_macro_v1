#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/pipeline/steps/step2_serp.py

Step 2: Unified Search (SERP) Exploration & Pinpoint Strike
- Fast-Fail Gate: Checks pagedSlot. If absent, keyword has no shopping presence (e.g. '박보검') -> Fail immediately.
- SERP Warmup: 2~3 downward swipes -> 必ず return to Home (y=0).
- Section Scoping: Extracts section from naver.search.section.main (shp_*) and queries strictly within section container.
- Slot Detection: Matches FIRST-occurring slot for target nv_mid across slider pages.
- CDP Direct Exposure: Exposes card via scrollIntoView/Flicking moveTo without clicking slider arrows or horizontal swipes.
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
from typing import Dict, Any, Optional

from config.settings import TIMINGS
from src.browser.cdp_client import AsyncCDPClient
from src.pipeline.models import TaskInput, TaskResult
from src.pipeline.utils.serp_parser import check_serp_paged_slot
from src.pipeline.utils.cdp_touch import cdp_real_touch, save_stage_screenshot
from src.device.adb_controller import fast_check_native_login_or_captcha

logger = logging.getLogger("ConveyorExecutor")


async def execute_serp_stage(
    task: TaskInput,
    result: TaskResult,
    cdp: AsyncCDPClient,
    device_id: str,
    output_dir: Optional[str] = None,
    traffic_logger: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Executes Step 2: SERP exploration and optional target strike.
    Returns:
    {
        "status": "SUCCESS" | "NOT_SHOPPING_KEYWORD" | "SERP_NOT_FOUND" | "ERROR",
        "hit_on_serp": bool,
        "is_catalog": bool,
        "error_message": Optional[str]
    }
    """
    t0_serp = time.time()

    # 1. Fast-Fail Gate: shp_ 쇼핑 섹션 및 pagedSlot 로딩 대기 (최대 30초 관대 완충)
    logger.info("⏳ [통합검색 검증] shp_ 쇼핑 섹션 및 pagedSlot 로딩 대기 중 (최대 30초 관대 완충)...")
    has_shp_section = False
    initial_check = {}
    serp_wait_steps = max(1, int(TIMINGS.SERP_SECTION_MAX_WAIT / TIMINGS.SERP_SECTION_POLL_INTERVAL))
    for wait_iter in range(serp_wait_steps):  # QoS 대역폭 저하 및 토글 초기 지연 대비 완충 (30초)
        await asyncio.sleep(TIMINGS.SERP_SECTION_POLL_INTERVAL)

        # 네이티브 로그인/캡차 즉시 감지 (50~100ms Fast-Fail)
        is_blocked, blk_type, reason = fast_check_native_login_or_captcha(device_id)
        if is_blocked:
            logger.warning(f"🚨 [통합검색 검증 중 네이티브 {blk_type} 감지] {reason}")
            try:
                save_stage_screenshot(device_id, blk_type.lower(), task.task_id, output_dir)
            except Exception:
                pass
            return {
                "status": blk_type,
                "hit_on_serp": False,
                "is_catalog": False,
                "error_message": reason
            }

        compare_target = task.compare_id or getattr(task, "target_id", None) or ""
        initial_check = await check_serp_paged_slot(cdp, target_mid=task.nv_mid, target_rank=task.target_rank, compare_id=compare_target)
        if wait_iter % 4 == 0:
            logger.info(f"🔍 [SERP 폴링 {wait_iter}] check_res: has_shp={initial_check.get('has_shp_section')}, sec={initial_check.get('section_name')}, reason={initial_check.get('reason')}, err={initial_check.get('error')}")
            if wait_iter >= 4 and not initial_check.get("has_shp_section"):
                try:
                    await cdp.evaluate("window.scrollBy(0, 600);")
                except Exception:
                    pass
        if initial_check.get("is_network_error"):
            logger.warning(f"🌐 [통합검색 네트워크 단절 감지] {initial_check.get('error_message')}")
            if wait_iter == serp_wait_steps - 1:
                return {
                    "status": "NETWORK_ERROR",
                    "hit_on_serp": False,
                    "is_catalog": False,
                    "error_message": initial_check.get("error_message")
                }

        if initial_check.get("has_shp_section"):
            has_shp_section = True
            sec_name = initial_check.get("section_name")
            has_ps = initial_check.get("has_paged_slot")
            if has_ps or wait_iter >= 3:
                logger.info(f"⚡ [통합검색 shp_ 섹션 포착 완료] 섹션: '{sec_name}' | pagedSlot 존재: {has_ps} (소요: {(wait_iter+1)*TIMINGS.SERP_SECTION_POLL_INTERVAL:.1f}초)")
                break

        # [Fast-Fail 조기 판정] 네이버 메타데이터(secMain)와 DOM이 완전히 로드되고 최소 완충 대기 후에도 shp_ 섹션이 없으면 스크롤 후 최종 탈출
        if initial_check.get("is_definitive_no_shp") and wait_iter >= 25:
            try:
                await cdp.evaluate("window.scrollBy(0, 1200);")
            except Exception:
                pass
            await asyncio.sleep(0.4)
            recheck = await check_serp_paged_slot(cdp, target_mid=task.nv_mid, target_rank=task.target_rank, compare_id=compare_target)
            if recheck.get("has_shp_section"):
                initial_check = recheck
                has_shp_section = True
                sec_name = initial_check.get("section_name")
                has_ps = initial_check.get("has_paged_slot")
                logger.info(f"⚡ [통합검색 shp_ 섹션 포착 완료 (스크롤 후)] 섹션: '{sec_name}' | pagedSlot 존재: {has_ps}")
                break
            logger.info(f"⚡ [통검 메타데이터 분석 완료] 네이버 검색 결과에 쇼핑 섹션(shp_*)이 존재하지 않음 확정 (소요: {(wait_iter+1)*TIMINGS.SERP_SECTION_POLL_INTERVAL:.1f}초)")
            break

    # [사용자 지침 1] section에서 shp_가 없으면 쇼핑 무관 키워드 -> 즉시 종료
    if not has_shp_section:
        if initial_check.get("is_network_error"):
            return {
                "status": "NETWORK_ERROR",
                "hit_on_serp": False,
                "is_catalog": False,
                "error_message": initial_check.get("error_message")
            }
        logger.error(f"🚨 [쇼핑 무관 키워드 Fast-Fail] 키워드 '{task.keyword}'는 통합검색에 쇼핑 섹션(shp_*)이 존재하지 않습니다.")
        return {
            "status": "NOT_SHOPPING_KEYWORD",
            "hit_on_serp": False,
            "is_catalog": False,
            "error_message": f"쇼핑과 무관한 키워드 (통합검색 shp_* 미존재): '{task.keyword}'"
        }

    # 2. [불필요한 워밍업 스크롤 완전 배제] naver.search.ext 객체 기반 즉시 직행 판정
    # 통합검색 pagedSlot에 타겟 상품이 없거나 있으면 이미 initial_check에서 확정되므로
    # 화면을 흔들고 시간을 낭비하는 하단 헛스크롤/Home복귀를 일체 배제하고 즉시 분기합니다.
    serp_data = initial_check
    sec_name = serp_data.get("section_name") or "shp_tli"
    has_paged_slot = serp_data.get("has_paged_slot", False)
    target = serp_data.get("target")

    # [사용자 지침 2] shp_ 섹션은 있으나 pagedSlot이 아니면 -> 고민 없이 즉시 쇼핑탭으로 이동하여 탐색 (워밍업 없이 직행)
    if not has_paged_slot:
        logger.info(f"🚀 [비표준 카테고리/pagedSlot 부재] 섹션: '{sec_name}' (pagedSlot 미존재) -> 사용자 지침에 따라 즉시 쇼핑탭으로 이동")
        return {
            "status": "SERP_NOT_FOUND",
            "hit_on_serp": False,
            "has_more_pages": True,
            "section_name": sec_name,
            "route_to_shop_tab": True
        }

    # [사용자 지침 3] newshopping.shopping.pagedSlot이 있는 일반 쇼핑 키워드
    # 타겟이 없으면 워밍업 일체 없이 0초 만에 쇼핑더보기로 직행!
    if not target:
        result.js_target_found = False
        result.js_total_count = serp_data.get("total_slots", 0)
        result.js_search_type = "SERP"
        total_pages = serp_data.get("total_pages", 1)

        # [절대 철칙 4] total_pages <= 1 (단일 페이지): 추가 상품이 없으므로 더보기 이동 없이 즉시 NOT_FOUND 종료!
        if total_pages <= 1:
            logger.info(f"🛑 [단일 페이지 슬롯] total_pages={total_pages} <= 1 (추가 페이지 없음) -> 불필요한 더보기 터치 배제 및 즉시 NOT_FOUND 안전 종료")
            return {
                "status": "NOT_FOUND",
                "hit_on_serp": False,
                "has_more_pages": False,
                "section_name": sec_name,
                "route_to_shop_tab": False,
                "error_message": f"단일 페이지 쇼핑 슬롯({total_pages}p) 내 타겟 미노출 (추가 상품 없음)"
            }

        logger.info(f"🔍 [SERP JS 타겟 탐색] 발견=False | 슬롯수={result.js_total_count}개 | 페이지수={total_pages}p > 1 -> 쇼핑탭 이동 필요 (워밍업 없이 직행)")
        return {
            "status": "SERP_NOT_FOUND",
            "hit_on_serp": False,
            "has_more_pages": True,
            "section_name": sec_name,
            "route_to_shop_tab": True
        }

    # 4. [타겟 포착] 통합검색 가로 슬라이더에 타겟 상품 존재
    target_rank = target.get("rank")
    target_mid = target.get("nvMid") or task.nv_mid
    target_title = target.get("productName", "")
    target_p_idx = target.get("pageIndex", 0)
    is_catalog = bool(target.get("isCatalog", False))

    result.js_target_found = True
    result.js_target_rank = target_rank
    result.js_total_count = serp_data.get("total_slots", 0)
    result.js_search_type = "SERP"
    logger.info(f"🎯 [통합검색 타겟 포착!] {target_rank}위 ({target.get('matchType')}) | '{target_title}' | 섹션: '{sec_name}' | 슬롯페이지: {target_p_idx+1}p")
    logger.info(f"🔍 [SERP JS 타겟 탐색] 발견=True | 순위={target_rank}위 | 전체슬롯={result.js_total_count}개 | 제목='{target_title}'")

    # [사용자 지침 2026-10-14] 통합검색 결과에 상품이 있는 경우:
    # 사람처럼 자연스러운 둘러보기 워밍업 스크롤(아래로 1~2회 스와이프 후 둘러보고 복귀)을 수행한 뒤 클릭!
    # (단, 쇼핑더보기로 넘어가려고 한다면 워밍업 없이 직행)
    logger.info("👀 [SERP 타겟 포착 후 인간형 워밍업] 사람처럼 자연스럽게 아래로 둘러보기 스와이프 및 쇼핑 영역 복귀 수행...")
    warmup_count = random.randint(1, 2)
    for w_idx in range(warmup_count):
        sx = random.randint(450, 600)
        sy1 = random.randint(1700, 1900)
        sy2 = random.randint(600, 800)
        dur = random.randint(350, 480)
        subprocess.run(f"adb -s {device_id} shell input swipe {sx} {sy1} {sx} {sy2} {dur}", shell=True, timeout=5.0)
        # 실제 사용자가 검색결과 둘러보는 자연스러운 인지 체류 (1.0 ~ 1.4초)
        await asyncio.sleep(random.uniform(1.0, 1.4))

    # 상단 쇼핑 영역으로 자연스럽게 반동 복귀 스와이프
    rx = random.randint(450, 600)
    ry1 = random.randint(650, 850)
    ry2 = random.randint(1650, 1850)
    dur = random.randint(350, 480)
    subprocess.run(f"adb -s {device_id} shell input swipe {rx} {ry1} {rx} {ry2} {dur}", shell=True, timeout=5.0)
    # 복귀 후 타겟 상품 발견 및 시선 안착 지연 (0.8 ~ 1.2초)
    await asyncio.sleep(random.uniform(0.8, 1.2))

    # 5. [사용자 엄명: CDP 직접 노출 (가로 슬라이더/버튼 클릭 절대 금지)]
    # - naver.search.section.main 기반 섹션 컨테이너 내부로 querySelector 범위 한정
    # - element.scrollIntoView({ block: 'center', inline: 'center' }) 로 화면 중앙 직접 노출
    # - 스크롤바 위아래 랜덤 1~50px 이동
    expose_and_measure_js = f"""
    (async () => {{
        try {{
            const targetMid = "{target_mid}";
            const secName = "{sec_name}";
            const targetPageIdx = {target_p_idx};

            // 1. 섹션 컨테이너 특정 (섹션명 우선 포함)
            let sec = null;
            if (secName) {{
                sec = document.querySelector(`#${{secName}}_root, #${{secName}}, section[data-slog-container*="${{secName}}"], section[class*="_root_${{secName}}"]`);
            }}
            if (!sec) {{
                sec = document.querySelector('section[class*="_root_shp_"], section[data-slog-container*="shp"], div[class*="api_subject_bx"][data-slog-container*="shp"], [id*="shp_"][id*="_root"]') || document.body;
            }}

            // 먼저 쇼핑 섹션을 화면 중앙으로 배치
            if (sec && typeof sec.scrollIntoView === 'function') {{
                sec.scrollIntoView({{ block: 'center', inline: 'nearest', behavior: 'instant' }});
                await new Promise(r => setTimeout(r, 100));
            }}

            // [철칙 준수] 인위적인 JS nextBtn.click() 완전 배제 - DOM에 렌더링된 카드 직접 정밀 탐색

            // [절대 철칙 1] 광고 정밀 검증기 (CPC / 파워링크 / 쇼핑검색광고 100% 원천 차단 - DOM 속성 단독)
            const isAdCard = (el) => {{
                if (!el) return false;
                // 1. Ad links (네이버 공식 광고 링크)
                if (el.querySelector('a[href*="adcr."], a[href*="/adcr/"], a[href*="ader."], a[href*="powerlink"], a[href*="ad.search"]')) {{
                    return true;
                }}
                // 2. nlog attributes
                const nlogArea = (el.getAttribute('data-nlog-area') || '').toLowerCase();
                if (nlogArea.startsWith('ad') || nlogArea.includes('.ad.') || nlogArea.includes('epl') || nlogArea.includes('pwl')) {{
                    return true;
                }}
                const nlogParams = el.getAttribute('data-nlog-params') || '';
                if (nlogParams.includes('"is_ad":true') || nlogParams.includes('"is_ad":"true"') || nlogParams.includes('"isAd":true')) {{
                    return true;
                }}
                // 3. Container attributes
                const slog = (el.getAttribute('data-slog-container') || el.closest('[data-slog-container]')?.getAttribute('data-slog-container') || '').toLowerCase();
                if (slog.includes('epl') || slog.includes('_ad') || slog.includes('ad_') || slog.includes('power')) {{
                    return true;
                }}
                // 4. Class names
                const cls = ((el.className || '') + ' ' + Array.from(el.querySelectorAll('[class]')).map(c => c.className).join(' ')).toLowerCase();
                if (/(^|\\s|_|-)(ad_badge|adbadge|ad_icon|adicon|ad_item|aditem|commercial_ad|ad_product|sponsor)($|\\s|_|-)/.test(cls)) {{
                    return true;
                }}
                if (el.querySelector('[class*="ad_badge"], [class*="adbadge"], [class*="ad_icon"], [data-ad]')) {{
                    return true;
                }}
                return false;
            }};

            // 3. 카드 매칭 (DOM 렌더링 완료 대기)
            let matchedLink = null;
            let matchedCard = null;
            let matchedCriteria = "";

            for (let retry = 0; retry < 5; retry++) {{
                const searchRoot = sec || document;
                const prodLinks = Array.from(searchRoot.querySelectorAll('a[href*="cr3.shopping"], a[href*="searchGate"], a[data-nlog-area*="item"], a[data-nlog-area*="superitem"], a[data-nlog-area*="out"]')).filter(a => {{
                    const h = (a.href || '').toLowerCase();
                    const area = (a.getAttribute('data-nlog-area') || '').toLowerCase();
                    // 광고 배제
                    if (h.includes('adcr') || h.includes('ader') || h.includes('powerlink') || h.includes('ad.search') || area.includes('ad') || area.includes('epl') || area.includes('pwl')) return false;
                    // 필터 칩 내부 배제
                    if (a.closest('div[class*="filter"], ul[role="tablist"], div[class*="chip"], nav, header')) return false;
                    return true;
                }});

                for (let a of prodLinks) {{
                    const h = a.href || '';
                    const nlog = a.getAttribute('data-nlog-params') || '';

                    // [광고 1차 차단]: data-nlog-params 내부 is_ad 플래그 검사
                    let isAdFlag = false;
                    try {{
                        const p = JSON.parse(nlog);
                        if (p.is_ad === true || p.is_ad === 'true' || p.isAd === true || (typeof p.sourceType === 'string' && p.sourceType.includes('AD')) || p.ad === true) {{
                            isAdFlag = true;
                        }}
                    }} catch(e) {{}}
                    if (isAdFlag) continue;

                    // [광고 2차 차단]: 카드 컨테이너 검사
                    const candidateCard = a.closest('li, div[class*="product_info_main"], div[class*="product_item"], div[class*="card"], div[class*="product_list_item"]') || a;
                    if (isAdCard(candidateCard)) continue;

                    let isMatch = false;
                    if (targetMid && (h.includes(targetMid) || nlog.includes(targetMid))) {{
                        isMatch = true;
                    }} else {{
                        try {{
                            const p = JSON.parse(nlog);
                            if (targetMid && String(p.content_id || '') === targetMid) {{
                                isMatch = true;
                            }}
                        }} catch(e) {{}}
                    }}

                    if (isMatch) {{
                        matchedLink = a;
                        matchedCard = candidateCard;
                        matchedCriteria = `cr3/searchGate link with targetMid='${{targetMid}}' (href='${{h.slice(0, 60)}}')`;
                        break;
                    }}
                }}

                if (matchedCard) break;
                await new Promise(r => setTimeout(r, 150));
            }}

            if (!matchedCard) {{
                return {{ found: false, reason: "CARD_NOT_IN_DOM" }};
            }}

            // [광고 3차 최종 차단] 선택된 matchedCard 최종 검증
            if (isAdCard(matchedCard)) {{
                return {{ found: false, isAdBlocked: true, reason: "MATCHED_CARD_IS_AD" }};
            }}

            const winH = window.innerHeight || 800;
            const winW = window.innerWidth || 360;
            const SAFE_TOP = 110;
            const SAFE_BOTTOM = winH - 85;

            // [코치마크/가림막 툴팁 원천 제거]
            try {{
                document.querySelectorAll('div[class*="tooltip"], div[class*="coach"], div[class*="guide"], div[class*="balloon"]').forEach(el => {{ try {{ el.remove(); }} catch(ign) {{}} }});
            }} catch(e) {{}}

            // 4. 타겟 카드 뷰포트 위치 검사 (이미 안전 영역에 완벽히 들어와 있으면 불필요한 scrollIntoView 생략)
            let offsetPx = 0;
            const initRect = matchedCard.getBoundingClientRect();
            if (initRect.top < SAFE_TOP || initRect.bottom > SAFE_BOTTOM) {{
                matchedCard.scrollIntoView({{ block: 'center', inline: 'center', behavior: 'instant' }});
                // [사용자 지침] 스크롤바 위아래 랜덤 1~50px 미세 이동
                const offsetDir = Math.random() < 0.5 ? -1 : 1;
                offsetPx = offsetDir * (Math.floor(Math.random() * 50) + 1);
                window.scrollBy({{ top: offsetPx, behavior: 'instant' }});
            }}

            // 5. 클릭 대상: Chromium Blink DOM querySelector 단독 타겟팅 (제목 링크 우선, 몰/리뷰 배제)
            const clickEl = matchedCard.querySelector('a[data-nlog-area*="item"], a[data-nlog-area*="title"], a[class*="tit"], [class*="product_info_tit"] a, [class*="title"] a, a[href*="cr3.shopping"], a[href*="products/"]') ||
                            matchedCard.querySelector('a[class*="product_link_title"], a[class*="product_title"]') ||
                            matchedCard.querySelector('a[class*="product_link"]') ||
                            matchedCard.querySelector('strong a, a:not([class*="mall"]):not([class*="seller"])') ||
                            matchedLink ||
                            matchedCard.querySelector('a') ||
                            matchedCard;

            // [광고 4차 차단] clickEl 자체 검증
            if (isAdCard(clickEl)) {{
                return {{ found: false, isAdBlocked: true, reason: "CLICK_EL_IS_AD" }};
            }}

            let r = clickEl.getBoundingClientRect();
            if (r.top < SAFE_TOP) {{
                window.scrollBy({{ top: r.top - SAFE_TOP - 10, behavior: 'instant' }});
                r = clickEl.getBoundingClientRect();
            }} else if (r.bottom > SAFE_BOTTOM) {{
                window.scrollBy({{ top: r.bottom - SAFE_BOTTOM + 10, behavior: 'instant' }});
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

            const randXRatio = sampleGaussian(0.40, 0.12, 0.15, 0.75);
            const randYRatio = sampleGaussian(0.50, 0.10, 0.25, 0.75);

            let clickX = r.left + Math.min(r.width * randXRatio, 180);
            let clickY = r.top + r.height * randYRatio;
            clickX = Math.max(25.0, Math.min(clickX, winW - 25.0));
            clickY = Math.max(SAFE_TOP + 10.0, Math.min(clickY, SAFE_BOTTOM - 10.0));

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
                    tagName: matchedCard.tagName,
                    id: matchedCard.id || '',
                    className: matchedCard.className || '',
                    outerHtmlPreview: (matchedCard.outerHTML || '').slice(0, 200)
                }},
                clickX: Math.round(clickX * 10) / 10,
                clickY: Math.round(clickY * 10) / 10,
                title: (clickEl.innerText || '').trim().slice(0, 40),
                offsetPx: offsetPx,
                isCatalog: {str(is_catalog).lower()}
            }};
        }} catch(e) {{
            return {{ found: false, error: e.toString() }};
        }}
    }})()
    """
    res = await cdp.evaluate(expose_and_measure_js)
    if not res or not isinstance(res, dict) or not res.get("found"):
        if res and res.get("isAdBlocked"):
            logger.critical(f"🛑 [광고 클릭 원천 차단] 타겟으로 조준된 카드가 광고로 감지되었습니다: {res.get('reason')} -> 클릭 배제 및 안전 중단")
            return {
                "status": "AD_CLICK_PREVENTED",
                "hit_on_serp": False,
                "is_catalog": False,
                "error_message": f"광고 상품 조준 감지 ({res.get('reason')}) -> 철칙 1에 의해 클릭 원천 차단"
            }
        logger.warning(f"⚠️ [SERP DOM 조준 실패] pagedSlot에는 있었으나 DOM 렌더링 카드 조준 실패: {res}")
        return {
            "status": "SERP_NOT_FOUND",
            "hit_on_serp": False,
            "is_catalog": is_catalog
        }

    click_x = res["clickX"]
    click_y = res["clickY"]
    current_page_url = res.get("currentUrl") or ""
    matched_selector = res.get("matchedSelector") or ""
    element_info = res.get("elementInfo") or {}

    # [사용자 요구사항]: 클릭 직전 타겟 상품의 수집된 전체 정보 JSON 구성 및 로그 기록
    product_data = {
        "nv_mid": target_mid,
        "product_name": target_title,
        "mall_name": target.get("mallName") or result.store_name or "-",
        "rank": target_rank,
        "page_index": target_p_idx,
        "is_catalog": is_catalog,
        "is_ad": False,
        "current_page_url": current_page_url,
        "matched_selector": matched_selector,
        "element_tag": element_info.get("tagName"),
        "element_class": element_info.get("className"),
        "element_href": element_info.get("href"),
        "element_text": element_info.get("text"),
        "raw_slot_data": target.get("rawSlotData")
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
        const card = el.closest('li, div[class*="product_info_main"], div[class*="product_item"], div[class*="card"], div[class*="product_list_item"]');
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
        logger.critical(f"🛑 [하드웨어급 프리터치 인터락 작동] 좌표 ({click_x:.1f}, {click_y:.1f})가 광고로 감지되어 터치를 원천 중단합니다! 이유: {interlock_res}")
        if traffic_logger:
            traffic_logger.record_event("AD_INTERLOCK_ABORT", f"Abort touch on ad: {interlock_res}", interlock_res)
        return {
            "status": "AD_CLICK_PREVENTED",
            "hit_on_serp": False,
            "is_catalog": False,
            "error_message": f"프리터치 인터락에 의해 광고 터치 원천 차단: {interlock_res}"
        }

    # 6. target_found 증빙 캡처
    result.target_found_screenshot = save_stage_screenshot(device_id, "target_found", task.task_id, output_dir)

    result.touch_coordinates = {"x": click_x, "y": click_y}
    result.serp_rank = target_rank
    result.match_type = "SERP"
    result.search_type = "m.search"
    result.click_source = "SERP (m.search.naver.com)"
    result.click_action = "SERP_ORGANIC_TARGET"
    if target.get("mallName"):
        result.store_name = target.get("mallName")
    result.target_type = "CATALOG" if is_catalog else "PROD"
    logger.info(f"🎯 [SERP 타겟 조준 완료] 좌표: ({click_x:.1f}, {click_y:.1f}) | 변위: {res.get('offsetPx')}px | 몰: '{result.store_name or '-'}' | 제목: '{res.get('title')}'")

    # 7. CDP 리얼 터치 발송
    touch_res = await cdp_real_touch(
        cdp=cdp,
        device_id=device_id,
        task_id=task.task_id,
        action_name="SERP_ORGANIC_TARGET",
        click_x=click_x,
        click_y=click_y,
        output_dir=output_dir,
        capture_screenshot=True,
        use_jitter=True
    )
    result.before_click_screenshot = touch_res.get("capture_path")
    result.click_success = touch_res.get("success", False)
    result.click_action = "SERP_ORGANIC_TARGET"
    if not result.click_success:
        result.click_fail_reason = touch_res.get("reason", "SERP_CLICK_FAILED")
    logger.info(f"🎯 [SERP 클릭 실행 결과] 성공={result.click_success} | 좌표=({click_x:.1f}, {click_y:.1f}) | 지터={touch_res.get('use_jitter')}")

    result.action_history.append({
        "time": time.time(),
        "action": "SERP_ORGANIC_TARGET",
        "target_rank": target_rank,
        "coord": {"x": click_x, "y": click_y},
        "current_url": current_page_url,
        "matched_selector": matched_selector,
        "product_data": product_data,
        "details": touch_res
    })
    result.jitter_history.append({
        "time": time.time(),
        "action": "SERP_ORGANIC_TARGET",
        "use_jitter": touch_res.get("use_jitter", True),
        "hold_ms": touch_res.get("hold_ms"),
        "pre_touch_delay": touch_res.get("pre_touch_delay")
    })
    if traffic_logger:
        traffic_logger.record_event("TARGET_TOUCH", f"Touch SERP Target: nv_mid={task.nv_mid}", {
            "x": click_x,
            "y": click_y,
            "action": "SERP_ORGANIC_TARGET",
            "page_url": current_page_url,
            "matched_selector": matched_selector,
            "element_info": element_info,
            "product_data": product_data
        })

    # [사용자 엄명 정책] 판매처로 묶인 상품(카탈로그) 중 compare_id가 없는 단독 카탈로그 타겟만 즉시 성공 종결
    if is_catalog and not (task.compare_id or getattr(task, "target_id", None)):
        logger.info("📦 [카탈로그 상품 지침] 판매처 묶음 상품 클릭 완료 -> 사용자 정책에 따라 성공(SUCCESS)으로 처리")
        result.status = "SUCCESS"
        result.success = True

    return {
        "status": "SUCCESS" if (is_catalog and not (task.compare_id or getattr(task, "target_id", None))) else "TARGET_CLICKED",
        "hit_on_serp": True,
        "is_catalog": is_catalog,
        "touch_coords": {"x": click_x, "y": click_y}
    }
