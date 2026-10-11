#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/browser/cdp_client.py

Chrome DevTools Protocol (CDP) WebSocket 클라이언트
- DOM 검사 및 순수 오가닉 스마트스토어 상품 식별
- B 방식 정밀 터치 (Input.dispatchTouchEvent) 발사
"""

import json
import time
import random
import asyncio
import urllib.request
from typing import Dict, Any, Optional, Tuple

class AsyncCDPClient:
    def __init__(self, ws):
        self.ws = ws
        self.msg_id = 100
        self.network_events = []
        self._running = True
        self._pending = {}
        self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        try:
            while self._running:
                msg = await self.ws.recv()
                data = json.loads(msg)
                if "id" in data:
                    req_id = data["id"]
                    if req_id in self._pending and not self._pending[req_id].done():
                        self._pending[req_id].set_result(data)
                elif data.get("method") == "Network.requestWillBeSent":
                    params = data.get("params", {})
                    req = params.get("request", {})
                    u = req.get("url", "")
                    redir = params.get("redirectResponse")
                    initiator = params.get("initiator", {})
                    if redir:
                        self.network_events.append({
                            "type": "redirect",
                            "from_url": redir.get("url", ""),
                            "to_url": u,
                            "status": redir.get("status"),
                            "headers": redir.get("headers", {})
                        })
                    if any(k in u for k in ["crd", "searchGate", "nid", "smartstore", "adcr", "catalog"]):
                        top_frame = None
                        if initiator.get("stack") and initiator["stack"].get("callFrames"):
                            f = initiator["stack"]["callFrames"][0]
                            top_frame = f"{f.get('functionName')} ({f.get('url')}:{f.get('lineNumber')})"
                        self.network_events.append({
                            "type": "request",
                            "url": u,
                            "method": req.get("method", "GET"),
                            "initiator": initiator.get("type"),
                            "top_frame": top_frame
                        })
                elif data.get("method") == "Network.responseReceived":
                    resp = data.get("params", {}).get("response", {})
                    u = resp.get("url", "")
                    if any(k in u for k in ["crd", "searchGate", "nid", "smartstore", "adcr", "catalog"]):
                        self.network_events.append({
                            "type": "response",
                            "url": u,
                            "status": resp.get("status"),
                            "headers": resp.get("headers", {})
                        })
        except Exception:
            pass

    async def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> Any:
        self.msg_id += 1
        req_id = self.msg_id
        fut = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        payload = {"id": req_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(payload))
        try:
            res = await asyncio.wait_for(fut, timeout=timeout)
            return res.get("result", {})
        finally:
            self._pending.pop(req_id, None)

    async def evaluate(self, expr: str, timeout: float = 10.0) -> Any:
        res = await self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True}, timeout=timeout)
        if "result" in res and "value" in res["result"]:
            return res["result"]["value"]
        return None

    async def get_cookie(self, name: str = "NNB") -> Optional[str]:
        js = f"""
        (() => {{
            const ck = document.cookie || '';
            const m = ck.match(new RegExp('{name}=([^;]+)'));
            return m ? m[1] : null;
        }})()
        """
        return await self.evaluate(js)

    async def find_and_touch_product(self, target_mid: str) -> Tuple[bool, str, Optional[Dict[str, float]]]:
        """
        DOM에서 광고(ader, adcr)를 100% 제외하고
        순수 오가닉 target_mid 링크를 탐색하여 사람과 동일한 시선 체류,
        미세 탐색 스크롤 후 B 방식(Input.dispatchTouchEvent) 발사
        """
        # [유기적 동작 1] 검색결과 상단 훑기 시선 체류 (1.2 ~ 1.8초)
        dwell_init = random.uniform(1.2, 1.8)
        await asyncio.sleep(dwell_init)

        # [유기적 동작 2] 탐색용 미세 스크롤 다운 (180 ~ 320px)
        micro_scroll_px = random.randint(180, 320)
        await self.evaluate(f"window.scrollBy({{ top: {micro_scroll_px}, behavior: 'smooth' }})")
        await asyncio.sleep(random.uniform(0.8, 1.2))

        inspect_js = f"""
        (() => {{
            const links = Array.from(document.querySelectorAll('a[href*="searchGate"]'));
            for (let a of links) {{
                const h = a.href || '';
                if (h.includes('ader.naver.com') || h.includes('adcr.naver.com')) continue;
                const parent = a.closest('li') || a.parentElement || a;
                const text = parent.innerText || '';
                if (text.includes('광고\\n') || text.includes('AD\\n')) continue;
                if (h.includes('nv_mid={target_mid}')) {{
                    a.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                    const r = a.getBoundingClientRect();
                    return {{
                        found: true,
                        title: text.slice(0, 40).replace(/\\n/g, ' ').trim(),
                        x: r.x + r.width / 2,
                        y: r.y + r.height / 2
                    }};
                }}
            }}
            return {{ found: false }};
        }})()
        """

        res = None
        for _ in range(5):
            res = await self.evaluate(inspect_js)
            if res and res.get("found"):
                break
            await self.evaluate(f"window.scrollBy({{ top: {random.randint(380, 520)}, behavior: 'smooth' }})")
            await asyncio.sleep(random.uniform(1.2, 1.6))

        if not res or not res.get("found"):
            return False, "TARGET_NOT_FOUND", None

        # [유기적 동작 3] 클릭 직전 인지 체류 (상품명/가격 확인 1.2 ~ 1.7초)
        dwell_pre = random.uniform(1.2, 1.7)
        await asyncio.sleep(dwell_pre)

        # 스크롤 정착 후 실측 좌표 재계산
        re_coord_js = f"""
        (() => {{
            const a = document.querySelector('a[href*="{target_mid}"]');
            if (!a) return null;
            const r = a.getBoundingClientRect();
            return {{ x: r.x + r.width / 2, y: r.y + r.height / 2 }};
        }})()
        """
        coord = await self.evaluate(re_coord_js) or {"x": res["x"], "y": res["y"]}
        tx = coord["x"]
        ty = coord["y"]

        # [유기적 동작 4] 인체공학적 터치 면적(타원형 18~28px) 및 접촉 시간(75~115ms), 미세 압력 가변 모의
        touch_dur = random.uniform(0.075, 0.115)
        rad_x = round(random.uniform(18.0, 24.5), 1)
        rad_y = round(random.uniform(22.0, 30.5), 1)
        touch_force = round(random.uniform(0.88, 1.0), 2)
        await self.call("Input.dispatchTouchEvent", {
            "type": "touchStart",
            "touchPoints": [{"x": tx, "y": ty, "radiusX": rad_x, "radiusY": rad_y, "force": touch_force}]
        })
        await asyncio.sleep(touch_dur)
        await self.call("Input.dispatchTouchEvent", {
            "type": "touchEnd",
            "touchPoints": []
        })

        return True, res.get("title", ""), coord

    def close(self):
        self._running = False
        self._read_task.cancel()

async def find_serp_debugger_url(cdp_port: int, timeout: float = 10.0) -> Optional[str]:
    """네이버 통합 검색(SERP) 탭 WebSocket URL 탐색"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=1.0).read().decode()
            targets = json.loads(data)
            for t in targets:
                u = t.get("url", "")
                if ("search.naver.com" in u or "m.search.naver.com" in u) and "next.html" not in u and ("query=" in u or "where=m" in u):
                    return t.get("webSocketDebuggerUrl")
        except Exception:
            pass
        await asyncio.sleep(0.15)
    return None

