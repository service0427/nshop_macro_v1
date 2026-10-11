#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/core/api_client.py

Central Task & NNB Management API Client:
- Connects to http://114.207.112.173:8000
- Robust HTTP with exponential backoff retries (1s, 2s, 4s)
- Safe payload sanitization:
  - Maps detailed status to DB ENUM ('SUCCESS' or 'FAILED')
  - Injects failure reason and detailed stats into 'memo' (up to 200 chars)
  - Passes device_id, duration_seconds, ranks, search_type, match_type
- Distinct NO_TASK / Cooldown handling (does not treat cooldown as error)
"""

import time
import json
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Union, Tuple

logger = logging.getLogger("CentralApiClient")

DEFAULT_API_BASE = "http://114.207.112.173:8000"

class CentralApiClient:
    def __init__(self, base_url: str = DEFAULT_API_BASE, timeout: float = 15.0, max_retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

    def _http_request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
        """
        내부 HTTP 요청 헬퍼 (지수 백오프 재시도 탑재)
        반환: (http_status, json_data)
        """
        url = f"{self.base_url}{path}"
        headers = {
            "User-Agent": "NShopCentralClient/2.0",
            "Accept": "application/json"
        }
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        last_err = None
        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    resp_data = resp.read().decode("utf-8")
                    return resp.status, json.loads(resp_data)
            except urllib.error.HTTPError as e:
                # 404 (작업 없음 등)은 즉시 반환하여 불필요한 재시도 배제
                try:
                    err_json = json.loads(e.read().decode("utf-8"))
                except Exception:
                    err_json = {"error": f"HTTP {e.code}: {e.reason}", "success": False}
                if e.code in (400, 404, 405):
                    return e.code, err_json
                last_err = e
            except Exception as e:
                last_err = e

            if attempt < self.max_retries - 1:
                sleep_dur = 1.0 * (2 ** attempt)
                time.sleep(sleep_dur)

        return 500, {"error": str(last_err), "success": False}

    def check_health(self) -> Dict[str, Any]:
        """서버 헬스체크: GET /health"""
        status_code, data = self._http_request("GET", "/health")
        return data

    def get_nnb_status(self) -> Dict[str, Any]:
        """NNB 풀 상태 조회: GET /api/v1/nnb/status"""
        status_code, data = self._http_request("GET", "/api/v1/nnb/status")
        return data

    def assign_task(self, device_id: str, task_id: Optional[Union[str, int]] = None) -> Dict[str, Any]:
        """
        작업 할당 요청: GET /api/v1/task/assign?device_id=...
        - 작업 존재 시: {"success": True, "task_id": 123, "keyword": "...", ...}
        - 쿨다운/작업 부재(NO_TASK) 시: {"success": False, "is_no_task": True, "message": "..."}
        """
        if task_id:
            path = f"/api/v1/task/assign?task_id={task_id}"
        else:
            path = f"/api/v1/task/assign?device_id={device_id}"

        status_code, data = self._http_request("GET", path)
        if status_code == 404:
            return {
                "success": False,
                "is_no_task": True,
                "message": data.get("error") or data.get("message") or "할당 가능한 작업이 없습니다 (스토어 쿨다운 대기 중)"
            }

        if not data.get("success"):
            data["is_no_task"] = True
        return data

    def report_task(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        작업 완료/실패 보고: POST /api/v1/task/report
        - DB status ENUM 제약(SUCCESS/FAILED) 100% 준수
        - memo 필드에 상세 상태 및 에러 메시지(최대 200자) 주입
        """
        raw_task_id = result.get("task_id")
        try:
            task_id_val = int(raw_task_id)
        except (ValueError, TypeError):
            task_id_val = raw_task_id

        is_success = bool(result.get("success", False))
        db_status = "SUCCESS" if is_success else "FAILED"

        # memo 필드 구축 (성공 시 순위/랜딩, 실패 시 세부 상태 및 원인)
        if is_success:
            s_rank = result.get("rank_info", {}).get("shopping_rank") or result.get("shopping_rank")
            memo_str = f"성공 (쇼핑순위: {s_rank or 'SERP'}위, 몰: {result.get('store_name') or ''})"
        else:
            detail_st = result.get("status", "FAILED")
            err_msg = result.get("error_message") or ""
            memo_str = f"[{detail_st}] {err_msg}".strip()
        memo_str = memo_str[:200]

        payload = {
            "task_id": task_id_val,
            "success": is_success,
            "status": db_status,
            "search_type": result.get("search_type") or ("m.search" if result.get("rank_info", {}).get("serp_rank") else "msearch"),
            "serp_rank": result.get("rank_info", {}).get("serp_rank"),
            "shopping_rank": result.get("rank_info", {}).get("shopping_rank"),
            "shopping_page": result.get("rank_info", {}).get("shopping_page"),
            "match_type": result.get("match_type"),
            "login_detected": bool(result.get("login_detected", False)),
            "device_id": result.get("device_id"),
            "store_name": result.get("store_name"),
            "duration_seconds": round(float(result.get("duration_seconds", 0.0)), 2),
            "memo": memo_str
        }

        status_code, data = self._http_request("POST", "/api/v1/task/report", payload=payload)
        return data
