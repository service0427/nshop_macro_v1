#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/core/traffic_logger.py

MITM-Grade Network & Touch Traffic Audit Logger
------------------------------------------------
네이버 공식 앱(com.nhn.android.search) 내부 웹뷰에서 발생하는
실제 Egress HTTP/HTTPS 요청, 헤더/쿠키, 리다이렉트 체인, 네이버 FDS/비콘,
물리 터치(TouchEvent) 좌표 및 체류 스크롤을 사람이 한눈에 파악할 수 있는
타임라인 텍스트 및 JSON 리포트로 디스크에 영구 보존합니다.
"""

import os
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TRAFFIC_DIR = ROOT_DIR / "logs" / "traffic"


class TrafficAuditLogger:
    def __init__(
        self,
        task_id: Any,
        device_id: str,
        keyword: str,
        nv_mid: str,
        ip: str = "unknown",
        output_dir: Optional[Union[str, Path]] = None,
        cycle_ymd: Optional[str] = None,
        cycle_his: Optional[str] = None
    ):
        self.task_id = task_id
        self.device_id = device_id
        self.keyword = keyword
        self.nv_mid = str(nv_mid)
        self.ip = ip
        self.t0 = time.time()
        self.events: List[Dict[str, Any]] = []

        # 세션별 격리 디렉토리 설정: logs/traffic/{Ymd}/{His}/{device}/
        if output_dir:
            self.session_dir = Path(output_dir)
        else:
            ymd = cycle_ymd or time.strftime("%Y%m%d")
            his = cycle_his or time.strftime("%H%M%S")
            self.session_dir = TRAFFIC_DIR / ymd / his / device_id
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.metadata: Dict[str, Any] = {
            "task_id": task_id,
            "device_id": device_id,
            "keyword": keyword,
            "nv_mid": nv_mid,
            "ip": ip,
            "session_dir": str(self.session_dir),
            "nnb": None,
            "buc": None,
            "ssaid": None,
            "store_name": None,
            "status": "IN_PROGRESS"
        }
        TRAFFIC_DIR.mkdir(parents=True, exist_ok=True)

    def set_identity(self, nnb: Optional[str] = None, buc: Optional[str] = None, ssaid: Optional[str] = None, store_name: Optional[str] = None):
        if nnb: self.metadata["nnb"] = nnb
        if buc: self.metadata["buc"] = buc
        if ssaid: self.metadata["ssaid"] = ssaid
        if store_name: self.metadata["store_name"] = store_name

    def record_event(self, category: str, title: str, details: Optional[Dict[str, Any]] = None):
        """임의의 감사 이벤트 기록 (상대 시간 자동 계산)"""
        rel_time = round(time.time() - self.t0, 2)
        event = {
            "rel_sec": rel_time,
            "category": category,
            "title": title,
            "details": details or {}
        }
        self.events.append(event)

    def import_cdp_network_events(self, cdp_events: List[Dict[str, Any]]):
        """CDP AsyncCDPClient.network_events 리스트를 감사 이벤트로 일괄 변환 및 흡수 (중복 배제)"""
        seen_keys = set()
        for ev in self.events:
            dt = ev.get("details", {})
            u = dt.get("url") or dt.get("from_url") or ""
            if u:
                seen_keys.add((ev.get("category"), dt.get("method", "GET"), u))

        for ev in cdp_events:
            ev_type = ev.get("type")
            u = ev.get("url", "")
            ts = ev.get("timestamp") or time.time()
            rel_sec = round(ts - self.t0, 2)
            if rel_sec < 0:
                rel_sec = 0.0

            if ev_type == "redirect":
                r_key = ("HTTP_REDIRECT", "REDIRECT", ev.get("from_url", ""))
                if r_key in seen_keys:
                    continue
                seen_keys.add(r_key)
                self.events.append({
                    "rel_sec": rel_sec,
                    "category": "HTTP_REDIRECT",
                    "title": f"HTTP {ev.get('status', 302)} Redirect",
                    "details": {
                        "from_url": ev.get("from_url"),
                        "to_url": ev.get("to_url"),
                        "status": ev.get("status"),
                        "headers": ev.get("headers", {})
                    }
                })
            elif ev_type == "request":
                # FDS 비콘, searchGate, 일반 페이지 요청 구분
                is_beacon = any(k in u for k in ["lcs.naver.com", "wcs.naver.net", "nlog.naver.com", "wtm.pstatic.net"])
                is_gate = "searchGate" in u or "cr3.shopping.naver.com" in u or "cr.shopping.naver.com" in u
                cat = "BEACON_SENT" if is_beacon else ("SEARCH_GATE" if is_gate else "HTTP_REQUEST")
                req_key = (cat, ev.get("method", "GET"), u)
                if req_key in seen_keys:
                    continue
                seen_keys.add(req_key)

                self.events.append({
                    "rel_sec": rel_sec,
                    "category": cat,
                    "title": f"[{ev.get('method', 'GET')}] {u[:110]}",
                    "details": {
                        "url": u,
                        "method": ev.get("method"),
                        "initiator": ev.get("initiator"),
                        "headers": ev.get("headers", {}),
                        "hasPostData": ev.get("hasPostData", False),
                        "postData": ev.get("postData")
                    }
                })
            elif ev_type == "response":
                resp_key = ("HTTP_RESPONSE", "RESP", u)
                if resp_key in seen_keys:
                    continue
                seen_keys.add(resp_key)
                self.events.append({
                    "rel_sec": rel_sec,
                    "category": "HTTP_RESPONSE",
                    "title": f"[HTTP {ev.get('status', 200)}] {u[:100]}",
                    "details": {
                        "url": u,
                        "status": ev.get("status"),
                        "headers": ev.get("headers", {})
                    }
                })

    def update_keyword(self, keyword: str) -> None:
        """체인 탐색(Re-query) 등으로 검색어가 갱신될 때 실시간 동기화"""
        prev = self.metadata.get("keyword")
        self.metadata["keyword"] = keyword
        if "keyword_history" not in self.metadata:
            self.metadata["keyword_history"] = [prev] if prev else []
        if keyword not in self.metadata["keyword_history"]:
            self.metadata["keyword_history"].append(keyword)

    def finalize(self, status: str, error_message: Optional[str] = None) -> str:
        """감사 파일 생성 및 최신 링크 갱신"""
        self.metadata["status"] = status
        if error_message:
            self.metadata["error_message"] = error_message
        total_duration = round(time.time() - self.t0, 2)
        self.metadata["total_duration_sec"] = total_duration

        # 이벤트 시간순 정렬
        self.events.sort(key=lambda x: x.get("rel_sec", 0.0))

        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        txt_path = self.session_dir / "traffic.log"
        json_path = self.session_dir / "traffic.json"
        legacy_txt_path = self.session_dir / f"traffic_{self.device_id}_task{self.task_id}_{timestamp_str}.log"

        # 1. 사람 친화적 ASCII 타임라인 리포트 생성
        lines = []
        lines.append("=" * 95)
        lines.append(f"📡 [MITM-Grade Network & Touch Traffic Audit Log]")
        lines.append("=" * 95)
        lines.append(f"• Task ID       : {self.metadata['task_id']}")
        lines.append(f"• Device Serial : {self.metadata['device_id']}")
        lines.append(f"• Target nv_mid : {self.metadata['nv_mid']} ({self.metadata.get('store_name') or 'N-Shop Target'})")
        kw_hist = self.metadata.get("keyword_history", [])
        if len(kw_hist) > 1:
            lines.append(f"• Search Keyword: '{self.metadata['keyword']}' (Chain: {' -> '.join(kw_hist)})")
        else:
            lines.append(f"• Search Keyword: '{self.metadata['keyword']}'")
        lines.append(f"• Public Egress : {self.metadata['ip']}")
        lines.append(f"• Session Dir   : {self.session_dir}")
        lines.append(f"• Packets Dump  : {self.session_dir / 'packets'} (Individual MITM JSON files)")
        lines.append(f"• NNB Cookie    : {self.metadata.get('nnb') or '(Auto Managed)'}")
        lines.append(f"• BUC Signature : {self.metadata.get('buc') or '(Auto Managed)'}")
        lines.append(f"• SSAID         : {self.metadata.get('ssaid') or '(Auto Isolated)'}")
        lines.append(f"• Final Status  : {status} (Total {total_duration}s)")
        if error_message:
            lines.append(f"• Error Message : {error_message}")
        lines.append("-" * 95)
        lines.append(f"{'Time':<8} | {'Category':<15} | {'Description / URL / Event Data'}")
        lines.append("-" * 95)

        for ev in self.events:
            sec_str = f"+{ev.get('rel_sec', 0.0):.2f}s"
            cat = ev.get("category", "")
            title = ev.get("title", "")
            lines.append(f"{sec_str:<8} | {cat:<15} | {title}")

            # 상세 정보가 있으면 들여쓰기로 출력
            dt = ev.get("details", {})
            if cat in ("TARGET_TOUCH", "PAGING_TOUCH") and dt:
                if dt.get("page_url"):
                    lines.append(f"         ↳ [Page URL] {dt.get('page_url')}")
                if dt.get("matched_selector"):
                    lines.append(f"         ↳ [Matched Selector] {dt.get('matched_selector')}")
                if dt.get("element_info"):
                    el_info = dt.get("element_info")
                    if isinstance(el_info, dict):
                        lines.append(f"         ↳ [Element Info] Tag=<{el_info.get('tagName')}> | Class='{el_info.get('className')}' | Href='{el_info.get('href')}'")
                    else:
                        lines.append(f"         ↳ [Element Info] {el_info}")
                if dt.get("product_data"):
                    lines.append(f"         ↳ [Target Product Data JSON]:")
                    pj_str = json.dumps(dt.get("product_data"), ensure_ascii=False, indent=2)
                    for pj_line in pj_str.splitlines():
                        lines.append(f"             {pj_line}")
                lines.append(f"         ↳ [Touch Data] Coord=({dt.get('x')}, {dt.get('y')}) | Radius=({dt.get('radiusX')}x{dt.get('radiusY')}) | Force={dt.get('force')} | Hold={dt.get('hold_ms')}ms")
            elif cat == "SEARCH_GATE" and dt:
                cookie_hdr = dt.get("headers", {}).get("Cookie") or dt.get("headers", {}).get("cookie")
                ref_hdr = dt.get("headers", {}).get("Referer") or dt.get("headers", {}).get("referer")
                if cookie_hdr:
                    lines.append(f"         ↳ [Cookie] {cookie_hdr[:100]}...")
                if ref_hdr:
                    lines.append(f"         ↳ [Referer] {ref_hdr}")
            elif cat == "SESSION_RESET" and dt:
                lines.append(f"         ↳ [Clean Reset] Attempt #{dt.get('attempt')}: Keyword='{dt.get('keyword')}' | SSAID={dt.get('ssaid')} | NNB={dt.get('nnb')}")
            elif cat == "HTTP_REDIRECT" and dt:
                lines.append(f"         ↳ [From] {dt.get('from_url')}")
                lines.append(f"         ↳ [To  ] {dt.get('to_url')}")
            elif cat == "BEACON_SENT" and dt:
                lines.append(f"         ↳ [Beacon Target] {dt.get('url')[:120]}")

        lines.append("=" * 95)
        lines.append(f"💾 Report generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 95 + "\n")

        report_content = "\n".join(lines)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(report_content)

        # 레거시 호환 파일도 함께 저장
        try:
            with open(legacy_txt_path, "w", encoding="utf-8") as f:
                f.write(report_content)
        except Exception:
            pass

        # 2. JSON 원본 저장
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "metadata": self.metadata,
                "events": self.events
            }, f, ensure_ascii=False, indent=2)

        # 3. MITM-Grade 개별 패킷 JSON 파일 분할 덤프 (과거 mitm_dumps 100% 재현)
        # {001_GET_m.search.naver.com_search.naver.json, 027_POST_nlog.naver.com_nlogapp.json ...}
        import urllib.parse
        import re

        packets_dir = self.session_dir / "packets"
        packets_dir.mkdir(parents=True, exist_ok=True)
        packet_idx = 0

        for ev in self.events:
            cat = ev.get("category", "")
            if cat in ("HTTP_REQUEST", "BEACON_SENT", "SEARCH_GATE", "NATIVE_TELEMETRY", "HTTP_REDIRECT"):
                packet_idx += 1
                dt = ev.get("details", {})
                u = dt.get("url") or dt.get("from_url") or ""
                m = dt.get("method") or ("REDIRECT" if cat == "HTTP_REDIRECT" else "GET")

                parsed = urllib.parse.urlparse(u)
                host = parsed.netloc or "unknown"
                path = parsed.path or "/"

                # 파일명 생성 규칙: 001_GET_m.search.naver.com_search.naver.json
                clean_host = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', host)
                clean_path = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', path)[:40]
                fname = f"{packet_idx:03d}_{m}_{clean_host}_{clean_path}.json"

                # 쿠키 파싱
                headers = dt.get("headers", {})
                if isinstance(headers, str):
                    headers = {"raw": headers}
                cookie_str = headers.get("Cookie") or headers.get("cookie") or ""
                parsed_cookies = {}
                if isinstance(cookie_str, str) and cookie_str:
                    for part in cookie_str.split(";"):
                        if "=" in part:
                            k, v = part.strip().split("=", 1)
                            parsed_cookies[k.strip()] = v.strip()

                dump_data = {
                    "index": packet_idx,
                    "rel_sec": ev.get("rel_sec", 0.0),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.t0 + ev.get("rel_sec", 0.0))),
                    "category": cat,
                    "request": {
                        "method": m,
                        "url": u,
                        "host": host,
                        "path": path,
                        "headers": headers,
                        "cookies": parsed_cookies,
                        "body": dt.get("postData")
                    },
                    "response": {
                        "status_code": dt.get("status") or (302 if cat == "HTTP_REDIRECT" else 200),
                        "headers": dt.get("response_headers", {}),
                        "location": dt.get("to_url")
                    }
                }
                try:
                    with open(packets_dir / fname, "w", encoding="utf-8") as pf:
                        json.dump(dump_data, pf, ensure_ascii=False, indent=2)
                except Exception:
                    pass

        # 4. 최신 편의 링크 (latest_{device_id}.log 및 latest.log) 생성/덮어쓰기
        try:
            latest_dev_path = TRAFFIC_DIR / f"latest_{self.device_id}.log"
            latest_global_path = TRAFFIC_DIR / "latest.log"
            with open(latest_dev_path, "w", encoding="utf-8") as f:
                f.write(report_content)
            with open(latest_global_path, "w", encoding="utf-8") as f:
                f.write(report_content)
        except Exception:
            pass

        return str(txt_path)