async def find_product_page_debugger_url(cdp_port: int, timeout: float = 12.0) -> Optional[str]:
    """클릭 후 새로 열린 스마트스토어/네이버쇼핑 상품 상세페이지 탭 WebSocket URL 탐색"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=1.0).read().decode()
            targets = json.loads(data)
            for t in targets:
                u = t.get("url", "")
                if ("smartstore.naver.com" in u or "shopping.naver.com" in u or "products" in u) and "next.html" not in u:
                    return t.get("webSocketDebuggerUrl")
        except Exception:
            pass
        await asyncio.sleep(0.15)
    return None

async def interact_and_expand_product_page(
    ws_url: str,
    min_dwell_sec: float = 4.0
) -> Dict[str, Any]:
    """
    스마트스토어 상품 상세페이지에 접속하여:
    1. document.readyState 및 하단 '구매하기' 바 렌더링(React Hydration 완료) 확인
    2. 상세설명 영역으로 스크롤하여 '상세정보 펼쳐보기' 버튼 탐색 및 자동 확장 클릭
    3. 확장 후 전체 본문 높이 증가 검증 및 3~5초 자연스러운 유기적 체류 스크롤 수행
    """
    import websockets

    result = {
        "hydration_complete": False,
        "buy_button_active": False,
        "detail_expanded": False,
        "before_height": 0,
        "after_height": 0,
        "detail_img_count": 0,
        "dwell_duration_sec": 0.0
    }
    t0 = time.time()

    async with websockets.connect(ws_url, ping_interval=None) as ws:
        cdp = AsyncCDPClient(ws)

        # 1. 완전한 로딩(Hydration) 확인: 하단 '구매하기' 바 활성화 대기
        for _ in range(12):
            st = await cdp.evaluate("""
            (() => {
                const buyBtn = Array.from(document.querySelectorAll('button')).find(b => (b.innerText || '').includes('구매하기'));
                return {
                    ready: document.readyState === 'complete',
                    buyVisible: buyBtn && buyBtn.offsetParent !== null,
                    buyText: buyBtn ? buyBtn.innerText.replace(/\\n/g, ' ').trim() : ''
                };
            })()
            """)
            if st and st.get("ready") and st.get("buyVisible"):
                result["hydration_complete"] = True
                result["buy_button_active"] = True
                break
            await asyncio.sleep(0.6)

        # 2. 상세설명 영역으로 부드럽게 스크롤하여 '상세정보 펼쳐보기' 버튼 탐색
        await cdp.evaluate(f"window.scrollBy({{ top: {random.randint(450, 600)}, behavior: 'smooth' }})")
        await asyncio.sleep(random.uniform(1.0, 1.4))

        expand_info = await cdp.evaluate("""
        (() => {
            const btn = Array.from(document.querySelectorAll('button')).find(b => (b.innerText || '').includes('상세정보 펼쳐보기'));
            if (!btn) return { found: false };
            const beforeH = document.body.scrollHeight;
            btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
            return {
                found: true,
                beforeHeight: beforeH,
                ariaExpanded: btn.getAttribute('aria-expanded')
            };
        })()
        """)

        if expand_info and expand_info.get("found"):
            result["before_height"] = expand_info.get("beforeHeight", 0)
            await asyncio.sleep(random.uniform(0.8, 1.3))

            # '상세정보 펼쳐보기' 터치 클릭하여 본문 전체 확장!
            await cdp.evaluate("""
            (() => {
                const btn = Array.from(document.querySelectorAll('button')).find(b => (b.innerText || '').includes('상세정보 펼쳐보기'));
                if (btn) btn.click();
            })()
            """)
            await asyncio.sleep(1.8)

            # 확장 후 상태 판정
            after_st = await cdp.evaluate("""
            (() => {
                const afterH = document.body.scrollHeight;
                const seViewer = document.querySelector('.se-viewer');
                return {
                    afterHeight: afterH,
                    seHeight: seViewer ? seViewer.scrollHeight : 0,
                    imgCount: document.querySelectorAll('.se-viewer img, [class*="detail"] img').length
                };
            })()
            """)
            if after_st:
                result["after_height"] = after_st.get("afterHeight", 0)
                result["detail_img_count"] = after_st.get("imgCount", 0)
                result["detail_expanded"] = result["after_height"] > result["before_height"]

        # 3. 유기적 체류 (본문 훑기 스크롤 2회 및 체류 시간 보장)
        remaining = max(min_dwell_sec, 3.5) - (time.time() - t0)
        if remaining > 0:
            await cdp.evaluate(f"window.scrollBy({{ top: {random.randint(350, 480)}, behavior: 'smooth' }})")
            await asyncio.sleep(min(remaining / 2, 2.0))
            await cdp.evaluate(f"window.scrollBy({{ top: {random.randint(250, 380)}, behavior: 'smooth' }})")
            await asyncio.sleep(min(remaining / 2, 2.0))

        result["dwell_duration_sec"] = round(time.time() - t0, 2)
        cdp.close()

    return result
