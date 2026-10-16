#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/tools/harvest_shop_candidates.py

50대 대표 대형 일반 e-커머스 키워드 무조건 쇼핑탭 진입 및 오가닉 35위 비인기 꼬리 상품 수집기
- [사용자 지침]
  1. 감자, 갓김치, 2인용쇼파, 골프장갑, 메모리폼매트리스 등 대형 일반 e-커머스 키워드 50종 전수 조회.
  2. 무조건 네이버 앱 쇼핑탭(__NEXT_DATA__)으로 진입.
  3. __NEXT_DATA__ compositeProducts 원본 전체 배열을 통 JSON으로 영구 저장.
  4. 광고(AD)를 배제한 순수 오가닉 35위(및 35~40위) 비인기 꼬리 상품을 추출하여 파일 보존.
  5. DB에 바로 저장하지 않고 파일로 보존한 후 교체 계획 수립.
"""

import os
import sys
import time
import json
import random
import asyncio
import logging
import urllib.request
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.profile_generator import (
    build_shopping_intent_url,
    generate_fresh_session_profile
)
from src.device.adb_controller import start_intent, force_stop_app
from src.device.surgical_cleaner import perform_surgical_cycle
from src.device.network_controller import get_network_controller
from src.browser.frida_runner import spawn_app_with_cdp
from src.browser.cdp_client import AsyncCDPClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ShopHarvester")

# ==============================================================================
# 50대 대표 대형 일반 e-커머스 키워드 (100% 순수 일반 쇼핑 카테고리)
# ==============================================================================
MAJOR_ECOMMERCE_KEYWORDS_50 = [
    # 1. 식품 / 신선 / 건강 (8)
    "감자", "갓김치", "고춧가루", "깐마늘", "깻잎", "돼지고기다짐육", "땅콩", "레드비트",
    # 2. 가구 / 인테리어 / 침구 (7)
    "2인용쇼파", "메모리폼매트리스", "그릇정리대", "대나무돗자리", "발매트", "빨래건조대", "도마",
    # 3. 스포츠 / 레저 / 캠핑 (7)
    "골프장갑", "골프거리측정기", "마라톤운동양말", "캠핑의자", "요가매트", "원터치텐트", "실내자전거",
    # 4. 생활 / 주방 / 욕실 (9)
    "냉면용기", "도시락가방", "도어체크", "수면안대", "손목보호대", "텀블러", "우산", "샤워기헤드", "물티슈",
    # 5. 패션 / 잡화 (7)
    "24인치캐리어", "남자반바지", "남자향수", "남자미니크로스백", "레디백", "선글라스", "리본끈",
    # 6. 가전 / 디지털 / 모바일 (9)
    "냉난방기", "차량용거치대", "보조배터리", "무선청소기", "마우스패드", "드라이기", "블루투스스피커", "선풍기", "에어프라이어",
    # 7. 문구 / 사무 / 뷰티 (3)
    "6공다이어리", "마이크커버", "폼클렌징"
]


async def find_shopping_tab_debugger_url(cdp_port: int, timeout: float = 12.0) -> Optional[str]:
    """쇼핑탭 WebSocket Debugger URL 탐색"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{cdp_port}/json/list")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                targets = json.loads(resp.read().decode())
                for t in targets:
                    if t.get("type") != "page":
                        continue
                    u = t.get("url", "")
                    if ("shopping.naver.com" in u or "msearch.shopping" in u or "search.naver.com" in u) and "next.html" not in u:
                        ws_url = t.get("webSocketDebuggerUrl")
                        if ws_url:
                            return ws_url
        except Exception:
            pass
        await asyncio.sleep(0.2)
    return None


