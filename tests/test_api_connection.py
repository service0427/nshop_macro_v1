#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Central API Allocation & Response Test Script (1:10 / 1:21 Verification)
"""

import sys
import json
import time
import requests

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.modules.task_api_client import API_HOSTS

ALL_21_DEVICES = [
    'R3CRC0B4X2F', 'R3CRC0ZCD2Z', 'R5CR80ZNCXT', 'R5CR80ZYL9K', 'R5CR82FNMVX',
    'R5CR82H78WT', 'R5CR91SH8LM', 'R5CR9336DSB', 'R5CRA0TJHLK', 'R5CRC2RDAFB',
    'R3CR70FFFEK', 'R3CR70KAZDM', 'R3CR70KB1RA', 'R3CR70SZ0JJ', 'R3CR8059XWZ',
    'R3CRB0WCGET', 'R5CR70YAG4N', 'R5CR713T5WT', 'R5CR807XTKD', 'R5CR80Z0Z9K',
    'R5CRA28JXXF'
]

HEADERS = {
    "User-Agent": "NShopMacro-ZeroReboot/2.0",
    "Content-Type": "application/json"
}

def test_api_allocate(device_count=21, dry_release=True):
    dev_subset = ALL_21_DEVICES[:device_count]
    dev_param = ",".join(dev_subset)
    print("=" * 80)
    print(f"📡 [중앙 API 할당 요청 테스트] 단말기 요청 수량: {device_count}대")
    print(f"   - 요청 단말기: {dev_subset}")
    print("=" * 80)

    for base_url in API_HOSTS:
        endpoint = f"{base_url}/api/v1/allocate"
        print(f"\n[*] 연결 시도 -> {endpoint}")
        t0 = time.time()
        try:
            res = requests.get(endpoint, params={"device_ids": dev_param}, headers=HEADERS, timeout=7.0)
            latency = round(time.time() - t0, 3)
            print(f"[*] 응답 코드: {res.status_code} ({latency}초 소요)")

            if res.status_code == 200:
                data = res.json()
                alloc_id = data.get("alloc_id")
                router = data.get("router", {})
                tasks = data.get("tasks") or data.get("jobs") or []

                print("\n" + "=" * 80)
                print(f"🎉 [할당 성공 200 OK]")
                print(f"   • Alloc ID: {alloc_id}")
                print(f"   • Router Num: {router.get('router_num')}")
                print(f"   • Endpoint: {router.get('endpoint')}")
                print(f"   • Macvlan Public IP: {router.get('macvlan_ip')}")
                print(f"   • Assigned Count (서버 표기): {router.get('assigned_count', len(tasks))}")
                print(f"   • 수신된 작업 수: {len(tasks)}개 (요청 {device_count}대 대비)")
                print("=" * 80)

                print("\n[할당된 개별 태스크 목록]")
                has_detailad = False
                for idx, t in enumerate(tasks, 1):
                    store = t.get("store_name")
                    kw = t.get("keyword")
                    dev = t.get("device_id")
                    ip = t.get("ip")
                    mid = t.get("mid")
                    title = t.get("product_title", "-")
                    is_detail = "🎯 [디테일애드]" if (store == "디테일애드" or "디테일" in (store or "")) else "  "
                    if "디테일" in str(store):
                        has_detailad = True
                    print(f"  {idx:2d}. {is_detail} [{dev}] IP:{ip:<10} | 스토어: {store:<12} | MID: {mid} | 키워드: {kw}")

                print(f"\n[*] 디테일애드 포함 여부: {'✅ 포함됨 (검증 통과)' if has_detailad else '❌ 미포함'}")

                # 테스트 목적이므로 즉시 안전 반납하여 실제 매크로 세션에 지장 없도록 처리
                if dry_release and alloc_id:
                    print(f"\n[*] [안전 조치] 테스트용 세션(alloc_id: {alloc_id}) 전량 조기 반납(/api/v1/release) 전송...")
                    rel_url = f"{base_url}/api/v1/release"
                    cancel_results = [{
                        "device_id": t.get("device_id"),
                        "status": "SUCCESS",
                        "is_searched": False,
                        "is_clicked": False,
                        "execution_sec": 0.1,
                        "public_ip": router.get("macvlan_ip", "TEST_API_CHECK")
                    } for t in tasks]
                    rel_res = requests.post(rel_url, json={"alloc_id": alloc_id, "results": cancel_results}, headers=HEADERS, timeout=6.0)
                    print(f"[✓] 반납 응답 ({rel_res.status_code}): {rel_res.text[:120]}")

                return True

            elif res.status_code == 503:
                try:
                    err = res.json()
                except Exception:
                    err = {"raw": res.text}
                code = err.get("code", "UNKNOWN")
                sub_code = err.get("sub_code", "")
                msg = err.get("message", res.text)
                sub_disp = f"/{sub_code}" if sub_code else ""
                print("-" * 80)
                print(f"⏸️ [서버 대기 503 Service Unavailable] ({base_url})")
                print(f"   • Code: [{code}{sub_disp}]")
                print(f"   • Message: {msg}")
                print(f"   • Raw Body: {json.dumps(err, ensure_ascii=False)}")
                print("-" * 80)

            else:
                print(f"[!] 비정상 응답 ({res.status_code}): {res.text[:200]}")

        except Exception as e:
            print(f"[!] 연결 에러 ({base_url}): {e}")

    return True

if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 21
    test_api_allocate(count)
