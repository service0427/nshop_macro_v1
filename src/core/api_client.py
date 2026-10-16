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
from typing import Dict, Any, Optional, Union, Tuple, List

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

    def assign(
        self,
        device_ids: Union[str, List[str]],
        ip: Optional[str] = None,
        task_id: Optional[Union[str, int]] = None,
        nv_mid: Optional[str] = None,
        min_age_seconds: int = 1200,
        exclude_mids: Optional[Union[str, List[str], set]] = None
    ) -> Dict[str, Any]:
        """
        [통합 작업 할당 요청] GET /api/v1/task/assign?device_ids=...&ip=...
        - 단일/복수 단말기 지원
        - 외부 LTE IP 전달 지원
        - exclude_mids: 특정 상품(NOT_FOUND 등) 배제 및 다른 랜덤 상품 강제 할당 지원
        """
        if isinstance(device_ids, list):
            dev_str = ",".join(str(d).strip() for d in device_ids if str(d).strip())
        else:
            dev_str = str(device_ids).strip()

        params = [f"device_ids={dev_str}"]
        if ip:
            params.append(f"ip={ip}")
        if task_id:
            params.append(f"task_id={task_id}")
        if nv_mid:
            params.append(f"nv_mid={nv_mid}")
        if min_age_seconds:
            params.append(f"min_age_seconds={min_age_seconds}")
        if exclude_mids:
            if isinstance(exclude_mids, (list, set, tuple)):
                ex_str = ",".join(str(m).strip() for m in exclude_mids if str(m).strip())
            else:
                ex_str = str(exclude_mids).strip()
            if ex_str:
                params.append(f"exclude_mids={ex_str}")

        query_str = "&".join(params)
        path = f"/api/v1/task/assign?{query_str}"

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

    def assign_task(
        self,
        device_id: str,
        task_id: Optional[Union[str, int]] = None,
        ip: Optional[str] = None,
        nv_mid: Optional[str] = None,
        exclude_mids: Optional[Union[str, List[str], set]] = None
    ) -> Dict[str, Any]:
        """단일 단말기 할당 래퍼 (통합 assign으로 위임)"""
        return self.assign(device_ids=[device_id], ip=ip, task_id=task_id, nv_mid=nv_mid, exclude_mids=exclude_mids)

    def assign_batch(
        self,
        device_ids: list,
        ip: Optional[str] = None,
        min_age_seconds: int = 1200,
        exclude_mids: Optional[Union[str, List[str], set]] = None
    ) -> Dict[str, Any]:
        """다중 단말기 배치 할당 래퍼 (통합 assign으로 위임)"""
        return self.assign(device_ids=device_ids, ip=ip, min_age_seconds=min_age_seconds, exclude_mids=exclude_mids)


    def report_task(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        작업 완료/실패 보고: POST /api/v1/task/report
        - DB status ENUM 제약(SUCCESS/FAILED) 100% 준수
        - error_code (중간실패 상세 코드) 및 memo 필드에 상세 상태 보존
        """
        raw_task_id = result.get("task_id")
        try:
            task_id_val = int(raw_task_id)
        except (ValueError, TypeError):
            task_id_val = raw_task_id

        is_success = bool(result.get("success", False))
        db_status = "SUCCESS" if is_success else "FAILED"
        detail_st = result.get("status", "FAILED")
        err_code = result.get("error_code") or (None if is_success else detail_st)

        serp_rank_val = result.get("serp_rank") or (result.get("rank_info") or {}).get("serp_rank")
        shop_rank_val = result.get("shopping_rank") or (result.get("rank_info") or {}).get("shopping_rank")
        shop_page_val = result.get("shopping_page") or (result.get("rank_info") or {}).get("shopping_page")
        search_type_val = result.get("search_type") or ("m.search" if (result.get("match_type") == "SERP" or serp_rank_val) else "msearch")
        match_type_val = result.get("match_type") or ("SERP" if search_type_val == "m.search" else "SHOPPING")

        # memo 필드 구축 (성공 시 순위/랜딩, 실패 시 세부 상태 및 원인)
        if is_success:
            rank_label = f"SERP {serp_rank_val}위" if search_type_val == "m.search" else f"쇼핑 {shop_rank_val}위"
            memo_str = f"성공 ({search_type_val}, {rank_label}, 몰: {result.get('store_name') or ''})"
        else:
            err_msg = result.get("error_message") or ""
            memo_str = f"[{detail_st}] {err_msg}".strip()
        memo_str = memo_str[:200]

        payload = {
            "task_id": task_id_val,
            "success": is_success,
            "status": db_status,
            "final_status": detail_st,
            "error_code": err_code,
            "error_message": result.get("error_message"),
            "failed_phase": result.get("failed_phase"),
            "checkpoints": result.get("checkpoints"),
            "telemetry": result.get("telemetry"),
            "action_guidance": result.get("action_guidance"),
            "node_id": result.get("node_id", "node-default"),
            "ip_c_class": result.get("ip_c_class"),
            "search_type": search_type_val,
            "serp_rank": serp_rank_val,
            "shopping_rank": shop_rank_val,
            "shopping_page": shop_page_val,
            "match_type": match_type_val,
            "login_detected": bool(result.get("login_detected", False)),
            "login_handling_type": str(result.get("login_handling_type", "PURE_ORGANIC")),
            "login_intercept_count": int(result.get("login_intercept_count", 0)),
            "login_intercept_details": result.get("login_intercept_details", []),
            "device_id": result.get("device_id"),
            "store_name": result.get("store_name"),
            "duration_seconds": round(float(result.get("duration_seconds", 0.0)), 2),
            "js_target_found": bool(result.get("js_target_found", False)),
            "scroll_count": int(result.get("scroll_count", 0)),
            "click_success": bool(result.get("click_success", False)),
            "memo": memo_str
        }

        # v2 리포트 우선 호출 -> daily_slot_quotas 카운터 갱신 및 11대 체크포인트 저장
        status_code, data = self._http_request("POST", "/api/v2/task/report", payload=payload)
        if status_code != 200:
            status_code, data = self._http_request("POST", "/api/v1/task/report", payload=payload)
        if isinstance(data, dict):
            data["reported_payload"] = payload
        return data

    def allocate_v2(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        [차세대 지능형 작업 할당 v2 API] POST /api/v2/task/allocate
        - 3중 쿨다운 (IP + 스토어 + C클래스) 및 일일 쿼터 적용
        - payload: { node_id, net_mode, router_num, public_ip, ip_c_class, devices, local_quarantine_mids, min_nnb_age_sec }
        """
        status_code, data = self._http_request("POST", "/api/v2/task/allocate", payload=payload)
        if status_code == 404 or (isinstance(data, dict) and data.get("is_no_task")):
            data["is_no_task"] = True
            return data
        return data

    def report_v2(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        [차세대 원격 정밀 진단 보고 v2 API] POST /api/v2/task/report
        - 11대 체크포인트 마일스톤, failed_phase, error_code, 실측 telemetry, action_guidance 전송
        """
        status_code, data = self._http_request("POST", "/api/v2/task/report", payload=payload)
        if isinstance(data, dict):
            data["reported_payload"] = payload
        return data

    def heartbeat_v2(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        [분산 노드 헬스체크 v2 API] POST /api/v2/node/heartbeat
        - payload: { node_id, hostname, net_mode, current_public_ip, active_devices, ... }
        """
        status_code, data = self._http_request("POST", "/api/v2/node/heartbeat", payload=payload)
        return data

    def get_diagnostics_v2(self, limit: int = 50) -> Dict[str, Any]:
        """
        [원격 정밀 진단 요약 조회 v2 API] GET /api/v2/task/diagnostics?limit=50
        """
        status_code, data = self._http_request("GET", f"/api/v2/task/diagnostics?limit={limit}")
        return data

    def report_lte_log(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """LTE 모뎀 토글 및 세션 트래픽(Upload/Download) 중앙 서버 기록: POST /api/v1/network/lte-log"""
        status_code, resp_data = self._http_request("POST", "/api/v1/network/lte-log", payload=data)
        return resp_data