async def harvest_keyword_products(
    cdp: AsyncCDPClient,
    device_id: str,
    keyword: str,
    cdp_port: int,
    raw_dir: Path
) -> Optional[Dict[str, Any]]:
    """
    단일 키워드에 대해 쇼핑 인텐트 URL로 진입한 후 __NEXT_DATA__ compositeProducts 전체 추출
    """
    intent_url = build_shopping_intent_url(keyword)
    logger.info(f"🔍 [{keyword}] 쇼핑탭 정식 인텐트 진입: {intent_url}")
    
    # CDP Navigation 또는 start_intent
    nav_triggered = False
    try:
        await cdp.call("Page.navigate", {"url": intent_url})
        nav_triggered = True
    except Exception:
        pass
    
    if not nav_triggered:
        start_intent(device_id, intent_url)

    # 쇼핑 화면 로드 및 __NEXT_DATA__ 파싱 대기 (최대 10초)
    extract_js = f"""
    (() => {{
        const pp = window.__NEXT_DATA__?.props?.pageProps;
        if (!pp) return null;
        const curQ = (pp.query || pp.keyword || "").trim().toLowerCase();
        const expectedQ = "{keyword}".trim().toLowerCase();
        if (curQ && expectedQ && !curQ.includes(expectedQ) && !expectedQ.includes(curQ)) {{
            // 이전 키워드 캐시 데이터일 수 있으므로 대기
            return null;
        }}
        const comp = pp.compositeProducts || pp.initialData?.products || {{}};
        const list = comp.list || pp.products || [];
        if (!list || list.length === 0) return null;

        return {{
            query: pp.query || pp.keyword || "{keyword}",
            total: comp.total || list.length,
            list: list
        }};
    }})()
    """

    data = None
    deadline = time.time() + 10.0
    while time.time() < deadline:
        try:
            data = await cdp.evaluate(extract_js)
            if data and data.get("list") and len(data["list"]) > 0:
                break
        except Exception:
            pass
        await asyncio.sleep(0.3)

    if not data or not data.get("list"):
        # start_intent 재발송 후 신규 탭 재스캔
        start_intent(device_id, intent_url)
        ws_url = await find_shopping_tab_debugger_url(cdp_port, timeout=4.0)
        if ws_url and ws_url != getattr(cdp, "ws_url", ""):
            import websockets
            new_ws = await websockets.connect(ws_url, ping_interval=None)
            cdp = AsyncCDPClient(new_ws)
            cdp.ws_url = ws_url
            for _ in range(15):
                data = await cdp.evaluate(extract_js)
                if data and data.get("list"):
                    break
                await asyncio.sleep(0.3)

    if not data or not data.get("list"):
        logger.warning(f"⚠️ [{keyword}] __NEXT_DATA__ 상품 데이터를 가져오지 못했습니다.")
        return None

    # Raw products 원본 통째로 JSON 저장
    raw_dir.mkdir(parents=True, exist_ok=True)
    clean_name = "".join(c for c in keyword if c.isalnum() or c in (" ", "_", "-")).strip()
    raw_file = raw_dir / f"{clean_name}_products.json"
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"💾 [{keyword}] 원본 상품 {len(data['list'])}개 통 JSON 백업 완료 -> {raw_file}")
    return data


