#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/pipeline/conveyor_striker.py

무한 자가 충전 컨베이어 벨트 타격 실행기
- 21분+ 숙성 정품 NNB 인출 (소비)
- pm clear -> 웜업 -> 신생아 NNB 추출 및 저금 (자가 충전)
- 0초 인프로세스 SSAID 실시간 변조 주입
- --mitm 옵션 시 100% 읽기 전용 순번별 패킷 덤프 자동 연동
- 숙성 NNB 주입 후 타겟 Intent 직행 및 B방식 CDP 정밀 터치
- 로그인 창 0.00% 및 스마트스토어 완착 검증
"""

import time
import json
import uuid
import random
import secrets
import hashlib
import asyncio
import urllib.parse
import websockets
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from config.settings import (
    DEFAULT_DEVICE_ID,
    DEFAULT_CDP_PORT,
    CAPTURES_DIR,
    HISTORY_FILE,
    MIN_AGING_SECONDS
)
from src.core.nnb_harvester import (
    get_next_ready_nnb,
    bank_newborn_nnb,
    mark_nnb_used,
    topup_pool,
    harvest_single_packet,
    load_pool,
    save_pool
)
from src.device.adb_controller import (
    reset_pm_clear,
    update_gms_adid,
    force_stop_app,
    start_intent,
    get_top_resumed_activity,
    take_screenshot
)
from src.device.surgical_cleaner import perform_surgical_cycle
from src.browser.frida_runner import spawn_app_with_cdp
from src.browser.cdp_client import (
    AsyncCDPClient,
    find_serp_debugger_url,
    find_product_page_debugger_url,
    interact_and_expand_product_page
)
from src.mitm.mitm_manager import MitmSessionManager
from src.core.profile_generator import (
    generate_fresh_session_profile,
    generate_random_ackey,
    generate_random_search_sm,
    build_intent_url
)

def append_history(record: Dict[str, Any]):
    history = []
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append(record)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

async def execute_conveyor_cycle(
    task: Dict[str, Any],
    device_id: str = DEFAULT_DEVICE_ID,
    cdp_port: int = DEFAULT_CDP_PORT,
    use_mitm: bool = False
) -> Tuple[bool, Dict[str, Any]]:
    """
    1회용 컨베이어 벨트 타격 수행 (소비 1개 + 채굴 1개)
    - use_mitm: True일 경우 100% 읽기 전용 순번별 패킷 덤프 디렉토리 생성
    """
    kw = task["keyword"]
    mid = str(task.get("nv_mid") or task.get("target_mid") or "")
    store = task.get("store_name", "")
    t0 = time.time()

    print("=" * 75)
    print(f"🎯 [컨베이어 타격 가동] 타겟 키워드: '{kw}' | 상점: '{store}' (mid: {mid})")
    if use_mitm:
        print("  🔍 [MITM 모드 활성화] 모든 패킷을 순번대로 읽기 전용 덤프합니다 (어떤 변조도 없음).")
    print("=" * 75)

    mitm_mgr: Optional[MitmSessionManager] = None
    mitm_dir: Optional[Path] = None
    if use_mitm:
        mitm_mgr = MitmSessionManager(device_id=device_id)
        mitm_dir = mitm_mgr.start(keyword=kw)

    try:
        # 1. NNB 토큰 확보 (API에서 nnb를 직접 전달한 경우 최우선 사용, 미지정 시 로컬 풀 인출)
        if task.get("nnb"):
            aged_nnb = task["nnb"]
            aged_buc = task.get("buc", "")
            print(f" • [외부 할당 토큰] API 지정 숙성 NNB 사용: {aged_nnb}")
        else:
            aged_item = get_next_ready_nnb(MIN_AGING_SECONDS)
            if not aged_item:
                print("❌ [경고] 21분 이상 숙성된 NNB가 부족합니다. 패킷 자동 충전을 시도합니다.")
                topup_pool(target_size=50, device_id=device_id)
                aged_item = get_next_ready_nnb(MIN_AGING_SECONDS)
                if not aged_item:
                    return False, {"error": "NO_MATURE_NNB_AVAILABLE"}

            aged_nnb = aged_item["nnb"]
            aged_buc = aged_item.get("buc", "")
            age_min = (time.time() - aged_item["issued_at"]) / 60
            print(f" • [소비 토큰] NNB: {aged_nnb} (숙성 {age_min:.1f}분 경과, 발급: {aged_item.get('issued_time')})")

        # 0초 신규 독립 식별자 및 대한민국 내륙 전역 좌표 종합 발급 (완전 무작위, 패턴 100% 배제)
        profile = generate_fresh_session_profile()
        fresh_ssaid = profile["ssaid"]
        fresh_dadd = profile["dadd"]
        fresh_dadv = profile["dadv"]
        fresh_napp_di = profile["napp_di"]
        fresh_google_account = profile["google_account"]
        fresh_lat = profile["lat"]
        fresh_lng = profile["lng"]
        fresh_region = profile["region"]
        fresh_acc = profile["accuracy"]
        fresh_alt = profile["altitude"]
        fresh_bearing = profile["bearing"]
        fake_install_time = profile.get("fake_install_time")
        fake_update_time = profile.get("fake_update_time")
        fake_boot_time = profile.get("fake_boot_time")

        # 2. 캐시 보존형 정밀 초기화 및 식별자 5종 직접 주입 (Surgical Reset)
        print("🧼 [정밀 리셋] V8/HTTP 캐시 100% 보존 + 이전 세션 잔재 선별 삭제 및 신규 식별자 직접 주입...")
        surg_res = perform_surgical_cycle(
            device_id=device_id,
            aged_nnb=aged_nnb,
            aged_buc=aged_buc,
            fresh_ssaid=fresh_ssaid,
            fresh_dadd=fresh_dadd,
            fresh_dadv=fresh_dadv,
            fresh_lat=fresh_lat,
            fresh_lng=fresh_lng,
            cdp_port=cdp_port
        )
        print(f" • [정밀 주입 완료] NNB: {aged_nnb} | SSAID: {fresh_ssaid} | DA_DD: {fresh_dadd} | m_loc: {surg_res.get('m_loc')[:16]}... (소요: {surg_res['elapsed_sec']}초)")

        # 3. 1:1 무한 자가 충전 (외부 서버 공급 NNB 모드일 경우 패킷 채굴 생략)
        newborn_nnb = None
        if not task.get("nnb"):
            newborn_item = harvest_single_packet(device_id)
            if newborn_item:
                newborn_nnb = newborn_item["nnb"]
                pool = load_pool()
                pool.append(newborn_item)
                save_pool(pool)
                print(f"🏦 [자가 충전 완료] 초고속 LCS 패킷으로 신생아 NNB 저금: '{newborn_nnb}' (21분 뒤 사용 가능)")

        # 4. Frida DevTools와 함께 앱 기동 -> 타겟 상품 검색창으로 곧바로 직행! (0초 대기)
        print(f"🚀 [타겟 직행] Frida CDP 주입 및 신규 SSAID('{fresh_ssaid}')로 타겟 검색 진입: '{kw}'...")
        pid, frida_session = spawn_app_with_cdp(
            device_id, cdp_port,
            spoof_ssaid=fresh_ssaid,
            spoof_google_account=fresh_google_account,
            spoof_dadd=fresh_dadd, spoof_dadv=fresh_dadv,
            spoof_network_type="cellular",
            spoof_mcc_mnc="450_08",
            spoof_lat=fresh_lat,
            spoof_lng=fresh_lng,
            spoof_acc=fresh_acc,
            spoof_alt=fresh_alt,
            spoof_bearing=fresh_bearing,
            fake_install_time=fake_install_time,
            fake_update_time=fake_update_time,
            fake_boot_time=fake_boot_time
        )


        target_url = build_intent_url(kw)
        start_intent(device_id, target_url)
        time.sleep(3.5)

        ws_url = await find_serp_debugger_url(cdp_port, timeout=10.0)
        if not ws_url:
            print("❌ CDP 탭 탐색 실패")
            force_stop_app(device_id)
            return False, {"error": "CDP_ATTACH_FAIL"}

        touch_success = False
        prod_title = ""
        coord = None

        async with websockets.connect(ws_url, ping_interval=None) as ws:
            cdp = AsyncCDPClient(ws)
            await cdp.call("Network.enable")

            active_nnb = await cdp.get_cookie("NNB")
            print(f"🍪 [웹뷰 적용 NNB] {active_nnb} (목표: {aged_nnb})")

            # 타겟 상품 탐색 및 B 방식 터치 발사
            touch_success, prod_title, coord = await cdp.find_and_touch_product(mid)
            if touch_success:
                print(f"🎯 [타겟 상품 확인] '{prod_title}' (nv_mid: {mid})")
                print(f"📍 [정밀 실측 좌표] X={coord['x']}, Y={coord['y']}")
                print("  [✓] Input.dispatchTouchEvent 발사 완료!")
            else:
                print(f"❌ [상품 미발견] nv_mid {mid}를 SERP에서 찾지 못했습니다.")

            await asyncio.sleep(1.5)
            cdp.close()

        if not touch_success:
            force_stop_app(device_id)
            return False, {"error": "PRODUCT_TOUCH_FAILED"}

        # 6. 스마트스토어 상세페이지 접속, Hydration 확인, '상세정보 펼쳐보기' 확장 및 유기적 체류
        prod_ws = await find_product_page_debugger_url(cdp_port, timeout=12.0)
        prod_interact_res = {}
        if prod_ws:
            print("🛍️ [스마트스토어 진입] 상세페이지 CDP 연결 및 완전 로딩/상세정보 확장 가동...")
            prod_interact_res = await interact_and_expand_product_page(prod_ws, min_dwell_sec=4.0)
            if prod_interact_res.get("buy_button_active"):
                print(" • [로딩 판별 완료] 하단 '구매하기' 바 활성화 (React Hydration 100% 완료)")
            if prod_interact_res.get("detail_expanded"):
                print(f" • [상세정보 확장 완료] '상세정보 펼쳐보기' 터치 -> 본문 확장 ({prod_interact_res.get('before_height')}px -> {prod_interact_res.get('after_height')}px, 이미지: {prod_interact_res.get('detail_img_count')}장)")
            print(f" • [유기적 체류 완료] 상세 본문 훑기 및 체류 시간: {prod_interact_res.get('dwell_duration_sec', 0)}초")
        else:
            await asyncio.sleep(4.0)

        top_act = get_top_resumed_activity(device_id)
        is_login_page = ("NidLoginActivity" in top_act) or ("nid.naver.com" in top_act)
        success = (not is_login_page) and ("InAppBrowserActivity" in top_act)

        # 증적 캡처 저장
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        shot_path = CAPTURES_DIR / f"{task.get('task_id', 'task')}_{kw}_{ts_str}_{'SUCCESS' if success else 'FAIL'}.png"
        take_screenshot(device_id, shot_path)

        dur = time.time() - t0
        result_data = {
            "task_id": task.get("task_id", "manual"),
            "keyword": kw,
            "target_mid": mid,
            "store_name": store,
            "used_nnb": aged_nnb,
            "banked_nnb": newborn_nnb,
            "spoofed_ssaid": fresh_ssaid,
            "spoofed_google_account": fresh_google_account,
            "spoofed_dadd": fresh_dadd,
            "spoofed_dadv": fresh_dadv,
            "spoofed_napp_di": fresh_napp_di,
            "spoofed_coords": {
                "lat": fresh_lat,
                "lng": fresh_lng,
                "region": fresh_region,
                "accuracy": fresh_acc,
                "altitude": fresh_alt,
                "bearing": fresh_bearing
            },
            "product_interaction": prod_interact_res,
            "success": success,
            "is_login_page": is_login_page,
            "top_activity": top_act,
            "duration_sec": round(dur, 2),
            "screenshot": str(shot_path),
            "mitm_dump_dir": str(mitm_dir) if mitm_dir else None,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        if success:
            mark_nnb_used(aged_nnb, f"{kw} ({mid})")
            print("\n" + "=" * 75)
            print("🎉 [타격 대성공] 네이버 FDS 100% 프리패스 관통!")
            print(f" • 스토어 완착: '{store}' - {prod_title}")
            print(f" • 로그인 팝업: 0.00% 미발생")
            print(f" • 가상 구글계정: {fresh_google_account} (AccountManager 최심부 상시 로그인)")
            print(f" • 주입 SSAID : {fresh_ssaid}")
            print(f" • 주입 da-dd : {fresh_dadd}")
            print(f" • 주입 da-dv : {fresh_dadv} (GMS Scope: 1 SCOPE_DEVELOPER)")
            print(f" • NAPP_DI    : {fresh_napp_di}")
            print(f" • 네트워크망  : cellular (순수 OS 뿌리 연동)")
            print(f" • MCC_MNC    : 450_08 (순수 OS 뿌리 연동)")
            print(f" • 가상 위치  : {fresh_region} (위도 {fresh_lat}, 경도 {fresh_lng}, 오차 ±{fresh_acc}m) -> m_loc 자동 생성")
            print(f" • 소요 시간  : {dur:.1f}초")
            print(f" • 증적 캡처  : {shot_path}")
            if mitm_dir:
                print(f" • MITM 덤프  : {mitm_dir}")
            print("=" * 75 + "\n")
        else:
            print("\n" + "=" * 75)
            print(f"❌ [타격 실패] 차단 발생 (최상단: {top_act})")
            print("=" * 75 + "\n")

        append_history(result_data)
        force_stop_app(device_id)
        return success, result_data

    finally:
        if mitm_mgr:
            mitm_mgr.stop()
