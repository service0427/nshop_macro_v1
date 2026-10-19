#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/pipeline/utils/serp_parser.py

Parses Naver Mobile SERP global objects:
1. naver.search.ext.newshopping.shopping._INITIAL_STATE.initProps.pagedSlot
   - Fast-fail validation: returns False if no shopping presence
   - Slot scanning: identifies target slot, enforcing the FIRST-occurrence rule
2. naver.search.section.main
   - Extracts active shopping collection section names (e.g. shp_tli, shp_fnd, shp_epl)
   - Resolves root DOM container selector to isolate search scope
"""

from typing import Dict, Any, Optional, List
from src.browser.cdp_client import AsyncCDPClient


async def check_serp_paged_slot(cdp: AsyncCDPClient, target_mid: str = "", target_rank: Optional[int] = None, compare_id: str = "") -> Dict[str, Any]:
    """
    Evaluates SERP pagedSlot and section metadata:
    - has_shopping: True if pagedSlot exists and has slots
    - target: first matching slot (first-occurrence rule)
    - section_selector: DOM selector for the shopping container
    """
    target_rank_str = str(target_rank) if target_rank is not None else "null"
    eval_js = f"""
    (() => {{
        try {{
            const targetMid = "{target_mid or ''}";
            const compareMid = "{compare_id or ''}";
            const targetRank = {target_rank_str};

            // 0. Check for network error page (Chromium net::ERR_* DOM element or error text)
            const bodyTxt = document.body ? (document.body.innerText || '') : '';
            const isNetErr = document.getElementById('main-frame-error') || 
                             document.querySelector('.error-code') ||
                             document.querySelector('#main-message') ||
                             bodyTxt.includes('ERR_NAME_NOT_RESOLVED') ||
                             bodyTxt.includes('ERR_INTERNET_DISCONNECTED') ||
                             bodyTxt.includes('ERR_CONNECTION_REFUSED') ||
                             bodyTxt.includes('ERR_TIMED_OUT') ||
                             bodyTxt.includes('net::ERR_') ||
                             bodyTxt.includes('사이트에 연결할 수 없습니다');
            if (isNetErr) {{
                return {{
                    has_shp_section: false,
                    has_paged_slot: false,
                    has_shopping: false,
                    is_network_error: true,
                    reason: "NETWORK_ERROR_PAGE",
                    error_message: "네트워크 단절 또는 DNS 해석 실패 (ERR_* / 사이트에 연결할 수 없습니다)",
                    found: false,
                    target: null,
                    section_name: null
                }};
            }}

            // 0-1. Check for access restriction (FDS rate-limiting / IP block)
            const isBlocked = bodyTxt.includes('접속이 일시적으로 제한되었습니다') ||
                              bodyTxt.includes('쇼핑 서비스 접속이 일시적으로 제한') ||
                              bodyTxt.includes('서비스 접속이 제한되었습니다') ||
                              bodyTxt.includes('비정상적인 접근이 감지되었습니다') ||
                              bodyTxt.includes('비정상적인 트래픽으로 인해') ||
                              bodyTxt.includes('쇼핑 서비스 이용이 일시적으로 제한');
            if (isBlocked) {{
                return {{
                    has_shp_section: false,
                    has_paged_slot: false,
                    has_shopping: false,
                    is_access_blocked: true,
                    reason: "ACCESS_BLOCKED_PAGE",
                    error_message: "통합검색/쇼핑 접속 제한 (접속이 일시적으로 제한되었습니다)",
                    found: false,
                    target: null,
                    section_name: null
                }};
            }}

            // 1. Extract organic shp_ section name from naver.search.section.main FIRST
            const isAdSectionStr = (s) => {{
                const lower = (s || '').toLowerCase();
                return lower.includes('_ad') || lower.includes('ad_') || lower.includes('pwl') || lower.includes('power');
            }};

            const secMain = window.naver?.search?.section?.main;
            let shpSectionName = null;
            if (Array.isArray(secMain)) {{
                for (let s of secMain) {{
                    let str = '';
                    if (typeof s === 'string') {{
                        str = s;
                    }} else if (s && typeof s === 'object') {{
                        str = s.area || s.id || s.name || s.section || '';
                    }}
                    if ((str.includes('shp_') || str.startsWith('shp')) && !isAdSectionStr(str)) {{
                        shpSectionName = str.split('*')[0];
                        break;
                    }}
                }}
            }} else if (secMain && typeof secMain === 'object') {{
                const keys = Object.keys(secMain);
                const foundKey = keys.find(k => (k.includes('shp_') || k.startsWith('shp')) && !isAdSectionStr(k));
                if (foundKey) {{
                    shpSectionName = foundKey.split('*')[0];
                }}
            }}

            // Fallback: Check DOM sections or newshopping state if secMain is still hydrating
            if (!shpSectionName) {{
                const shpEl = document.querySelector('[data-nlog-area*="shp_"]:not([data-nlog-area*="pwl"]):not([data-nlog-area*="ad"]), [data-slog-id*="shp_"]:not([data-slog-id*="ad"]), section[class*="_root_shp_"]:not([class*="ad"]), section[data-slog-container*="shp"]:not([data-slog-container*="ad"]), div[class*="api_subject_bx"][data-slog-container*="shp"], div._new_shopping_sticky_area, section[id*="shp_"]:not([id*="ad"]), a[href*="msearch.shopping.naver.com"]:not([role="tab"])');
                if (shpEl) {{
                    const rawVal = (shpEl.getAttribute('data-nlog-area') || shpEl.getAttribute('data-slog-id') || shpEl.id || shpEl.getAttribute('data-block') || 'shp_tli').split('.')[0];
                    shpSectionName = rawVal.split('*')[0] || 'shp_tli';
                    if (isAdSectionStr(shpSectionName)) {{
                        shpSectionName = 'shp_tli';
                    }}
                }} else if (window.naver?.search?.ext?.newshopping?.shopping?._INITIAL_STATE?.initProps?.pagedSlot) {{
                    shpSectionName = 'shp_tli';
                }} else {{
                    const hasShopLink = document.querySelector('a[href*="msearch.shopping.naver.com"]:not([role="tab"]), a[data-nlog-area*="shp_"], [data-nlog-area*="shp_tli"]') ||
                                        (document.body && (document.body.innerText.includes('상품 더보기') || document.body.innerText.includes('쇼핑 더보기')));
                    if (hasShopLink) {{
                        shpSectionName = 'shp_tli';
                    }}
                }}
            }}

            const secMainLoaded = (Array.isArray(secMain) && secMain.length > 0) || (secMain && typeof secMain === 'object' && Object.keys(secMain).length > 0);
            const domReady = (document.readyState === 'complete' || document.readyState === 'interactive') && !!document.body && document.body.children.length > 3;

            // [사용자 지침 1] section에서 shp_가 아예 없다면 쇼핑 무관 키워드 -> 즉시 종료
            if (!shpSectionName) {{
                return {{
                    has_shp_section: false,
                    has_paged_slot: false,
                    has_shopping: false,
                    is_definitive_no_shp: secMainLoaded && domReady,
                    reason: "NO_SHP_SECTION",
                    found: false,
                    target: null,
                    section_name: null
                }};
            }}

            // [사용자 지침 2] shp_ 섹션이 있는데 pagedSlot이 아니라면 -> 쇼핑탭(쇼핑 더보기)으로 즉시 이동
            const ps = window.naver?.search?.ext?.newshopping?.shopping?._INITIAL_STATE?.initProps?.pagedSlot;
            const hasPagedSlot = !!(ps && Array.isArray(ps) && ps.length > 0);

            if (!hasPagedSlot) {{
                return {{
                    has_shp_section: true,
                    has_paged_slot: false,
                    has_shopping: true,
                    route_to_shop_tab: true,
                    reason: "NO_PAGED_SLOT_NON_STANDARD_CATEGORY",
                    found: false,
                    target: null,
                    section_name: shpSectionName,
                    total_pages: 0
                }};
            }}

            // [사용자 지침 3] newshopping.shopping.pagedSlot이 있다면 -> 타겟 상품 탐색
            let foundTarget = null;
            let organicRankCounter = 0;

            for (let pIdx = 0; pIdx < ps.length; pIdx++) {{
                const pageObj = ps[pIdx];
                const slots = pageObj.slots || [];

                for (let sIdx = 0; sIdx < slots.length; sIdx++) {{
                    const slot = slots[sIdx];
                    const d = slot.data || {{}};

                    // [절대 철칙 1] 엄격한 광고 배제 (CPC / 파워링크 / 쇼핑검색광고 전수 차단)
                    const isAd = (
                        !!d.ad || !!d.isAd || !!d.is_ad || !!d.adInfo || !!d.adcrUrl ||
                        (typeof d.sourceType === 'string' && d.sourceType.toUpperCase().includes('AD')) ||
                        (typeof d.cardType === 'string' && d.cardType.toUpperCase().includes('AD')) ||
                        (typeof d.sasType === 'string' && d.sasType.toUpperCase().includes('AD')) ||
                        (typeof d.type === 'string' && d.type.toUpperCase().includes('AD')) ||
                        (typeof d.productType === 'string' && d.productType.toUpperCase().includes('AD')) ||
                        (typeof d.badge === 'string' && d.badge.includes('광고')) ||
                        (typeof d.mallName === 'string' && d.mallName.includes('광고'))
                    );
                    if (isAd) continue;

                    const isCatalog = (d.cardType === 'CATALOG_CARD') || !!d.catalogMatchingId || (d.mallCount > 1);

                    organicRankCounter++;

                    const slotMid = String(d.nvMid || '');
                    const slotChanId = String(d.channelProductId || '');

                    // targetMid(내 상품) 또는 compareMid(카탈로그) 일치 여부 판정
                    const matchTarget = targetMid && (slotMid === targetMid || slotChanId === targetMid);
                    const matchCompare = compareMid && (slotMid === compareMid || slotChanId === compareMid);
                    const matchRank = (targetRank !== null) && (organicRankCounter === targetRank || d.rank === targetRank);

                    // 1순위: 단독 상품으로 매칭된 경우 (카탈로그가 아닌 일반 카드에 내 상품이 걸림)
                    if (matchTarget && !isCatalog) {{
                        foundTarget = {{
                            pageIndex: pIdx,
                            pageNumber: pageObj.page || (pIdx + 1),
                            slotIndex: sIdx,
                            rank: d.rank || organicRankCounter,
                            matchType: 'direct_seller_mid',
                            nvMid: slotMid,
                            channelProductId: slotChanId,
                            productName: (d.productName || '').replace(/<[^>]+>/g, ''),
                            mallName: d.mallName || '',
                            price: d.price || d.lowPrice || '',
                            isCatalog: false,
                            isAd: false,
                            rawSlotData: d
                        }};
                        break;
                    }}

                    // 2순위: 카탈로그로 매칭된 경우 (compareMid 또는 targetMid가 카탈로그로 걸림)
                    if (!foundTarget && (matchCompare || (matchTarget && isCatalog) || (!targetMid && matchRank))) {{
                        foundTarget = {{
                            pageIndex: pIdx,
                            pageNumber: pageObj.page || (pIdx + 1),
                            slotIndex: sIdx,
                            rank: d.rank || organicRankCounter,
                            matchType: matchCompare ? 'compare_catalog_mid' : (matchTarget ? 'nv_mid' : 'target_rank'),
                            nvMid: slotMid || compareMid || targetMid,
                            channelProductId: slotChanId,
                            productName: (d.productName || '').replace(/<[^>]+>/g, ''),
                            mallName: d.mallName || '',
                            price: d.price || d.lowPrice || '',
                            isCatalog: isCatalog,
                            isAd: false,
                            rawSlotData: d
                        }};
                        if (!isCatalog) break;
                    }}
                }}
                if (foundTarget && (!compareMid || !foundTarget.isCatalog)) break;
            }}

            return {{
                has_shp_section: true,
                has_paged_slot: true,
                has_shopping: true,
                route_to_shop_tab: !foundTarget,
                found: !!foundTarget,
                target: foundTarget,
                section_name: shpSectionName,
                total_pages: ps.length
            }};
        }} catch (e) {{
            return {{
                has_shp_section: false,
                has_paged_slot: false,
                has_shopping: false,
                error: e.toString()
            }};
        }}
    }})()
    """
    try:
        res = await cdp.evaluate(eval_js)
        if isinstance(res, dict):
            return res
    except Exception as e:
        return {"has_shopping": False, "error": str(e)}
    return {"has_shopping": False, "error": "EMPTY_RESULT"}
