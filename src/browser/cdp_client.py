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
from typing import Dict, Any, Optional, Tuple, Callable, List, Union


class CDPResponse:
    """Playwright/Puppeteer 스타일의 CDP Response 래퍼"""
    def __init__(
        self,
        url: str,
        status: int,
        headers: Dict[str, Any],
        mime_type: str = "",
        request_id: Optional[str] = None
    ):
        self.url = url
        self.status = status
        self.headers = {k.lower(): v for k, v in headers.items()} if headers else {}
        self.mime_type = mime_type
        self.request_id = request_id
        self.timestamp = time.time()

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def is_captcha(self) -> bool:
        """429 Too Many Requests 또는 실제 캡차/챌린지 차단 응답 여부 (정적 리소스 오탐 원천 차단)"""
        if self.status == 429:
            return True

        u_lower = self.url.lower()
        mime_lower = (self.mime_type or "").lower()

        # 1. 정적 에셋(JS, CSS, 이미지, 폰트 등)은 단순 리소스 로딩이므로 차단 패킷이 아님
        # 특히 ncpt.naver.com/static/ncaptcha-api.js 같은 라이브러리 스크립트는 항상 200 OK로 다운로드됨
        if any(mime_lower.startswith(p) for p in ("image/", "font/", "text/css", "application/javascript", "text/javascript")):
            return False
        if any(u_lower.endswith(ext) or f"{ext}?" in u_lower for ext in (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2")):
            return False
        if "ncpt.naver.com/static/" in u_lower:
            return False

        # 2. 실제 차단/챌린지 응답 (403/400 차단 응답)
        if self.status in (403, 400) and any(k in u_lower for k in ("captcha", "challenge")):
            return True

        # 3. 메인 도큐먼트가 명시적인 캡차 차단 전용 URL로 응답한 경우 (단, query 파라미터 값 제외)
        if "/captcha" in u_lower and not any(k in u_lower for k in ("query=", "keyword=", "msearch.shopping", "search.naver")):
            return True

        return False

    @property
    def is_login_redirect(self) -> bool:
        """302 로그인 리다이렉트 또는 nidlogin 페이지 여부"""
        loc = (self.headers.get("location") or "").lower()
        if self.status in (301, 302, 303, 307, 308) and "nidlogin" in loc:
            return True
        return "nidlogin.login" in self.url.lower()

    @property
    def is_access_blocked(self) -> bool:
        """네이버 FDS 쇼핑/검색 서비스 일시 접속 제한 패킷 여부"""
        u_lower = self.url.lower()
        if self.status in (403, 429) and any(k in u_lower for k in ("shopping", "search", "msearch")):
            return True
        if "sus_val" in u_lower:
            return True
        return False

    def __repr__(self) -> str:
        return f"<CDPResponse status={self.status} url='{self.url[:70]}'>"


class CaptchaBlockedException(Exception):
    """네이버 FDS 캡차/보안확인 차단 패킷 감지 예외"""
    def __init__(self, url: str, status: int, message: str = "네이버 보안 확인(CAPTCHA) 감지"):
        super().__init__(f"{message} (status: {status}, url: {url[:80]})")
        self.url = url
        self.status = status


class AccessBlockedException(Exception):
    """네이버 FDS 서비스 접속 일시 제한 패킷 감지 예외"""
    def __init__(self, url: str, status: int = 0, message: str = "쇼핑 서비스 접속이 일시적으로 제한되었습니다 (FDS IP 차단)"):
        super().__init__(f"{message} (status: {status}, url: {url[:80]})")
        self.url = url
        self.status = status


class LoginRedirectException(Exception):
    """네이버 로그인 리다이렉트 감지 예외"""
    def __init__(self, url: str, redirect_url: str = "", message: str = "네이버 로그인 화면 리다이렉트 감지"):
        super().__init__(f"{message} (target: {redirect_url or url})")
        self.url = url
        self.redirect_url = redirect_url


class AsyncCDPClient:
    def __init__(self, ws):
        self.ws = ws
        self.msg_id = 100
        self.network_events = []
        self._running = True
        self._pending = {}
        # Playwright 스타일 비동기 이벤트 웨이터 리스트
        self._response_waiters: List[Tuple[Callable[[CDPResponse], bool], asyncio.Future, bool]] = []
        self._nav_waiters: List[Tuple[Callable[[str], bool], asyncio.Future]] = []
        # 최근 30개 응답 링버퍼 (빠른 패킷 유실 방지)
        self.recent_responses: List[CDPResponse] = []
        self.current_url: str = ""
        self.external_mall_detected: Optional[str] = None
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

                # Page 네비게이션 감지
                elif data.get("method") == "Page.frameNavigated":
                    frame = data.get("params", {}).get("frame", {})
                    if not frame.get("parentId"):  # 메인 프레임 네비게이션
                        nav_url = frame.get("url", "")
                        self.current_url = nav_url
                        # 네비게이션 대기자 확인
                        rem_nav = []
                        for predicate, fut in self._nav_waiters:
                            if not fut.done():
                                try:
                                    if predicate(nav_url):
                                        fut.set_result(nav_url)
                                    else:
                                        rem_nav.append((predicate, fut))
                                except Exception as pe:
                                    fut.set_exception(pe)
                        self._nav_waiters = rem_nav

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
                    telemetry_domains = ["crd", "searchGate", "nid", "smartstore", "brand.naver.com", "adcr", "catalog", "lcs.naver.com", "wcs.naver.net", "nlog.naver.com", "wtm.pstatic.net", "shopping.naver.com", "search.naver.com"]
                    if any(k in u for k in telemetry_domains):
                        top_frame = None
                        if initiator.get("stack") and initiator["stack"].get("callFrames"):
                            f = initiator["stack"]["callFrames"][0]
                            top_frame = f"{f.get('functionName')} ({f.get('url')}:{f.get('lineNumber')})"
                        self.network_events.append({
                            "timestamp": round(time.time(), 3),
                            "type": "request",
                            "url": u,
                            "method": req.get("method", "GET"),
                            "headers": req.get("headers", {}),
                            "hasPostData": req.get("hasPostData", False),
                            "postData": req.get("postData"),
                            "initiator": initiator.get("type"),
                            "resource_type": params.get("type"),
                            "top_frame": top_frame
                        })

                elif data.get("method") == "Network.responseReceived":
                    resp_data = data.get("params", {}).get("response", {})
                    u = resp_data.get("url", "")
                    status = resp_data.get("status", 200)
                    headers = resp_data.get("headers", {})
                    mime = resp_data.get("mimeType", "")
                    req_id = data.get("params", {}).get("requestId")

                    cdp_resp = CDPResponse(url=u, status=status, headers=headers, mime_type=mime, request_id=req_id)
                    self.recent_responses.append(cdp_resp)
                    if len(self.recent_responses) > 40:
                        self.recent_responses.pop(0)

                    telemetry_domains = ["crd", "searchGate", "nid", "smartstore", "brand.naver.com", "adcr", "catalog", "lcs.naver.com", "wcs.naver.net", "nlog.naver.com", "wtm.pstatic.net", "shopping.naver.com", "search.naver.com"]
                    if any(k in u for k in telemetry_domains):
                        self.network_events.append({
                            "timestamp": round(time.time(), 3),
                            "type": "response",
                            "url": u,
                            "status": status,
                            "headers": headers
                        })

                    # [핵심] Playwright 스타일 _response_waiters 처리 (0.01초 즉시 발화)
                    rem_waiters = []
                    for predicate, fut, check_errors in self._response_waiters:
                        if fut.done():
                            continue
                        try:
                            # 1. 전역 에러/차단 패킷 즉시 감지 (Fast-Fail)
                            if check_errors:
                                if cdp_resp.is_access_blocked:
                                    fut.set_exception(AccessBlockedException(u, status))
                                    continue
                                if cdp_resp.is_captcha:
                                    fut.set_exception(CaptchaBlockedException(u, status))
                                    continue
                                if cdp_resp.is_login_redirect:
                                    fut.set_exception(LoginRedirectException(u, headers.get("location", "")))
                                    continue

                            # 2. 조건 매칭 검사
                            if predicate(cdp_resp):
                                fut.set_result(cdp_resp)
                            else:
                                rem_waiters.append((predicate, fut, check_errors))
                        except Exception as pe:
                            fut.set_exception(pe)
                    self._response_waiters = rem_waiters

        except Exception:
            pass

    async def wait_for_response(
        self,
        url_or_predicate: Union[str, Callable[[CDPResponse], bool]],
        timeout: float = 8.0,
        check_errors: bool = True,
        since_timestamp: Optional[float] = None
    ) -> CDPResponse:
        """
        Playwright의 page.waitForResponse()와 100% 동일한 비동기 패킷 감시 메서드.
        - url_or_predicate: URL에 포함될 문자열(str) 또는 매칭 함수 lambda resp: bool
        - check_errors: 429(캡차), 302(로그인) 패킷 포착 시 즉시 예외 발생
        - since_timestamp: 해당 시점 이후에 도착한 패킷만 매칭 (과거 패킷 오탐 방지)
        - 타임아웃 도달 시 asyncio.TimeoutError 발생
        """
        if isinstance(url_or_predicate, str):
            pat = url_or_predicate
            predicate = lambda r: pat in r.url
        else:
            predicate = url_or_predicate

        # 1. 최근 1.5초 이내에 이미 도착한 패킷 중에 조건 만족하는 것이 있는지 초고속 검사 (Ring Buffer Fast Path)
        now = time.time()
        for r in reversed(self.recent_responses):
            if since_timestamp is not None and r.timestamp < since_timestamp:
                continue
            if now - r.timestamp < 1.5:
                if check_errors:
                    if r.is_access_blocked:
                        raise AccessBlockedException(r.url, r.status)
                    if r.is_captcha:
                        raise CaptchaBlockedException(r.url, r.status)
                    if r.is_login_redirect:
                        raise LoginRedirectException(r.url, r.headers.get("location", ""))
                if predicate(r):
                    return r

        # 2. 미래에 수신될 패킷을 기다리는 Future 등록
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._response_waiters.append((predicate, fut, check_errors))

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            # 타임아웃 등으로 이탈 시 대기자 목록에서 정리
            self._response_waiters = [(p, f, c) for p, f, c in self._response_waiters if f is not fut]

    async def wait_for_navigation(
        self,
        expected_url_pattern: Optional[str] = None,
        timeout: float = 8.0
    ) -> str:
        """Playwright의 page.waitForURL()과 동일한 메인 프레임 네비게이션 대기"""
        if expected_url_pattern:
            predicate = lambda u: expected_url_pattern in u
        else:
            predicate = lambda u: True

        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._nav_waiters.append((predicate, fut))

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._nav_waiters = [(p, f) for p, f in self._nav_waiters if f is not fut]

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

    async def evaluate(self, expr: str, timeout: float = 10.0, await_promise: bool = True) -> Any:
        res = await self.call("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": await_promise
        }, timeout=timeout)
        if "exceptionDetails" in res:
            exc = res["exceptionDetails"]
            text = exc.get("text", "")
            desc = exc.get("exception", {}).get("description", "")
            import logging
            logging.getLogger("AsyncCDPClient").error(f"❌ [CDP Runtime.evaluate Exception] {text}: {desc}")
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
                if t.get("type") != "page":
                    continue
                u = t.get("url", "")
                if ("search.naver.com" in u or "m.search.naver.com" in u or "shopping.naver.com" in u) and "next.html" not in u and ("query=" in u or "where=m" in u):
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
                if t.get("type") != "page":
                    continue
                u = t.get("url", "")
                if not u or "next.html" in u or "about:blank" in u or "chrome://" in u:
                    continue
                # 1. 스마트스토어/브랜드스토어/네이버쇼핑 상세페이지
                is_naver = any(k in u for k in ["smartstore.naver.com", "brand.naver.com", "shopping.naver.com"])
                if is_naver and ("products" in u or "product" in u or "detail" in u or "smartstore" in u):
                    return t.get("webSocketDebuggerUrl")
                # 2. 일반 외부몰 상세페이지 (쿠팡, 11번가, 일반 쇼핑몰 등)
                if any(k in u for k in ["/products/", "/product/", "/vp/products/", "/item/", "/goods/", "coupang.com", "11st.co.kr", "gmarket.co.kr", "auction.co.kr"]):
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
            btn.scrollIntoView({ behavior: 'instant', block: 'center' });
            const rect = btn.getBoundingClientRect();
            return {
                found: true,
                beforeHeight: beforeH,
                ariaExpanded: btn.getAttribute('aria-expanded'),
                x: rect.left + rect.width / 2,
                y: rect.top + rect.height / 2
            };
        })()
        """)

        if expand_info and expand_info.get("found"):
            result["before_height"] = expand_info.get("beforeHeight", 0)
            btn_x = expand_info.get("x", 180.0)
            btn_y = expand_info.get("y", 400.0)
            await asyncio.sleep(random.uniform(0.8, 1.3))

            # [철칙 준수] DOM btn.click() 완전 배제 -> CDP Input.dispatchTouchEvent 실물 물리 탭 발송
            try:
                await cdp.call("Input.dispatchTouchEvent", {
                    "type": "touchStart",
                    "touchPoints": [{"x": btn_x, "y": btn_y, "radiusX": 20.0, "radiusY": 25.0, "force": 0.9}]
                })
                await asyncio.sleep(random.uniform(0.06, 0.12))
                await cdp.call("Input.dispatchTouchEvent", {
                    "type": "touchEnd",
                    "touchPoints": []
                })
            except Exception:
                pass
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
