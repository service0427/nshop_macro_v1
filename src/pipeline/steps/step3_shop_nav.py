#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/pipeline/steps/step3_shop_nav.py

Step 3: Shopping Navigation Module
- 실제 모바일 사용자처럼 통합검색 내 쇼핑 섹션 내부의 '상품 더보기' 버튼(.more)을 화면에서 직접 실물 터치 (CDP Real Touch)
- 📌 [절대 철칙 9] JavaScript el.click() 영구 금지! 오직 getBoundingClientRect() 좌표 기반 CDP Input.dispatchTouchEvent만 사용!
- 사유: el.click() 시 터치 이벤트/WTM/nlog 비콘이 누락되어 FDS에 비정상 매크로로 탐지되어 로그인 화면/캡차가 유발됨.
"""

import time
import asyncio
import logging
from typing import Dict, Any, Optional

from config.settings import TIMINGS
from src.browser.cdp_client import AsyncCDPClient
from src.pipeline.models import TaskInput, TaskResult
from src.core.profile_generator import build_shopping_intent_url
from src.device.adb_controller import start_intent
from src.pipeline.utils.cdp_touch import cdp_real_touch, save_stage_screenshot
from src.pipeline.utils.transition_waiter import wait_for_transition, TransitionType

logger = logging.getLogger("ConveyorExecutor")


async def execute_shop_navigation(
    task: TaskInput,
    result: TaskResult,
    cdp: AsyncCDPClient,
    device_id: str,
    section_name: Optional[str] = None,
    cdp_port: Optional[int] = None,
    output_dir: Optional[str] = None,
    traffic_logger: Optional[Any] = None
) -> Dict[str, Any]:
    """
    [쇼핑 네비게이션 전용 모듈]
    - 사용자 엄명: 상단 카테고리 [쇼핑] 탭(role="tab") 영구 배제
    - 오직 통합검색 내 오가닉 쇼핑 섹션(shp_*) 내부의 '.more' / '상품 더보기' 버튼만을 탐색하여 실물 터치 (CDP Real Touch)
    - 광고 섹션(shp_epl, 파워링크 등) 100% 원천 배제 및 실물 터치 오염 방지
    - Playwright 스타일 패킷/전환 대기 엔진으로 쇼핑탭 정상 안착 검증
    """
    raw_sec = section_name or "shp"
    # [절대 철칙 1] 광고 섹션(파워링크 등) 명칭 오염 원천 배제
    if any(k in raw_sec.lower() for k in ["_ad", "ad_", "power", "pwl"]):
        logger.warning(f"⚠️ [광고 섹션 배제] 광고 섹션({raw_sec}) 감지 -> 순수 오가닉 쇼핑 섹션으로 정제")
        sec_name = "shp_tli"
    else:
        sec_name = raw_sec

    logger.info(f"🚀 [쇼핑 더보기 전환 진행] 키워드: '{task.keyword}' (섹션: {sec_name}) -> 오가닉 쇼핑섹션 내 .more 탐색")

    # 1. 전환 전 증빙 캡처
    save_stage_screenshot(device_id, "before_shop_nav", task.task_id, output_dir)

    # 2. 오가닉 쇼핑 섹션 내부의 .more / 상품 더보기 버튼 탐색 (광고 섹션 및 document 전역 배제)
    find_more_js = f"""
    (() => {{
        // [절대 철칙 1] 광고 섹션 판별기
        const isAdSectionStr = (s) => {{
            const lower = (s || '').toLowerCase();
            return lower.includes('_ad') || lower.includes('ad_') || lower.includes('pwl') || lower.includes('power');
        }};

        // [AI 검색 배너 및 코치마크/툴팁 원천 제거 - 레이아웃 시프트 및 오클릭 100% 방지]
        try {{
            document.querySelectorAll('a[href*="aitabshop"], a[href*="m_ait"], a[href*="shopping_banner"], .cGTdiNgw, .hbhTlgi0, [class*="ai_tab_banner"], [class*="ait_agent"]').forEach(el => el.remove());
            document.querySelectorAll('div[class*="tooltip"], div[class*="coach"], div[class*="guide"], div[class*="balloon"]').forEach(el => el.remove());
        }} catch(e) {{}}

        // 1. 오가닉 쇼핑 섹션 컨테이너 특정
        const secMain = window.naver?.search?.section?.main;
        let shpSecName = "{sec_name or ''}";
        if (shpSecName && isAdSectionStr(shpSecName)) {{
            shpSecName = '';
        }}

        if (!shpSecName && Array.isArray(secMain)) {{
            for (let s of secMain) {{
                let str = (typeof s === 'string') ? s : (s?.area || s?.id || s?.name || s?.section || '');
                if ((str.includes('shp_') || str.startsWith('shp')) && !isAdSectionStr(str)) {{
                    shpSecName = str.split('*')[0];
                    break;
                }}
            }}
        }} else if (!shpSecName && secMain && typeof secMain === 'object') {{
            const k = Object.keys(secMain).find(k => (k.includes('shp_') || k.startsWith('shp')) && !isAdSectionStr(k));
            if (k) shpSecName = k.split('*')[0];
        }}

        let shpContainer = null;
        if (shpSecName) {{
            shpContainer = document.querySelector(`#${{shpSecName}}_root, #${{shpSecName}}, [data-slog-container*="${{shpSecName}}"], [class*="_root_${{shpSecName}}"], [id*="${{shpSecName}}"]`);
        }}
        if (!shpContainer) {{
            shpContainer = document.querySelector('[class*="_root_shp_"]:not([class*="ad"]), [data-slog-container*="shp"]:not([data-slog-container*="ad"]), div[class*="api_subject_bx"][data-slog-container*="shp"]:not([data-slog-container*="ad"]), [id*="shp_"]:not([id*="ad"]), [data-area*="shp"]');
        }}
        if (!shpContainer) {{
            // 오가닉 쇼핑 내부 요소(data-nlog-area^="shp_")를 통한 컨테이너 역추적
            const shpItem = document.querySelector('[data-nlog-area^="shp_"]:not([data-nlog-area*="ad"]), [data-slog-id^="shp_"]');
            if (shpItem) {{
                shpContainer = shpItem.closest('section, div.api_subject_bx, div[class*="root"], div[class*="bx"]') || shpItem.parentElement;
            }}
        }}

        // [절대 철칙 4 준수] 오가닉 shp_ 접두사 전용 검색 스코프 확정
        const searchScope = shpContainer || document;

        // 2. [Chromium Blink DOM querySelector 단독 정밀 타겟팅]
        // [AI 배너/AI탭 영구 무력화 CSS 쉴드 주입 및 DOM 즉시 파기]
        try {{
            if (!document.getElementById('__nshop_ai_shield')) {{
                const style = document.createElement('style');
                style.id = '__nshop_ai_shield';
                style.innerHTML = `
                    .eA6w58S8, .cGTdiNgw, .hbhTlgi0,
                    [data-nlog-area*="aitab"],
                    [data-nlog-area*="ait"],
                    [data-nlog-area*="cue"],
                    [href*="aitabshop"],
                    [href*="m_ait"],
                    [href*="shopping_banner"],
                    [class*="ai_tab_banner"],
                    [class*="ait_agent"],
                    [role="tab"][href*="m_ait"],
                    [role="tab"][href*="tab.m_ait"] {{
                        display: none !important;
                        height: 0 !important;
                        max-height: 0 !important;
                        overflow: hidden !important;
                        pointer-events: none !important;
                        visibility: hidden !important;
                        position: absolute !important;
                        top: -9999px !important;
                    }}

                    /* [절대 원칙] 네이버 클립 및 동영상 섹션 상호작용 완전 무력화 (오클릭/재생 원천 차단) */
                    [data-nlog-area^="clp_"],
                    [data-nlog-area*="clip"],
                    [data-nlog-area*="video"],
                    [class*="clip_wrap"],
                    [class*="clip_card"],
                    [class*="clip_area"],
                    [class*="video_wrap"],
                    a[href*="clip.naver.com"],
                    a[href*="m.clip.naver.com"],
                    a[href*="naversearchapp://clip"],
                    div#_clip_root,
                    section[id*="clip"] {{
                        pointer-events: none !important;
                    }}
                `;
                (document.head || document.documentElement).appendChild(style);
            }}
            document.querySelectorAll('.eA6w58S8, .cGTdiNgw, .hbhTlgi0, [data-nlog-area*="aitab"], a[href*="aitabshop"], a[href*="m_ait"], a[href*="shopping_banner"], [class*="ai_tab_banner"], [class*="ait_agent"], [role="tab"][href*="m_ait"]').forEach(el => el.remove());
        }} catch(e) {{}}

        const isAiLink = (el) => {{
            if (!el) return false;
            const aTag = el.closest('a') || el;
            const h = (aTag.href || aTag.getAttribute('href') || el.href || el.getAttribute('href') || '').toLowerCase();
            const a = (el.getAttribute('data-nlog-area') || aTag.getAttribute('data-nlog-area') || '').toLowerCase();
            const c = ((el.className || '') + ' ' + (aTag.className || '')).toLowerCase();
            const t = ((el.innerText || '') + ' ' + (aTag.innerText || '')).toLowerCase();
            return h.includes('ait') || h.includes('shopping_banner') || h.includes('banner') || h.includes('cue') ||
                   a.includes('ait') || a.includes('banner') || a.includes('cue') ||
                   c.includes('ait') || c.includes('cgtdingw') || c.includes('hbhtlgi0') || c.includes('ea6w58s8') || c.includes('cue') ||
                   t.includes('ai로') || t.includes('ai탭') || t.includes('ai 검색') || t.includes('ai 브리핑');
        }};

        const isNotMoreBtn = (el) => {{
            if (!el) return true;
            const a = (el.getAttribute('data-nlog-area') || '').toLowerCase();
            const t = ((el.innerText || '') + ' ' + (el.getAttribute('title') || '')).toLowerCase();
            const h = (el.href || el.getAttribute('href') || '').toLowerCase();
            if (a.includes('.mtc') || a.includes('.filter') || a.includes('.sort') || a.includes('law') || a.includes('pw') || a.includes('ad')) return true;
            if (a.startsWith('clp') || a.includes('clip') || a.includes('video')) return true;
            if (h.includes('clip.naver.com') || h.includes('naversearchapp://clip')) return true;
            if (t.includes('로만 검색') || t.includes('원문보기') || t.includes('이전 페이지') || t.includes('다음 페이지') || t.includes('현재') || t.includes('전체')) return true;
            return false;
        }};

        const candidateSelectors = [
            'a[data-nlog-area^="shp_"][data-nlog-area$=".none.more"][href*="shopping.naver.com"]:not([role="tab"])',
            'a[data-nlog-area^="shp_"][data-nlog-area$=".none.more"]:not([data-nlog-area*="pw"]):not([data-nlog-area*="ad"]):not([data-nlog-area*="more2"]):not([role="tab"])',
            'button[data-nlog-area^="shp_"][data-nlog-area$=".none.more"]:not([data-nlog-area*="pw"]):not([data-nlog-area*="ad"]):not([data-nlog-area*="more2"]):not([role="tab"])',
            'a[data-nlog-area^="shp_"][data-nlog-area*="more"][href*="shopping.naver.com"]:not([role="tab"]):not([data-nlog-area*="pw"]):not([data-nlog-area*="ad"])',
            'a[data-nlog-area^="shp_"][data-nlog-area*="more"]:not([data-nlog-area*="pw"]):not([data-nlog-area*="ad"]):not([data-nlog-area*="more2"]):not([role="tab"])',
            'button[data-nlog-area^="shp_"][data-nlog-area*="more"]:not([data-nlog-area*="pw"]):not([data-nlog-area*="ad"]):not([data-nlog-area*="more2"]):not([role="tab"])',
            'a[href*="msearch.shopping.naver.com"][data-nlog-area*="more"]:not([role="tab"]):not([class*="tab"]):not([href*="brand.naver.com"]):not([data-nlog-area*="ad"])'
        ];

        let moreEl = null;
        for (const sel of candidateSelectors) {{
            const list = Array.from(searchScope.querySelectorAll(sel));
            for (const found of list) {{
                if (isAiLink(found) || isNotMoreBtn(found)) continue;
                const h = (found.href || found.getAttribute('href') || '').toLowerCase();
                if (h.includes('brand.naver.com') || h.includes('ader.naver.com') || h.includes('adcr')) continue;
                const r = found.getBoundingClientRect();
                if (r.width >= 50 && r.height >= 18 && r.height <= 95) {{
                    moreEl = found;
                    break;
                }}
            }}
            if (moreEl) break;
        }}

        if (!moreEl && shpContainer) {{
            // 쇼핑 컨테이너 내부에서 더보기 텍스트를 가진 요소 탐색
            const links = Array.from(shpContainer.querySelectorAll('a, button'));
            moreEl = links.find(el => {{
                const txt = (el.innerText || '').trim();
                const role = el.getAttribute('role') || '';
                const area = (el.getAttribute('data-nlog-area') || '').toLowerCase();
                if (role.includes('tab') || area.includes('more2') || area.includes('pw') || area.includes('ad')) return false;
                if (isAiLink(el)) return false;
                if (!txt.includes('더보기')) return false;
                const r = el.getBoundingClientRect();
                return r.width >= 50 && r.height >= 18 && r.height <= 95;
            }});
        }}

        if (!moreEl) {{
            // 폴백: 쇼핑 섹션 내 텍스트에 '더보기'가 포함되고 정상 버튼 크기인 링크 검색
            const allLinks = Array.from(document.querySelectorAll('a, button'));
            moreEl = allLinks.find(el => {{
                const txt = (el.innerText || '').trim();
                const role = el.getAttribute('role') || '';
                const area = (el.getAttribute('data-nlog-area') || '').toLowerCase();
                const href = (el.href || el.getAttribute('href') || '').toLowerCase();
                if (role.includes('tab') || area.includes('more2') || area.includes('law') || area.includes('pw') || area.includes('ad')) return false;
                if (isAiLink(el)) return false;
                const isShopRelated = href.includes('shopping.naver.com') || area.includes('shp') || txt.includes('상품 더보기') || txt.includes('쇼핑 더보기') || txt.includes('상품더보기');
                if (!isShopRelated) return false;
                if (!txt.includes('더보기')) return false;
                const r = el.getBoundingClientRect();
                return r.width >= 50 && r.height >= 18 && r.height <= 95;
            }});
        }}
        if (!moreEl) {{
            const moreLinks = Array.from(document.querySelectorAll('a, button')).filter(el => (el.innerText || '').includes('더보기')).map(el => ({{
                text: (el.innerText || '').trim(),
                href: (el.href || el.getAttribute('href') || '').slice(0, 80),
                area: el.getAttribute('data-nlog-area'),
                role: el.getAttribute('role'),
                rect: {{ w: el.getBoundingClientRect().width, h: el.getBoundingClientRect().height }}
            }}));
            return {{
                found: false,
                error: "MORE_BTN_NOT_FOUND",
                debug: {{
                    shpSecName: shpSecName,
                    shpContainerFound: !!shpContainer,
                    allLinks: document.querySelectorAll('a, button').length,
                    moreLinks: moreLinks
                }}
            }};
        }}

        let clickTarget = moreEl;
        if (clickTarget.tagName !== 'A' && clickTarget.tagName !== 'BUTTON') {{
            const childBtn = clickTarget.querySelector('a, button');
            if (childBtn && !isAiLink(childBtn)) clickTarget = childBtn;
        }}

        if (isAiLink(clickTarget)) {{
            return {{ found: false, error: "TARGET_IS_AI_BANNER" }};
        }}

        // 📌 [고유 마킹] 재측정 시 동일 요소를 100% 오차 없이 재추적하기 위해 고유 마커 속성 부여
        clickTarget.setAttribute('data-macro-target', 'shop_more_btn');

        // 뷰포트 중앙으로 스크롤 정렬
        clickTarget.scrollIntoView({{ block: 'center', inline: 'center', behavior: 'instant' }});
        const r = clickTarget.getBoundingClientRect();

        return {{
            found: true,
            text: (clickTarget.innerText || '').trim().substring(0, 40),
            area: clickTarget.getAttribute('data-nlog-area') || '',
            href: clickTarget.href || '',
            x: r.x + r.width / 2,
            y: r.y + r.height / 2,
            width: r.width,
            height: r.height,
            section: shpSecName || 'shp'
        }};
    }})()
    """

    more_info = None
    more_wait_steps = max(1, int(TIMINGS.SHOP_NAV_MORE_MAX_WAIT / TIMINGS.SHOP_NAV_MORE_POLL_INTERVAL))
    for wait_more in range(more_wait_steps):  # QoS 대역폭 저하 로딩 적응형 완충
        more_info = await cdp.evaluate(find_more_js)
        if isinstance(more_info, dict) and more_info.get("found"):
            break
        if wait_more >= 1:
            # 하단에 위치한 오가닉 쇼핑 섹션 노출을 위해 적극적인 스크롤 하강 탐색
            try:
                await cdp.evaluate("window.scrollBy(0, 800);")
            except Exception:
                pass
        await asyncio.sleep(TIMINGS.SHOP_NAV_MORE_POLL_INTERVAL)

    if not isinstance(more_info, dict) or not more_info.get("found"):
        logger.error(f"❌ [쇼핑 더보기 버튼 미발견] 쇼핑 섹션({sec_name}) 내 .more 요소를 찾을 수 없습니다: {more_info}")
        return {
            "success": False,
            "status": "SHOPPING_MORE_NOT_FOUND",
            "error_message": "쇼핑 섹션 내 .more 더보기 버튼 미발견"
        }

    btn_x = more_info.get("x", 0)
    btn_y = more_info.get("y", 0)
    btn_text = more_info.get("text", "")
    btn_area = more_info.get("area", "")
    btn_href = more_info.get("href", "")
    logger.info(f"🎯 [쇼핑섹션 .more 버튼 포착] 섹션='{sec_name}' | nlog-area='{btn_area}' | 텍스트='{btn_text}' | 1차좌표=({btn_x:.1f}, {btn_y:.1f})")

    # 1. 뷰포트 스크롤 후 레이아웃 시프트 완결 및 DOM 정착 대기
    await asyncio.sleep(0.35)

    # 2. [Zero-Stale Coordinate & AI Eradication & elementFromPoint Interlock Gate]
    # 터치 직전 실시간 정밀 좌표 재측정 + AI 배너 완전 박멸 + 좌표 직하 실물 요소 100% 검증
    recalc_js = f"""
    (() => {{
        // [AI 배너/AI탭 영구 무력화 CSS 쉴드 주입 및 DOM 즉시 파기]
        try {{
            if (!document.getElementById('__nshop_ai_shield')) {{
                const style = document.createElement('style');
                style.id = '__nshop_ai_shield';
                style.innerHTML = `
                    .eA6w58S8, .cGTdiNgw, .hbhTlgi0,
                    [data-nlog-area*="aitab"],
                    [data-nlog-area*="ait"],
                    [data-nlog-area*="cue"],
                    [href*="aitabshop"],
                    [href*="m_ait"],
                    [href*="shopping_banner"],
                    [class*="ai_tab_banner"],
                    [class*="ait_agent"],
                    [role="tab"][href*="m_ait"],
                    [role="tab"][href*="tab.m_ait"] {{
                        display: none !important;
                        height: 0 !important;
                        max-height: 0 !important;
                        overflow: hidden !important;
                        pointer-events: none !important;
                        visibility: hidden !important;
                        position: absolute !important;
                        top: -9999px !important;
                    }}

                    /* [절대 원칙] 네이버 클립 및 동영상 섹션 상호작용 완전 무력화 (오클릭/재생 원천 차단) */
                    [data-nlog-area^="clp_"],
                    [data-nlog-area*="clip"],
                    [data-nlog-area*="video"],
                    [class*="clip_wrap"],
                    [class*="clip_card"],
                    [class*="clip_area"],
                    [class*="video_wrap"],
                    a[href*="clip.naver.com"],
                    a[href*="m.clip.naver.com"],
                    a[href*="naversearchapp://clip"],
                    div#_clip_root,
                    section[id*="clip"] {{
                        pointer-events: none !important;
                    }}
                `;
                (document.head || document.documentElement).appendChild(style);
            }}
            document.querySelectorAll('.eA6w58S8, .cGTdiNgw, .hbhTlgi0, [data-nlog-area*="aitab"], a[href*="aitabshop"], a[href*="m_ait"], a[href*="shopping_banner"], [class*="ai_tab_banner"], [class*="ait_agent"], [role="tab"][href*="m_ait"]').forEach(el => el.remove());
            document.querySelectorAll('div[class*="tooltip"], div[class*="coach"], div[class*="guide"], div[class*="balloon"]').forEach(el => el.remove());
        }} catch(e) {{}}

        const isAiLink = (el) => {{
            if (!el) return false;
            const aTag = el.closest('a') || el;
            const h = (aTag.href || aTag.getAttribute('href') || el.href || el.getAttribute('href') || '').toLowerCase();
            const a = (el.getAttribute('data-nlog-area') || aTag.getAttribute('data-nlog-area') || '').toLowerCase();
            const c = ((el.className || '') + ' ' + (aTag.className || '')).toLowerCase();
            const t = ((el.innerText || '') + ' ' + (aTag.innerText || '')).toLowerCase();
            return h.includes('ait') || h.includes('shopping_banner') || h.includes('banner') || h.includes('cue') ||
                   a.includes('ait') || a.includes('banner') || a.includes('cue') ||
                   c.includes('ait') || c.includes('cgtdingw') || c.includes('hbhtlgi0') || c.includes('ea6w58s8') || c.includes('cue') ||
                   t.includes('ai로') || t.includes('ai탭') || t.includes('ai 검색') || t.includes('ai 브리핑');
        }};

        const isClipElement = (el) => {{
            if (!el) return false;
            const aTag = el.closest('a') || el;
            const h = (aTag.href || aTag.getAttribute('href') || el.href || el.getAttribute('href') || '').toLowerCase();
            const a = (el.getAttribute('data-nlog-area') || aTag.getAttribute('data-nlog-area') || '').toLowerCase();
            const c = ((el.className || '') + ' ' + (aTag.className || '')).toLowerCase();
            return h.includes('clip.naver.com') || h.includes('naversearchapp://clip') ||
                   a.startsWith('clp_') || a.includes('clip') ||
                   c.includes('clip_') || c.includes('_clip');
        }};

        const isNotMoreBtn = (el) => {{
            if (!el) return true;
            const a = (el.getAttribute('data-nlog-area') || '').toLowerCase();
            const t = ((el.innerText || '') + ' ' + (el.getAttribute('title') || '')).toLowerCase();
            const h = (el.href || el.getAttribute('href') || '').toLowerCase();
            if (a.includes('.mtc') || a.includes('.filter') || a.includes('.sort') || a.includes('law') || a.includes('pw') || a.includes('ad')) return true;
            if (a.startsWith('clp') || a.includes('clip') || a.includes('video')) return true;
            if (h.includes('clip.naver.com') || h.includes('naversearchapp://clip')) return true;
            if (t.includes('로만 검색') || t.includes('원문보기') || t.includes('이전 페이지') || t.includes('다음 페이지') || t.includes('현재') || t.includes('전체')) return true;
            return false;
        }};

        // 1차에서 마킹한 정확한 버튼 요소 추적
        let btn = document.querySelector('[data-macro-target="shop_more_btn"]');
        if (btn && (isAiLink(btn) || isClipElement(btn) || isNotMoreBtn(btn))) btn = null;

        if (!btn) {{
            const list = Array.from(document.querySelectorAll('a[data-nlog-area^="shp_"][data-nlog-area*="more"]:not([data-nlog-area*="more2"]):not([role="tab"])'));
            btn = list.find(el => !isAiLink(el) && !isClipElement(el) && !isNotMoreBtn(el));
        }}
        if (!btn) {{
            const allLinks = Array.from(document.querySelectorAll('a, button'));
            btn = allLinks.find(el => {{
                const txt = (el.innerText || '').trim();
                const role = el.getAttribute('role') || '';
                const area = (el.getAttribute('data-nlog-area') || '').toLowerCase();
                const h = (el.href || el.getAttribute('href') || '').toLowerCase();
                const isShop = area.startsWith('shp_') || h.includes('shopping.naver.com') || h.includes('msearch.shopping');
                return !role.includes('tab') && !area.includes('more2') && !area.includes('law') && isShop && !isAiLink(el) && !isClipElement(el) && !isNotMoreBtn(el) && txt.includes('더보기');
            }});
        }}
        if (!btn) return {{ valid: false, error: 'BTN_LOST_OR_AI_FILTERED' }};

        const winH = window.innerHeight || 800;
        const winW = window.innerWidth || 360;
        const SAFE_TOP = 130;  // 상단 fixed 헤더 회피
        const SAFE_BOTTOM = winH - 90; // 하단 탭바 회피

        // 1. 항상 버튼을 뷰포트 정중앙으로 스크롤하여 플로팅/헤더/푸터 간섭 원천 배제
        btn.scrollIntoView({{ block: 'center', inline: 'center', behavior: 'instant' }});
        let r = btn.getBoundingClientRect();

        if (r.width < 80 || r.height < 20 || r.height > 95) {{
            return {{ valid: false, error: 'INVALID_RECT_SIZE', width: r.width, height: r.height }};
        }}

        const cx = Math.max(30.0, Math.min(r.left + r.width / 2, winW - 30.0));
        const cy = Math.max(SAFE_TOP + 10.0, Math.min(r.top + r.height / 2, SAFE_BOTTOM - 10.0));

        // [프리터치 elementFromPoint 100% 실측 인터락]
        const elAtPoint = document.elementFromPoint(cx, cy);
        if (!elAtPoint) return {{ valid: false, error: 'NO_ELEMENT_AT_POINT' }};

        // 좌표 상에 AI 관련 요소가 있으면 즉시 제거 후 에러 리턴
        const aiHit = elAtPoint.closest('[href*="ait"], [class*="ai_tab"], [class*="ait_agent"], [data-nlog*="ait"], .cGTdiNgw, .hbhTlgi0, .eA6w58S8');
        if (aiHit || isAiLink(elAtPoint)) {{
            try {{ (aiHit || elAtPoint).remove(); }} catch(ign) {{}}
            return {{ valid: false, error: 'AI_ELEMENT_INTERCEPTED_AND_REMOVED' }};
        }}

        // 좌표 상에 클립/동영상 요소가 감지되면 즉시 에러 리턴 (오클릭 방지)
        if (isClipElement(elAtPoint)) {{
            return {{ valid: false, error: 'CLIP_ELEMENT_INTERCEPTED' }};
        }}

        // 좌표 상 요소가 진짜 더보기 버튼이거나 그 내부 텍스트인지 검증
        const isTargetMatch = elAtPoint === btn || btn.contains(elAtPoint) || elAtPoint.contains(btn) || elAtPoint.closest('[data-macro-target="shop_more_btn"]') || (elAtPoint.innerText || '').includes('더보기');
        if (!isTargetMatch) {{
            const elAtPointAdjusted = document.elementFromPoint(cx, cy + 8);
            if (elAtPointAdjusted && (elAtPointAdjusted === btn || btn.contains(elAtPointAdjusted) || elAtPointAdjusted.contains(btn) || (elAtPointAdjusted.innerText || '').includes('더보기'))) {{
                return {{
                    valid: true,
                    x: Math.round(cx * 10) / 10,
                    y: Math.round((cy + 8) * 10) / 10,
                    rect: {{ top: r.top, bottom: r.bottom, height: r.height, width: r.width }},
                    text: (btn.innerText || '').trim(),
                    href: btn.href || btn.getAttribute('href') || ''
                }};
            }}
            return {{
                valid: false,
                error: 'ELEMENT_MISMATCH_AT_POINT',
                hitTag: elAtPoint.tagName,
                hitClass: elAtPoint.className,
                hitText: (elAtPoint.innerText || '').slice(0, 30)
            }};
        }}

        return {{
            valid: true,
            x: Math.round(cx * 10) / 10,
            y: Math.round(cy * 10) / 10,
            rect: {{ top: r.top, bottom: r.bottom, height: r.height, width: r.width }},
            text: (btn.innerText || '').trim(),
            href: btn.href || btn.getAttribute('href') || ''
        }};
    }})()
    """

    recalc_info = await cdp.evaluate(recalc_js)
    if isinstance(recalc_info, dict) and recalc_info.get("valid"):
        orig_y = btn_y
        btn_x = recalc_info.get("x", btn_x)
        btn_y = recalc_info.get("y", btn_y)
        btn_h = recalc_info.get("rect", {}).get("height", 0)
        logger.info(f"✨ [터치 직전 실시간 좌표 확정] 1차({orig_y:.1f}) -> 2차 실측({btn_y:.1f}) | 변위: {btn_y - orig_y:+.1f}px | 버튼높이: {btn_h:.1f}px")
    else:
        logger.warning(f"⚠️ [1차 재측정 실패] {recalc_info} -> 0.3초 대기 후 2차 재측정 시도...")
        await asyncio.sleep(0.3)
        recalc_info = await cdp.evaluate(recalc_js)
        if isinstance(recalc_info, dict) and recalc_info.get("valid"):
            btn_x = recalc_info.get("x", btn_x)
            btn_y = recalc_info.get("y", btn_y)
            logger.info(f"✨ [2차 재측정 성공] 좌표 확정: ({btn_x:.1f}, {btn_y:.1f})")
        else:
            logger.error(f"❌ [쇼핑 더보기 버튼 정밀 조준 최종 실패] 좌표 무결성 검증 탈락: {recalc_info}")
            return {
                "success": False,
                "status": "SHOPPING_MORE_ALIGN_FAILED",
                "error_message": f"더보기 버튼 조준 실패 ({recalc_info.get('error') if isinstance(recalc_info, dict) else 'UNKNOWN'})"
            }

    # 📌 [절대 철칙 4/AI 배너 영구 배제] 터치 대상 URL이 AI 검색/배너로 연결되는지 최종 검증
    target_href = str((recalc_info.get("href") if isinstance(recalc_info, dict) else "") or more_info.get("href", "")).lower()
    if any(k in target_href for k in ("aitabshop", "m_ait", "shopping_banner", "ait_agent_type", "tab.m_ait")):
        logger.error(f"❌ [AI 검색 배너 클릭 시도 원천 차단] 버튼 URL이 AI 탭을 향하고 있습니다: {target_href}")
        return {
            "success": False,
            "status": "NOT_SHOPPING_KEYWORD",
            "error_message": f"쇼핑 더보기 버튼이 AI 배너로 연결됨 ({target_href})"
        }

    # 3. 실물 터치 (CDP Real Touch) 타격
    # 📌 [절대 철칙 9] el.click() 절대 금지! 100% 순수 물리 터치(CDP Real Touch: Input.dispatchTouchEvent) 단독 발송
    touch_res = await cdp_real_touch(
        cdp=cdp,
        device_id=device_id,
        task_id=task.task_id,
        action_name="SHOPPING_MORE_TOUCH",
        click_x=btn_x,
        click_y=btn_y,
        output_dir=output_dir,
        capture_screenshot=True,
        use_jitter=False
    )
    result.action_history.append({
        "time": time.time(),
        "action": "SHOPPING_MORE_TOUCH",
        "coord": {"x": btn_x, "y": btn_y},
        "section": sec_name,
        "details": touch_res
    })
    result.jitter_history.append({
        "time": time.time(),
        "action": "SHOPPING_MORE_TOUCH",
        "use_jitter": touch_res.get("use_jitter", False),
        "hold_ms": touch_res.get("hold_ms"),
        "pre_touch_delay": touch_res.get("pre_touch_delay")
    })

    if traffic_logger:
        traffic_logger.record_event("SHOP_NAV", f"Click .more in section {sec_name}", {
            "keyword": task.keyword,
            "section": sec_name,
            "btn_text": btn_text,
            "coord": {"x": btn_x, "y": btn_y}
        })

    # 4. [Playwright 스타일 범용 패킷/네비게이션 전환 대기 + 신규 InAppBrowserActivity 실시간 감시]
    trans_res = await wait_for_transition(
        cdp=cdp,
        transition_type=TransitionType.PAGE_NAV,
        expected_pattern="shopping.naver.com",
        timeout=TIMINGS.SHOP_NAV_TRANSITION_TIMEOUT,
        device_id=device_id,
        cdp_port=cdp_port,
        abort_predicate=lambda: getattr(result, "login_detected", False)
    )

    # [핵심 보강] 1차 터치 후 통검에 머무르는 경우(CLICK_MISSED/TIMEOUT) 2차 정밀 재터치 (단, 로그인 챌린지 감지 시 제외)
    if not trans_res.success and trans_res.status in ("CLICK_MISSED", "TIMEOUT") and not getattr(result, "login_detected", False):
        logger.warning(f"⚠️ [쇼핑 더보기 전환 미반응 감지 ({trans_res.status})] 통검 화면 잔류 확인 -> 2차 정밀 재터치 발송...")
        retry_touch_js = f"""
        (() => {{
            // [AI 배너/AI탭 영구 무력화 CSS 쉴드 주입 및 DOM 즉시 파기]
            try {{
                if (!document.getElementById('__nshop_ai_shield')) {{
                    const style = document.createElement('style');
                    style.id = '__nshop_ai_shield';
                    style.innerHTML = `
                        .eA6w58S8, .cGTdiNgw, .hbhTlgi0,
                        [data-nlog-area*="aitab"],
                        [data-nlog-area*="ait"],
                        [data-nlog-area*="cue"],
                        [href*="aitabshop"],
                        [href*="m_ait"],
                        [href*="shopping_banner"],
                        [class*="ai_tab_banner"],
                        [class*="ait_agent"],
                        [role="tab"][href*="m_ait"],
                        [role="tab"][href*="tab.m_ait"] {{
                            display: none !important;
                            height: 0 !important;
                            max-height: 0 !important;
                            overflow: hidden !important;
                            pointer-events: none !important;
                            visibility: hidden !important;
                            position: absolute !important;
                            top: -9999px !important;
                        }}

                        /* [절대 원칙] 네이버 클립 및 동영상 섹션 상호작용 완전 무력화 (오클릭/재생 원천 차단) */
                        [data-nlog-area^="clp_"],
                        [data-nlog-area*="clip"],
                        [data-nlog-area*="video"],
                        [class*="clip_wrap"],
                        [class*="clip_card"],
                        [class*="clip_area"],
                        [class*="video_wrap"],
                        a[href*="clip.naver.com"],
                        a[href*="m.clip.naver.com"],
                        a[href*="naversearchapp://clip"],
                        div#_clip_root,
                        section[id*="clip"] {{
                            pointer-events: none !important;
                        }}
                    `;
                    (document.head || document.documentElement).appendChild(style);
                }}
                document.querySelectorAll('.eA6w58S8, .cGTdiNgw, .hbhTlgi0, [data-nlog-area*="aitab"], a[href*="aitabshop"], a[href*="m_ait"], a[href*="shopping_banner"], [class*="ai_tab_banner"], [class*="ait_agent"], [role="tab"][href*="m_ait"]').forEach(el => el.remove());
                document.querySelectorAll('div[class*="tooltip"], div[class*="coach"], div[class*="guide"], div[class*="balloon"]').forEach(el => el.remove());
            }} catch(e) {{}}

            const isAiLink = (el) => {{
                if (!el) return false;
                const aTag = el.closest('a') || el;
                const h = (aTag.href || aTag.getAttribute('href') || el.href || el.getAttribute('href') || '').toLowerCase();
                const a = (el.getAttribute('data-nlog-area') || aTag.getAttribute('data-nlog-area') || '').toLowerCase();
                const c = ((el.className || '') + ' ' + (aTag.className || '')).toLowerCase();
                const t = ((el.innerText || '') + ' ' + (aTag.innerText || '')).toLowerCase();
                return h.includes('ait') || h.includes('shopping_banner') || h.includes('banner') || h.includes('cue') ||
                       a.includes('ait') || a.includes('banner') || a.includes('cue') ||
                       c.includes('ait') || c.includes('cgtdingw') || c.includes('hbhtlgi0') || c.includes('ea6w58s8') || c.includes('cue') ||
                       t.includes('ai로') || t.includes('ai탭') || t.includes('ai 검색') || t.includes('ai 브리핑');
            }};

            const isClipElement = (el) => {{
                if (!el) return false;
                const aTag = el.closest('a') || el;
                const h = (aTag.href || aTag.getAttribute('href') || el.href || el.getAttribute('href') || '').toLowerCase();
                const a = (el.getAttribute('data-nlog-area') || aTag.getAttribute('data-nlog-area') || '').toLowerCase();
                const c = ((el.className || '') + ' ' + (aTag.className || '')).toLowerCase();
                return h.includes('clip.naver.com') || h.includes('naversearchapp://clip') ||
                       a.startsWith('clp_') || a.includes('clip') ||
                       c.includes('clip_') || c.includes('_clip');
            }};

            const isNotMoreBtn = (el) => {{
                if (!el) return true;
                const a = (el.getAttribute('data-nlog-area') || '').toLowerCase();
                const t = ((el.innerText || '') + ' ' + (el.getAttribute('title') || '')).toLowerCase();
                const h = (el.href || el.getAttribute('href') || '').toLowerCase();
                if (a.includes('.mtc') || a.includes('.filter') || a.includes('.sort') || a.includes('law') || a.includes('pw') || a.includes('ad')) return true;
                if (a.startsWith('clp') || a.includes('clip') || a.includes('video')) return true;
                if (h.includes('clip.naver.com') || h.includes('naversearchapp://clip')) return true;
                if (t.includes('로만 검색') || t.includes('원문보기') || t.includes('이전 페이지') || t.includes('다음 페이지') || t.includes('현재') || t.includes('전체')) return true;
                return false;
            }};

            let el = document.querySelector('[data-macro-target="shop_more_btn"]');
            if (el && (isAiLink(el) || isClipElement(el) || isNotMoreBtn(el))) el = null;
            if (!el) {{
                const list = Array.from(document.querySelectorAll('a[data-nlog-area$=".none.more"]:not([data-nlog-area*="more2"]):not([role="tab"])'));
                el = list.find(e => !isAiLink(e) && !isClipElement(e) && !isNotMoreBtn(e));
            }}
            if (!el) {{
                const allLinks = Array.from(document.querySelectorAll('a, button'));
                el = allLinks.find(e => {{
                    const txt = (e.innerText || '').trim();
                    const role = e.getAttribute('role') || '';
                    const area = (e.getAttribute('data-nlog-area') || '').toLowerCase();
                    const h = (e.href || e.getAttribute('href') || '').toLowerCase();
                    const isShop = area.startsWith('shp_') || h.includes('shopping.naver.com') || h.includes('msearch.shopping');
                    return !role.includes('tab') && !area.includes('more2') && !area.includes('law') && isShop && !isAiLink(e) && !isClipElement(e) && !isNotMoreBtn(e) && txt.includes('더보기');
                }});
            }}
            if (!el || isAiLink(el) || isClipElement(el) || isNotMoreBtn(el)) return {{ found: false }};

            el.scrollIntoView({{ block: 'center', inline: 'center', behavior: 'instant' }});
            const r = el.getBoundingClientRect();
            const cx = r.left + r.width / 2;
            const cy = r.top + r.height / 2;

            const elAtPoint = document.elementFromPoint(cx, cy);
            if (elAtPoint && (isAiLink(elAtPoint) || isClipElement(elAtPoint) || elAtPoint.closest('[href*="ait"], [class*="ai_tab"], [class*="ait_agent"], [data-nlog*="ait"], .cGTdiNgw, .hbhTlgi0, .eA6w58S8'))) {{
                return {{ found: false, error: 'AI_OR_CLIP_BLOCKED' }};
            }}

            return {{ found: true, x: cx, y: cy, href: el.href || '' }};
        }})()
        """
        try:
            retry_info = await cdp.evaluate(retry_touch_js)
            if retry_info and retry_info.get("found"):
                rx = retry_info.get("x", btn_x)
                ry = retry_info.get("y", btn_y)
                retry_touch_res = await cdp_real_touch(
                    cdp=cdp,
                    device_id=device_id,
                    task_id=task.task_id,
                    action_name="SHOPPING_MORE_RETRY",
                    click_x=rx,
                    click_y=ry,
                    output_dir=output_dir,
                    capture_screenshot=False,
                    use_jitter=False
                )
                result.action_history.append({
                    "time": time.time(),
                    "action": "SHOPPING_MORE_RETRY",
                    "coord": {"x": rx, "y": ry},
                    "details": retry_touch_res
                })
                result.jitter_history.append({
                    "time": time.time(),
                    "action": "SHOPPING_MORE_RETRY",
                    "use_jitter": retry_touch_res.get("use_jitter", False),
                    "hold_ms": retry_touch_res.get("hold_ms"),
                    "pre_touch_delay": retry_touch_res.get("pre_touch_delay")
                })
                trans_res = await wait_for_transition(
                    cdp=cdp,
                    transition_type=TransitionType.PAGE_NAV,
                    expected_pattern="shopping.naver.com",
                    timeout=TIMINGS.SHOP_NAV_RETRY_TIMEOUT,
                    device_id=device_id,
                    cdp_port=cdp_port,
                    abort_predicate=lambda: getattr(result, "login_detected", False)
                )
        except Exception as e:
            logger.warning(f"2차 더보기 재터치 시도 예외: {type(e).__name__} ({e})")

    if not trans_res.success:
        logger.error(f"❌ [쇼핑탭 진입 실패] 상태: {trans_res.status} | 사유: {trans_res.error_message}")
        if trans_res.status in ("CAPTCHA_BLOCKED", "LOGIN_REQUIRED", "LOGIN_CHALLENGE_DETECTED", "AI_SEARCH_REDIRECT"):
            save_stage_screenshot(device_id, trans_res.status.lower(), task.task_id, output_dir)
            if traffic_logger:
                traffic_logger.record_event(trans_res.status, trans_res.error_message or trans_res.status, {
                    "url": trans_res.final_url,
                    "error": trans_res.error_message
                })
        return {
            "success": False,
            "status": trans_res.status,
            "error_message": trans_res.error_message
        }

    logger.info(f"⚡ [쇼핑탭 진입 성공] {trans_res.duration_sec:.2f}초 만에 쇼핑 검색결과 안착 확인 완료")

    # 5. 분리된 신규 웹뷰 탭(InAppBrowserActivity 등) 존재 여부 검사 및 연결 동기화
    shop_cdp = trans_res.cdp or cdp
    if cdp_port and not trans_res.cdp:
        try:
            import urllib.request
            import json
            import websockets
            deadline = time.time() + TIMINGS.SHOP_NAV_TAB_SCAN_TIMEOUT
            while time.time() < deadline:
                data = urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=1.0).read().decode()
                targets = json.loads(data)
                shop_target = next((t for t in targets if t.get("type") == "page" and any(k in t.get("url", "") for k in ["shopping.naver.com", "msearch.shopping", "where=m_shop", "/search/all", "/ns/search"])), None)
                if shop_target and shop_target.get("webSocketDebuggerUrl"):
                    new_ws_url = shop_target["webSocketDebuggerUrl"]
                    cur_ws = getattr(cdp, "ws_url", "")
                    if not cur_ws or new_ws_url != cur_ws:
                        logger.info(f"🔗 [신규 쇼핑 탭 분리 감지] 새 WebSocket 대상 연결: {new_ws_url}")
                        new_ws = await websockets.connect(new_ws_url, ping_interval=None, open_timeout=5.0)
                        shop_cdp = AsyncCDPClient(new_ws)
                        shop_cdp.ws_url = new_ws_url
                        try:
                            await shop_cdp.call("Network.enable")
                        except Exception:
                            pass
                        break
                await asyncio.sleep(0.15)
        except Exception as e:
            logger.debug(f"쇼핑 탭 URL 스캔 예외: {e}")

    # [최종 무결성 검증] 쇼핑탭 URL 안착 대기 (최대 3초 완충)
    cur_u_verify = ""
    for _ in range(10):
        try:
            cur_u_verify = await shop_cdp.evaluate("window.location.href", timeout=1.0) or ""
            if any(k in cur_u_verify for k in ("shopping.naver.com", "where=m_shop", "/search/all")):
                break
        except Exception:
            pass
        await asyncio.sleep(0.3)

    if cur_u_verify and "m.search.naver.com" in cur_u_verify and "where=m_shop" not in cur_u_verify and "shopping.naver.com" not in cur_u_verify:
        fail_status = "LOGIN_CHALLENGE_DETECTED" if result.login_detected else "SHOPPING_MORE_MISSED"
        fail_msg = "쇼핑 더보기 클릭 후 FDS 로그인 챌린지 감지" if result.login_detected else f"쇼핑 더보기 클릭 후 쇼핑탭 미진입 (통검 잔류: {cur_u_verify})"
        logger.error(f"❌ [쇼핑탭 진입 실패 확정] {fail_msg}")
        return {
            "success": False,
            "status": fail_status,
            "error_message": fail_msg
        }

    return {
        "success": True,
        "status": "SUCCESS",
        "cdp": shop_cdp,
        "error_message": None
    }


# 하위 호환 별칭
execute_shop_more_click = execute_shop_navigation
