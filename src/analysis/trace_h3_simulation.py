#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/analysis/trace_h3_simulation.py

네이버 공식 앱(com.nhn.android.search) 내부 Chromium/XWhale 웹뷰의
전체 라이프사이클에 걸친 HTTP/3 (h3) / QUIC 프로토콜 사용 구간 실측 시뮬레이터.

분석 단계:
 1. 1차 SERP 진입 (Initial Search: '날씨' or '보관백')
 2. 체류 & 스크롤 비콘 발송 (Scroll & Responsive Beacons)
 3. 동일 세션 2차 검색 / AJAX 호출 (Alt-Svc 캐시 적용 여부 확인)
 4. 오가닉 상품 클릭 및 리다이렉션 (searchGate / crd.naver.com)
 5. 스마트스토어 상세페이지 완착 및 체류 API (smartstore.naver.com / lcs / APIs)
"""

import sys
import os
import time
import json
import asyncio
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

import websockets

PROJECT_ROOT = Path("/home/tech/nshop_macro_v1")
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    DEFAULT_DEVICE_ID,
    DEFAULT_CDP_PORT,
    LOGS_DIR,
    MIN_AGING_SECONDS
)
from src.core.nnb_harvester import get_next_ready_nnb
from src.device.adb_controller import (
    reset_pm_clear,
    force_stop_app,
    start_intent,
    get_top_resumed_activity
)
try:
    from src.device.cookie_manager import extract_newborn_and_inject_aged
except ImportError:
    from src.device.surgical_cleaner import perform_surgical_cycle as extract_newborn_and_inject_aged
from src.browser.frida_runner import spawn_app_with_cdp

class NetworkProtocolTracker:
    def __init__(self):
        self.events: List[Dict[str, Any]] = []
        self.current_phase = "INIT"
        self.t0 = time.time()

    def set_phase(self, phase: str):
        self.current_phase = phase
        rel = time.time() - self.t0
        print(f"\n[{rel:6.2f}s] >>> [구간 전환] {phase} <<<")

    def record_response(self, resp: Dict[str, Any]):
        url = resp.get("url", "")
        proto = resp.get("protocol", "unknown")
        status = resp.get("status", 0)
        mime = resp.get("mimeType", "")
        headers = resp.get("headers", {})
        alt_svc = headers.get("alt-svc", "") or headers.get("Alt-Svc", "")

        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc

        evt = {
            "time_offset": round(time.time() - self.t0, 3),
            "phase": self.current_phase,
            "domain": domain,
            "url": url,
            "protocol": proto,
            "status": status,
            "mime_type": mime,
            "alt_svc": alt_svc,
            "from_disk_cache": resp.get("fromDiskCache", False)
        }
        self.events.append(evt)

        # 실시간 h3 또는 Alt-Svc 감지 시 콘솔 출력
        if proto == "h3" or "quic" in proto:
            print(f"  ⚡ [H3 감지!] {proto.upper()} | {domain} | {url[:70]} (Phase: {self.current_phase})")
        elif alt_svc:
            # alt-svc 헤더 수신 알림
            pass

async def attach_and_trace(cdp_port: int, tracker: NetworkProtocolTracker, duration: float = 30.0):
    """
    CDP 포트의 모든 활성 탭을 모니터링하며 네트워크 이벤트를 수집
    """
    attached_targets = set()
    deadline = time.time() + duration

    async def monitor_tab(ws_url: str, tab_id: str, title: str):
        print(f"[*] CDP 세션 연결: {tab_id[:8]} ({title[:30]}) -> {ws_url}")
        try:
            async with websockets.connect(ws_url, ping_interval=None) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
                while time.time() < deadline:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=0.8)
                        data = json.loads(msg)
                        method = data.get("method")
                        if method == "Network.responseReceived":
                            resp = data.get("params", {}).get("response", {})
                            tracker.record_response(resp)
                    except asyncio.TimeoutError:
                        continue
        except Exception as e:
            # 탭 닫힘 또는 이동
            pass

    tasks = []
    while time.time() < deadline:
        try:
            raw = urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=1.0).read().decode()
            targets = json.loads(raw)
            for t in targets:
                t_id = t.get("id")
                ws = t.get("webSocketDebuggerUrl")
                if ws and t_id not in attached_targets:
                    attached_targets.add(t_id)
                    t_title = t.get("title", "")
                    task = asyncio.create_task(monitor_tab(ws, t_id, t_title))
                    tasks.append(task)
        except Exception:
            pass
        await asyncio.sleep(0.5)

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

async def run_simulation(device_id: str = DEFAULT_DEVICE_ID, cdp_port: int = DEFAULT_CDP_PORT):
    tracker = NetworkProtocolTracker()

    print("=" * 80)
    print("🚀 [네이버 앱 Chromium/XWhale HTTP/3 (h3) 프로토콜 전수 실측 시뮬레이션]")
    print("=" * 80)

    # 1. 21분+ 숙성 NNB 준비
    aged_item = get_next_ready_nnb(MIN_AGING_SECONDS)
    aged_nnb = aged_item["nnb"] if aged_item else "dummy_nnb"
    aged_buc = aged_item.get("buc", "") if aged_item else ""

    # 2. 1회용 pm clear
    tracker.set_phase("PHASE_0_PM_CLEAR")
    reset_pm_clear(device_id)

    # 3. 3초 웜업 & DB 골격 생성
    tracker.set_phase("PHASE_0_WARMUP")
    start_intent(device_id, "https://m.search.naver.com/search.naver?query=날씨")
    time.sleep(3.5)
    force_stop_app(device_id)

    # 4. 숙성 NNB 주입
    extract_newborn_and_inject_aged(device_id, aged_nnb, aged_buc)

    # 5. Frida 스폰 및 CDP 포워딩
    tracker.set_phase("PHASE_0_SPAWN_CDP")
    pid, frida_session = spawn_app_with_cdp(device_id, cdp_port)
    time.sleep(1.0)

    # 백그라운드에서 CDP 트래커 시작 (총 35초간 전수 캡처)
    trace_task = asyncio.create_task(attach_and_trace(cdp_port, tracker, duration=35.0))
    await asyncio.sleep(1.0)

    # -------------------------------------------------------------
    # PHASE 1: 1차 SERP 진입 (Initial Search Query)
    # -------------------------------------------------------------
    tracker.set_phase("PHASE_1_INITIAL_SERP_QUERY")
    query_1 = "보관백"
    enc_q1 = urllib.parse.quote(query_1)
    target_url_1 = f"https://m.search.naver.com/search.naver?sm=mtp_sug.top&where=m&query={enc_q1}"
    start_intent(device_id, target_url_1)
    await asyncio.sleep(4.0)

    # -------------------------------------------------------------
    # PHASE 2: SERP 체류, 스크롤 및 로깅 비콘 발생
    # -------------------------------------------------------------
    tracker.set_phase("PHASE_2_SERP_SCROLL_AND_BEACONS")
    # CDP 통해 부드러운 스크롤 발생
    try:
        raw = urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=1.0).read().decode()
        targets = json.loads(raw)
        serp_ws = None
        for t in targets:
            if "search.naver.com" in t.get("url", "") and "next.html" not in t.get("url", ""):
                serp_ws = t.get("webSocketDebuggerUrl")
                break
        if serp_ws:
            async with websockets.connect(serp_ws, ping_interval=None) as ws:
                for step in range(3):
                    await ws.send(json.dumps({
                        "id": 100 + step,
                        "method": "Runtime.evaluate",
                        "params": {"expression": "window.scrollBy({ top: 500, behavior: 'smooth' });"}
                    }))
                    await asyncio.sleep(1.5)
    except Exception as e:
        print("[-] 스크롤 CDP 에러:", e)

    await asyncio.sleep(2.0)

    # -------------------------------------------------------------
    # PHASE 3: 동일 세션 2차 검색 (Alt-Svc 캐시 활성화 검증)
    # -------------------------------------------------------------
    tracker.set_phase("PHASE_3_SECOND_QUERY_SAME_ORIGIN")
    # 네이버 검색창에서 2차 검색어('가리개')로 이동
    query_2 = "가리개"
    enc_q2 = urllib.parse.quote(query_2)
    target_url_2 = f"https://m.search.naver.com/search.naver?sm=mtp_sug.top&where=m&query={enc_q2}"
    start_intent(device_id, target_url_2)
    await asyncio.sleep(4.0)

    # 2차 검색 SERP에서도 스크롤 수행
    try:
        if serp_ws:
            async with websockets.connect(serp_ws, ping_interval=None) as ws:
                await ws.send(json.dumps({
                    "id": 201,
                    "method": "Runtime.evaluate",
                    "params": {"expression": "window.scrollBy({ top: 600, behavior: 'smooth' });"}
                }))
    except Exception:
        pass
    await asyncio.sleep(2.0)

    # -------------------------------------------------------------
    # PHASE 4: 오가닉 스마트스토어 상품 진입 (Click & searchGate)
    # -------------------------------------------------------------
    tracker.set_phase("PHASE_4_ORGANIC_CLICK_AND_GATE")
    # 검색된 SERP 내에서 오가닉 상품 링크 탐색 및 클릭
    try:
        raw = urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=1.0).read().decode()
        targets = json.loads(raw)
        active_ws = None
        for t in targets:
            if "search.naver.com" in t.get("url", "") and "next.html" not in t.get("url", ""):
                active_ws = t.get("webSocketDebuggerUrl")
                break
        if active_ws:
            async with websockets.connect(active_ws, ping_interval=None) as ws:
                # 오가닉 링크 1개 찾아서 클릭
                find_js = """
                (() => {
                    const links = Array.from(document.querySelectorAll('a[href*="searchGate"]'));
                    for (let a of links) {
                        const h = a.href || '';
                        if (h.includes('ader.naver.com') || h.includes('adcr.naver.com')) continue;
                        const parent = a.closest('li') || a.parentElement || a;
                        if (parent.innerText.includes('광고\\n')) continue;
                        a.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        const r = a.getBoundingClientRect();
                        return { found: true, href: h, x: r.x + r.width/2, y: r.y + r.height/2 };
                    }
                    return { found: false };
                })()
                """
                await ws.send(json.dumps({"id": 301, "method": "Runtime.evaluate", "params": {"expression": find_js, "returnByValue": True}}))
                resp = await ws.recv()
                r_val = json.loads(resp).get("result", {}).get("result", {}).get("value", {})
                if r_val.get("found"):
                    tx = r_val["x"]
                    ty = r_val["y"]
                    print(f"[*] 오가닉 상품 클릭 발사: ({tx}, {ty}) -> {r_val.get('href')[:60]}")
                    await ws.send(json.dumps({
                        "id": 302,
                        "method": "Input.dispatchTouchEvent",
                        "params": {"type": "touchStart", "touchPoints": [{"x": tx, "y": ty, "radiusX": 15, "radiusY": 15, "force": 1.0}]}
                    }))
                    await asyncio.sleep(0.08)
                    await ws.send(json.dumps({
                        "id": 303,
                        "method": "Input.dispatchTouchEvent",
                        "params": {"type": "touchEnd", "touchPoints": []}
                    }))
    except Exception as e:
        print("[-] 상품 클릭 처리 중 에러:", e)

    # -------------------------------------------------------------
    # PHASE 5: 스마트스토어 랜딩 & 체류 (SmartStore WebContents)
    # -------------------------------------------------------------
    tracker.set_phase("PHASE_5_SMARTSTORE_LANDING_AND_DWELL")
    await asyncio.sleep(5.0)

    top_act = get_top_resumed_activity(device_id)
    print(f"[*] 현재 최상단 액티비티: {top_act}")

    # 트레이스 종료 대기
    await trace_task

    force_stop_app(device_id)

    # -------------------------------------------------------------
    # 결과 분석 및 리포트 작성
    # -------------------------------------------------------------
    print("\n" + "=" * 80)
    print("📊 [실측 결과 분석: 프로토콜별 통계 요약]")
    print("=" * 80)

    proto_counts = {}
    phase_proto = {}
    domain_proto = {}
    h3_events = []
    alt_svc_events = []

    for e in tracker.events:
        p = e["protocol"]
        dom = e["domain"]
        ph = e["phase"]

        proto_counts[p] = proto_counts.get(p, 0) + 1

        if ph not in phase_proto:
            phase_proto[ph] = {}
        phase_proto[ph][p] = phase_proto[ph].get(p, 0) + 1

        if dom not in domain_proto:
            domain_proto[dom] = {}
        domain_proto[dom][p] = domain_proto[dom].get(p, 0) + 1

        if p == "h3" or "quic" in p:
            h3_events.append(e)
        if e["alt_svc"]:
            alt_svc_events.append(e)

    total_reqs = len(tracker.events)
    print(f" • 총 캡처 요청 수: {total_reqs}건")
    for proto, cnt in sorted(proto_counts.items(), key=lambda x: x[1], reverse=True):
        pct = (cnt / total_reqs * 100) if total_reqs else 0
        print(f"   - {proto.upper():12s}: {cnt:4d}건 ({pct:5.1f}%)")

    print("\n" + "-" * 80)
    print("📍 [구간(Phase)별 프로토콜 분포]")
    print("-" * 80)
    for ph, counts in phase_proto.items():
        summary_str = ", ".join([f"{k.upper()}: {v}" for k, v in counts.items()])
        print(f" • [{ph:32s}] -> {summary_str}")

    print("\n" + "-" * 80)
    print("🌐 [주요 도메인별 프로토콜 분포]")
    print("-" * 80)
    for dom, counts in sorted(domain_proto.items(), key=lambda x: sum(x[1].values()), reverse=True)[:15]:
        summary_str = ", ".join([f"{k.upper()}: {v}" for k, v in counts.items()])
        print(f" • {dom:35s} -> {summary_str}")

    print("\n" + "-" * 80)
    print(f"⚡ [HTTP/3 (h3) 발생 상세 내역: 총 {len(h3_events)}건]")
    print("-" * 80)
    if not h3_events:
        print("  (h3 직접 전송 요청 없음)")
    else:
        for idx, h in enumerate(h3_events, 1):
            print(f" [{idx:2d}] {h['time_offset']:6.2f}s | Phase: {h['phase']:25s} | {h['domain']}")
            print(f"      URL: {h['url'][:90]}")

    print("\n" + "-" * 80)
    print(f"📢 [Alt-Svc 헤더(h3 지원 선언) 제공 도메인/엔드포인트: 총 {len(alt_svc_events)}건]")
    print("-" * 80)
    seen_alt_domains = set()
    for a in alt_svc_events:
        if a["domain"] not in seen_alt_domains:
            seen_alt_domains.add(a["domain"])
            print(f" • [Alt-Svc] {a['domain']:32s} (Phase: {a['phase']})")
            print(f"    헤더: {a['alt_svc']}")
            print(f"    샘플: {a['url'][:80]}")

    # 결과 JSON 저장
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = LOGS_DIR / f"h3_trace_simulation_{ts}.json"
    report_data = {
        "timestamp": ts,
        "total_requests": total_reqs,
        "protocol_summary": proto_counts,
        "phase_breakdown": phase_proto,
        "domain_breakdown": domain_proto,
        "h3_events": h3_events,
        "alt_svc_events": alt_svc_events,
        "all_events": tracker.events
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print(f"💾 [전수 패킷 로그 저장 완료] {out_file}")
    print("=" * 80 + "\n")

    return report_data

if __name__ == "__main__":
    asyncio.run(run_simulation())
