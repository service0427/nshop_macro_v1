#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/mitm/dump_addon.py

Mitmproxy 패킷 순번별 투명 로거 (Zero-Tampering Read-Only Addon)
- 어떤 요청이나 응답도 일체 변조하지 않음 (100% 읽기 전용)
- 모든 HTTP/HTTPS 요청과 응답을 순번대로 {001_POST_..., 002_GET_...}.json 파일로 덤프
- 주요 기기 식별자(SSAID/NAPP_DI, DA_DD, NNB, BUC 등)의 정상 생성 여부 시각적 대조 제공
"""

import os
import re
import json
import gzip
import time
import base64
import urllib.parse
from datetime import datetime
from threading import Lock
from typing import Dict, Any, Optional

from mitmproxy import http

class DumpLoggerAddon:
    def __init__(self):
        self.lock = Lock()
        self.counter = 0
        self.summary_list = []
        
        # 로그 저장 디렉토리 (환경변수 또는 기본 디렉토리)
        self.log_dir = os.environ.get("MITM_DUMP_DIR")
        if not self.log_dir:
            now = datetime.now()
            date_str = now.strftime("%Y%m%d")
            ts = now.strftime("%Y%m%d_%H%M%S")
            self.log_dir = f"/home/tech/nshop_macro_v1/macro_v1/logs/mitm_dumps/{date_str}/session_{ts}"
        os.makedirs(self.log_dir, exist_ok=True)
        
        print(f"\n[MITM Logger] Read-Only 패킷 덤프 활성화: {self.log_dir}\n")

    def _parse_cookies(self, cookie_header: str) -> Dict[str, str]:
        """Cookie 헤더 문자열을 딕셔너리로 파싱"""
        cookies = {}
        if not cookie_header:
            return cookies
        parts = cookie_header.split(";")
        for part in parts:
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies

    def _safe_body(self, content: bytes, content_type: str) -> Any:
        """바이너리/이미지는 축약하고 JSON이나 텍스트는 보기 쉽게 디코딩"""
        if not content:
            return None
        ct_l = (content_type or "").lower()
        if any(img in ct_l for img in ["image/", "font/", "audio/", "video/"]):
            return f"[BINARY CONTENT: {len(content)} bytes ({content_type})]"
        
        # GZIP 압축 해제 시도
        data = content
        if content.startswith(b"\x1f\x8b"):
            try:
                data = gzip.decompress(content)
            except Exception:
                pass
        
        # JSON 디코딩
        try:
            work_str = data.decode("utf-8", "ignore")
            if work_str.strip().startswith("{") or work_str.strip().startswith("["):
                return json.loads(work_str)
            if len(work_str) > 2000:
                return work_str[:2000] + f"... [TRUNCATED {len(work_str)} chars]"
            return work_str
        except Exception:
            return f"base64:{base64.b64encode(data[:500]).decode('ascii')}... ({len(data)} bytes)"

    def response(self, flow: http.HTTPFlow):
        """요청 및 응답 완료 시점에 파일로 저장 (어떤 변조도 수행하지 않음)"""
        req = flow.request
        resp = flow.response
        if not resp:
            return

        host = req.pretty_host
        # pstatic.net 정적 CDN 자산 도메인은 모니터링/덤프에서 제외
        if "pstatic.net" in host:
            return

        # 관심 대상 도메인 (네이버 및 관련 API/서비스)
        if not any(k in host for k in ["naver.com", "navercorp.com", "akamaized.net"]):
            return

        with self.lock:
            self.counter += 1
            idx = self.counter

        t_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        req_cookies = self._parse_cookies(req.headers.get("cookie", ""))
        req_ct = req.headers.get("content-type", "")
        resp_ct = resp.headers.get("content-type", "")

        # 파일명 생성: 001_GET_m.search.naver.com_search.naver.json
        clean_path = req.path.split("?")[0].replace("/", "_").strip("_")
        if not clean_path:
            clean_path = "root"
        safe_path = re.sub(r'[^a-zA-Z0-9_.-]', '', clean_path)[:60]
        safe_host = re.sub(r'[^a-zA-Z0-9_.-]', '', host)
        fn = f"{idx:03d}_{req.method}_{safe_host}_{safe_path}.json"
        file_path = os.path.join(self.log_dir, fn)

        # 핵심 기기 식별자 추출 (시각적 대조용)
        key_identifiers = {}
        for k in ["NAPP_DI", "DA_DD", "DA_DV", "NNB", "BUC", "AF_ID", "_naver_usersession_", "NAC", "NACT", "SRT30", "m_loc"]:
            if k in req_cookies:
                key_identifiers[k] = req_cookies[k]
        # 헤더에 da-dd, da-dv가 있는 경우
        if "da-dd" in req.headers:
            key_identifiers["header:da-dd"] = req.headers["da-dd"]
        if "da-dv" in req.headers:
            key_identifiers["header:da-dv"] = req.headers["da-dv"]

        # 패킷 상세 데이터
        dump_data = {
            "index": idx,
            "timestamp": t_now,
            "duration_ms": round((resp.timestamp_end - req.timestamp_start) * 1000, 2) if (resp.timestamp_end and req.timestamp_start) else 0,
            "request": {
                "method": req.method,
                "url": req.url,
                "host": host,
                "path": req.path,
                "headers": dict(req.headers),
                "key_identifiers": key_identifiers,
                "cookies": req_cookies,
                "body": self._safe_body(req.content, req_ct)
            },
            "response": {
                "status_code": resp.status_code,
                "headers": dict(resp.headers),
                "alt_svc": resp.headers.get("alt-svc", ""),
                "set_cookies": resp.headers.get_all("set-cookie"),
                "body": self._safe_body(resp.content, resp_ct)
            }
        }

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(dump_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[-] Dump write error ({fn}): {e}")

        # Summary 리스트 업데이트
        summary_item = {
            "index": idx,
            "time": t_now.split(" ")[1],
            "method": req.method,
            "host": host,
            "path": req.path.split("?")[0],
            "status": resp.status_code,
            "key_identifiers": key_identifiers,
            "dump_file": fn
        }

        with self.lock:
            self.summary_list.append(summary_item)
            summary_path = os.path.join(self.log_dir, "session_summary.json")
            try:
                with open(summary_path, "w", encoding="utf-8") as sf:
                    json.dump(self.summary_list, sf, ensure_ascii=False, indent=2)
            except Exception:
                pass

addons = [
    DumpLoggerAddon()
]