def extract_organic_candidates(raw_data: Dict[str, Any], keyword: str) -> List[Dict[str, Any]]:
    """
    추출된 raw 데이터에서 광고(AD)를 배제하고 오가닉 35위~40위 상품 선별 (35위 필수 포함)
    """
    items = raw_data.get("list", [])
    organic_list = []
    org_rank = 0

    for card in items:
        it = card.get("item", card)
        # 광고 여부 판별 (CPC / 쇼핑검색광고 완전 배제)
        if it.get("ad") or it.get("isAd") or it.get("cardType") == "AD_CARD":
            continue

        org_rank += 1
        it_id = str(it.get("id") or it.get("nvMid") or it.get("channelProductId") or "")
        cat_id = str(it.get("catalogMatchingId") or "")
        title = it.get("productTitle") or it.get("productName") or it.get("title") or ""
        mall = it.get("mallName") or it.get("channelName") or "-"
        is_catalog = bool((it.get("mallCount", 0) > 1) or cat_id)
        low_price = it.get("lowPrice") or it.get("price") or 0

        clean_item = {
            "keyword": keyword,
            "organic_rank": org_rank,
            "nv_mid": it_id,
            "catalog_id": cat_id,
            "is_catalog": is_catalog,
            "product_title": title.replace("<mark>", "").replace("</mark>", "").strip(),
            "mall_name": mall,
            "price": low_price,
            "harvested_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        organic_list.append(clean_item)

    # 35위 ~ 40위 필터링
    candidates = [item for item in organic_list if 35 <= item["organic_rank"] <= 40]
    return candidates


async def run_harvester(
    device_id: str,
    keywords: List[str],
    cdp_port: int = 9222,
    output_dir: Optional[Path] = None
) -> Dict[str, Any]:
    base_out = output_dir or (PROJECT_ROOT / "logs" / "harvest")
    raw_dir = base_out / "raw"
    cand_file = base_out / "candidates_35_40.json"
    rank35_file = base_out / "exact_rank35_targets.json"
    base_out.mkdir(parents=True, exist_ok=True)

    print("=" * 85)
    print("🌾 [네이버 쇼핑 50대 대표 대형 키워드 35위 오가닉 비인기 상품 수집기 가동]")
    print(f"   • 대상 기기     : {device_id} (포트: {cdp_port})")
    print(f"   • 수집 키워드 수 : {len(keywords)}개 대형 일반 e-커머스 카테고리")
    print(f"   • 저장 경로     : {base_out}")
    print(f"   • 핵심 타겟     : 순수 오가닉 35위 (광고 0건, 타사/자연구매 배제 꼬리 상품)")
    print("=" * 85)

    # 1. 고속 로컬 이더넷 통신망 점검 및 기기 터널링
    net_ctrl = get_network_controller("local")
    net_ctrl.setup()
    net_ctrl.connect_devices([device_id])
    ver = net_ctrl.verify_naver_connectivity(device_id, max_retries=3)
    if not ver.get("success"):
        logger.warning(f"⚠️ 네이버 통신 검증 경고 (계속 진행): {ver}")

    # 2. 단말기 1회용 클린 초기화 & Frida 스폰
    profile = generate_fresh_session_profile()
    logger.info(f"🧹 [{device_id}] 단말기 클린 초기화 및 6대 훅 스폰...")
    perform_surgical_cycle(
        device_id=device_id,
        aged_nnb="TEMP_HARVEST_NNB",
        aged_buc="",
        fresh_ssaid=profile["ssaid"],
        fresh_dadd=profile["dadd"],
        fresh_dadv=profile["dadv"],
        fresh_lat=profile["lat"],
        fresh_lng=profile["lng"],
        cdp_port=cdp_port
    )
    spawn_app_with_cdp(
        device_id=device_id,
        cdp_port=cdp_port,
        spoof_ssaid=profile["ssaid"],
        spoof_google_account=profile["google_account"],
        spoof_dadd=profile["dadd"],
        spoof_dadv=profile["dadv"],
        spoof_lat=profile["lat"],
        spoof_lng=profile["lng"],
        target_nnb="TEMP_HARVEST_NNB",
        clean_mode=True
    )

    # 첫 키워드로 진입하여 기본 CDP 연결 확보
    first_url = build_shopping_intent_url(keywords[0])
    start_intent(device_id, first_url)
    ws_url = await find_shopping_tab_debugger_url(cdp_port, timeout=15.0)
    if not ws_url:
        logger.error("❌ 쇼핑탭 CDP 연결 실패")
        force_stop_app(device_id)
        return {"success": False, "error": "CDP_CONNECT_FAILED"}

    import websockets
    ws = await websockets.connect(ws_url, ping_interval=None)
    cdp = AsyncCDPClient(ws)
    cdp.ws_url = ws_url

    all_candidates = []
    exact_rank35_list = []
    success_count = 0

    try:
        for idx, kw in enumerate(keywords, 1):
            print(f"\n[{idx:02d}/{len(keywords):02d}] 🚀 키워드: '{kw}' 수집 시작...")
            t0 = time.time()
            raw_data = await harvest_keyword_products(cdp, device_id, kw, cdp_port, raw_dir)
            if not raw_data:
                logger.warning(f"[-] '{kw}' 수집 실패 (건너뜀)")
                continue

            cands = extract_organic_candidates(raw_data, kw)
            dur = round(time.time() - t0, 2)
            
            # 정확히 35위 상품 포착
            target_35 = next((c for c in cands if c["organic_rank"] == 35), None)
            if target_35:
                exact_rank35_list.append(target_35)
                print(f"   ↳ 🎯 [35위 포착] MID: {target_35['nv_mid']} | 몰: {target_35['mall_name'][:12]} | 가격: {target_35['price']}원 | {target_35['product_title'][:28]}")
            else:
                print(f"   ↳ ⚠️ 35위 상품 미발견 (전체 {len(raw_data.get('list', []))}개 중 오가닉 {len(cands)}개)")

            all_candidates.extend(cands)
            success_count += 1

            # 자연스러운 브라우징 완충 딜레이
            await asyncio.sleep(random.uniform(1.0, 1.5))

    finally:
        try:
            await ws.close()
        except Exception:
            pass
        force_stop_app(device_id)

    # 선별된 35~40위 후보군 전체 보존
    with open(cand_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_keywords": len(keywords),
            "succeeded_keywords": success_count,
            "total_candidates": len(all_candidates),
            "candidates": all_candidates
        }, f, ensure_ascii=False, indent=2)

    # 35위 단독 타겟 상품 파일 보존
    with open(rank35_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_targets": len(exact_rank35_list),
            "targets": exact_rank35_list
        }, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 85)
    print(f"🎉 [50대 대표 키워드 수집 완료] {success_count}/{len(keywords)}개 키워드 성공")
    print(f"   • 선별된 35위 단독 타겟 수 : {len(exact_rank35_list)}개")
    print(f"   • 35~40위 전체 후보군 수   : {len(all_candidates)}개")
    print(f"   • 35위 단독 타겟 파일     : {rank35_file}")
    print(f"   • 35~40위 전체 후보 파일   : {cand_file}")
    print("=" * 85)

    return {
        "success": True,
        "success_count": success_count,
        "rank35_count": len(exact_rank35_list),
        "rank35_file": str(rank35_file),
        "candidates_file": str(cand_file)
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Harvest exact 35-rank organic products for 50 major keywords")
    parser.add_argument("-d", "--device", type=str, default=None, help="ADB Device ID")
    parser.add_argument("-p", "--port", type=int, default=9222, help="CDP Port")
    parser.add_argument("--limit", type=int, default=50, help="수집할 키워드 수")
    parser.add_argument("--keyword", type=str, default=None, help="단일 키워드 테스트")
    args = parser.parse_args()

    target_device = args.device
    if not target_device:
        from src.device.adb_controller import get_connected_devices
        devs = get_connected_devices()
        if not devs:
            print("❌ 연결된 ADB 단말기가 없습니다.")
            sys.exit(1)
        target_device = devs[0]

    if args.keyword:
        keywords = [args.keyword.strip()]
    else:
        keywords = MAJOR_ECOMMERCE_KEYWORDS_50[:args.limit]

    loop = asyncio.get_event_loop()
    res = loop.run_until_complete(run_harvester(
        device_id=target_device,
        keywords=keywords,
        cdp_port=args.port
    ))
    sys.exit(0 if res.get("success") else 1)


if __name__ == "__main__":
    main()
