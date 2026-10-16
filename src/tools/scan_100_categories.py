#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/tools/scan_100_categories.py

1회성 연구 스크립트:
다양한 100개 카테고리 검색어를 대상으로 네이버 통합검색의
1. window.naver.search.section.main
2. window.naver.search.ext.newshopping
데이터 구조를 통으로 수집하여 JSON 파일로 저장 및 유형별 분석 보고서 생성.
"""

import os
import sys
import json
import time
import urllib.parse
import asyncio
from pathlib import Path
import websockets

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.device.adb_controller import start_intent, force_stop_app
from src.browser.frida_runner import spawn_app_with_cdp
from src.browser.cdp_client import AsyncCDPClient, find_serp_debugger_url

DEVICE_ID = "R3CR70FFFEK"
CDP_PORT = 9901
OUTPUT_FILE = ROOT_DIR / "logs" / "analysis" / "category_100_scan_result.json"

KEYWORDS_100 = [
    # 1. 여성의류 (10)
    "여자 가디건", "린넨 원피스", "여성 트렌치코트", "블라우스", "슬랙스", 
    "뷔스티에", "여성 숏패딩", "청바지", "롱스커트", "반팔티",
    # 2. 남성의류 (10)
    "남자 슬랙스", "오버핏 맨투맨", "남성 셔츠", "라이더 자켓", "남자 청바지", 
    "남성 롱패딩", "카라티", "니트 조끼", "반바지", "정장 수트",
    # 3. 패션잡화 (10)
    "여성 숄더백", "에코백", "여성 로퍼", "남성 스니커즈", "볼캡", 
    "목걸이", "선글라스", "카드지갑", "백팩", "어그부츠",
    # 4. 뷰티/화장품 (10)
    "수분크림", "립밤", "선크림", "클렌징오일", "파운데이션", 
    "마스크팩", "헤어 에센스", "핸드크림", "향수", "바디워시",
    # 5. 디지털/가전 (10)
    "블루투스 이어폰", "무선청소기", "공기청정기", "전자레인지", "스마트워치", 
    "로봇청소기", "헤어드라이어", "보조배터리", "게이밍 모니터", "태블릿 거치대",
    # 6. 식품/건강식품 (10)
    "닭가슴살", "사과 5kg", "단백질쉐이크", "유산균", "강아지오메가3", 
    "김치 10kg", "쌀 20kg", "올리브유", "원두커피", "밀키트",
    # 7. 가구/인테리어 (10)
    "컴퓨터 의자", "암막커튼", "디퓨저", "토퍼 매트리스", "침대 프레임", 
    "인테리어 조명", "수납장", "좌식 테이블", "거실 러그", "스탠드 행거",
    # 8. 출산/육아 (5)
    "기저귀", "물티슈", "젖병", "카시트", "유모차",
    # 9. 스포츠/레저/캠핑 (10)
    "캠핑의자", "텐트", "요가매트", "런닝화", "낚시대", 
    "단백질 보충제", "등산화", "골프공", "자전거", "덤벨",
    # 10. 생활/주방/반려동물/자동차/취미/공구 (15)
    "KF94 마스크", "스텐 텀블러", "프라이팬", "고양이 모래", "강아지 사료", 
    "차량용 방향제", "차량용 거치대", "전동드릴", "독서대", "레고 테크닉", 
    "보드게임", "기타 줄", "캐리어 24인치", "AA 건전지", "블루투스 스피커"
]

JS_COLLECT = """
(() => {
    try {
        const secMain = window.naver?.search?.section?.main || null;
        const newshopping = window.naver?.search?.ext?.newshopping || null;
        
        let shpSections = [];
        if (Array.isArray(secMain)) {
            for (let s of secMain) {
                let str = typeof s === 'string' ? s : (s?.area || s?.id || s?.name || '');
                if (str.includes('shp')) {
                    shpSections.push({
                        raw: s,
                        code: str,
                        prefix: str.split('*')[0],
                        suffix: str.includes('*') ? str.split('*')[1] : null
                    });
                }
            }
        }
        
        let nsSummary = {};
        if (newshopping && typeof newshopping === 'object') {
            for (let nsKey of Object.keys(newshopping)) {
                const nsObj = newshopping[nsKey];
                const initState = nsObj?._INITIAL_STATE;
                const initProps = initState?.initProps;
                
                let details = {
                    has_initial_state: !!initState,
                    has_init_props: !!initProps,
                    prop_keys: initProps ? Object.keys(initProps) : []
                };
                
                // pagedSlot 여부
                if (initProps?.pagedSlot && Array.isArray(initProps.pagedSlot)) {
                    details.paged_slot = {
                        pages: initProps.pagedSlot.length,
                        total_slots: initProps.pagedSlot.reduce((acc, p) => acc + (p.slots?.length || 0), 0)
                    };
                }
                
                // fashionContents 여부
                if (initProps?.fashionContents && Array.isArray(initProps.fashionContents)) {
                    details.fashion_contents = {
                        blocks: initProps.fashionContents.length,
                        has_products: !!(initProps.fashionContents[0]?.products)
                    };
                }
                
                nsSummary[nsKey] = details;
            }
        }
        
        return {
            url: window.location.href,
            sec_main_raw: secMain,
            shp_sections: shpSections,
            newshopping_keys: newshopping ? Object.keys(newshopping) : [],
            newshopping_details: nsSummary
        };
    } catch(e) {
        return { error: e.toString() };
    }
})()
"""

async def main():
    print(f"==================================================================")
    print(f"🔬 [네이버 통합검색 100개 카테고리 전수 조사기] 시작")
    print(f"   • 대상 기기: {DEVICE_ID}")
    print(f"   • 조사 키워드: 총 {len(KEYWORDS_100)}개")
    print(f"   • 저장 위치: {OUTPUT_FILE}")
    print(f"==================================================================")

    # 1. 앱 기동 (Frida + DevTools)
    print(f"🚀 [1/3] 네이버 앱 1회 기동 및 Frida 주입...")
    first_kw = KEYWORDS_100[0]
    spawn_app_with_cdp(DEVICE_ID, CDP_PORT, target_nnb="SCANNER_SESSION_NNB")
    from src.core.profile_generator import build_intent_url
    start_intent(DEVICE_ID, build_intent_url(first_kw))
    await asyncio.sleep(3.0)

    # 2. WebSocket 연결
    print(f"🔌 [2/3] CDP WebSocket 연결 탐색...")
    ws_url = await find_serp_debugger_url(CDP_PORT, timeout=10.0)
    if not ws_url:
        print(f"❌ CDP WebSocket 연결 실패!")
        return

    all_results = []

    async with websockets.connect(ws_url, ping_interval=None, open_timeout=10.0) as ws:
        cdp = AsyncCDPClient(ws)
        print(f"✅ CDP 연결 성공: {ws_url}\n")
        print(f"📊 [3/3] 100개 검색어 순차 스캔 진행...")

        for idx, kw in enumerate(KEYWORDS_100, 1):
            t0 = time.time()
            # [절대 철칙 3 준수] ackey 탑재된 정식 인텐트 URL 사용
            from src.core.profile_generator import build_intent_url
            from src.device.adb_controller import start_intent
            nav_url = build_intent_url(kw)
            start_intent(DEVICE_ID, nav_url)

            # 페이지 로딩 대기 (최대 3초)
            data = None
            for wait_i in range(15): # 15 * 0.2s = 3.0s
                await asyncio.sleep(0.2)
                try:
                    res = await cdp.evaluate(JS_COLLECT)
                    if isinstance(res, dict) and res.get("sec_main_raw"):
                        data = res
                        break
                except Exception:
                    pass

            if not data:
                try:
                    data = await cdp.evaluate(JS_COLLECT) or {}
                except Exception as e:
                    data = {"error": str(e)}

            elapsed = round(time.time() - t0, 2)
            shp_codes = [s.get("code") for s in data.get("shp_sections", [])]
            ns_keys = data.get("newshopping_keys", [])
            
            record = {
                "index": idx,
                "keyword": kw,
                "elapsed_seconds": elapsed,
                "shp_sections": shp_codes,
                "newshopping_keys": ns_keys,
                "data": data
            }
            all_results.append(record)

            print(f"[{idx:03d}/100] '{kw:<10}' ({elapsed}s) | shp: {shp_codes} | newshopping: {ns_keys}")

    # 결과 파일 저장
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n==================================================================")
    print(f"🎉 100개 키워드 전수 조사 완료! 파일 저장: {OUTPUT_FILE}")
    print(f"==================================================================")

if __name__ == "__main__":
    asyncio.run(main())
