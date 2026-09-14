#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
[모듈명] 중앙 서버 통신 및 작업 할당/반환 API 클라이언트 (TaskApiClient)
========================================================================================
- 기능:
    1. 중앙 관제 서버(https://aaa4.kr 또는 http://114.207.112.173:5000)와 통신.
    2. 단말기별 작업 할당 수신 (GET /api/v1/allocate?device_ids=...)
    3. 작업 완료 및 결과 반환 보고 (POST /api/v1/release)
    4. 최신 API 규격(is_searched, is_clicked, is_exposed, exposure_rank, snapshot_path, free_storage_mb 등) 전수 준수.

- 상세 반환 규칙 (POST /api/v1/release):
    • alloc_id (String, 필수): 할당 시 발급받은 세션 ID
    • results (Array, 필수): 단말기별 실행 결과 딕셔너리 리스트
      - device_id (String, 필수): 대상 단말기 ID
      - status (String, 필수): "SUCCESS" 또는 "FAILED"
      - target_code (String, 선택): 타겟 상품 mid
      - keyword (String, 선택): 검색 키워드
      - is_searched (Bool, 필수): 검색창 입력 및 검색 실행 여부 (True/False)
      - is_clicked (Bool, 필수): 타겟 상품 실제 클릭 여부 (True/False)
      - is_exposed (Bool, 필수): 검색 결과 목록 내 타겟 노출 여부 (True/False)
      - exposure_rank (Int/null, 선택): 검색 결과 노출 순위 (1, 2, 3위... 미노출 시 None/null)
      - execution_sec (Float, 선택): 작업 소요 시간(초)
      - free_storage_mb (Int, 선택): 단말기 남은 저장용량(MB)
      - snapshot_path (String, 선택): 갱신된 프로필 스냅샷 tar.gz 경로
      - ssaid / adid / nnb (String, 선택): 세션 식별자
========================================================================================
"""

import os
import json
import time
import logging
from datetime import datetime
import requests
from typing import Dict, Any, List, Optional

logger = logging.getLogger("TaskApiClient")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [API] %(message)s",
        datefmt="%H:%M:%S"
    )

from src.config import (
    PRIMARY_SERVER_URL, BACKUP_SERVER_URL, ALLOCATE_ENDPOINT, RELEASE_ENDPOINT,
    ALLOCATE_HISTORY_DIR, RELEASE_HISTORY_DIR, LOGS_DIR,
    get_dated_dir, prune_dir_by_age, LOG_RETENTION_DAYS
)

# 기본 API 서버 URL 및 폴백 리스트
API_HOSTS = [
    PRIMARY_SERVER_URL,
    BACKUP_SERVER_URL
]


class TaskApiClient:
    """
    중앙 서버 작업 할당/반환 전용 API 클라이언트
    """

    def __init__(self, primary_url: Optional[str] = None):
        self.hosts = [primary_url] + API_HOSTS if primary_url else API_HOSTS
        self.headers = {
            "User-Agent": "NShopMacro-ZeroReboot/2.0",
            "Content-Type": "application/json"
        }
        self.last_wait_info: Optional[Dict[str, Any]] = None

    def _record_no_task(self, record: Dict[str, Any]):
        """일자별 파일 하나(no_task_records.jsonl)에 시간, code, sub_code, message 등을 JSONL 레코드 형식으로 기록"""
        try:
            alloc_dated_dir = get_dated_dir(ALLOCATE_HISTORY_DIR)
            record_file = os.path.join(alloc_dated_dir, "no_task_records.jsonl")
            with open(record_file, "a", encoding="utf-8") as rf:
                rf.write(json.dumps(record, ensure_ascii=False) + "\n")
            prune_dir_by_age(ALLOCATE_HISTORY_DIR, retention_days=LOG_RETENTION_DAYS)
        except Exception as e:
            logger.debug(f"[-] no_task_records 기록 실패: {e}")

    def allocate_tasks(self, device_ids: List[str]) -> Optional[Dict[str, Any]]:
        """
        [1단계] 단말기 작업 할당 요청 (GET /api/v1/allocate)
        
        Args:
            device_ids: 등록된 단말기 ID 리스트 (예: ["R3CR70KAZDM", "R3CR70SZ0JJ"])
            
        Returns:
            서버 응답 JSON (alloc_id, jobs 목록 포함) 또는 실패 시 None
        """
        dev_param = ",".join(device_ids)
        params = {"device_ids": dev_param}
        self.last_wait_info = None
        recorded = False

        for base_url in self.hosts:
            endpoint = f"{base_url}/api/v1/allocate"
            try:
                logger.info(f"[*] 작업 할당 요청 중 -> {endpoint} (단말기: {dev_param})")
                res = requests.get(endpoint, params=params, headers=self.headers, timeout=6.0)
                if res.status_code == 200:
                    data = res.json()
                    task_list = data.get("tasks") or data.get("jobs") or []
                    alloc_id = data.get("alloc_id")
                    
                    if not task_list:
                        logger.info(f"[*] ⏸️ 가용 작업 없음 (200 OK, tasks: [])")
                        self.last_wait_info = {
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "status_code": 200,
                            "code": "NO_TASKS",
                            "sub_code": "EMPTY_TASKS",
                            "message": "서버 응답은 200 성공이나 가용 작업이 비어있습니다 (tasks: []).",
                            "requested_devices": device_ids
                        }
                        if not recorded:
                            self._record_no_task(self.last_wait_info)
                            recorded = True
                        return data

                    logger.info(f"[✓] 작업 할당 수신 성공! (alloc_id: {alloc_id}, 작업 수: {len(task_list)})")
                    
                    # 로컬 JSON 감사 로그 저장 (일자별 서브디렉토리, 최소 30일 보존)
                    try:
                        ts = int(time.time())
                        alloc_dated_dir = get_dated_dir(ALLOCATE_HISTORY_DIR)
                        with open(f"{alloc_dated_dir}/alloc_{alloc_id}_{ts}.json", "w", encoding="utf-8") as jf:
                            json.dump(data, jf, ensure_ascii=False, indent=2)
                        prune_dir_by_age(ALLOCATE_HISTORY_DIR, retention_days=LOG_RETENTION_DAYS)
                    except Exception:
                        pass

                    return data
                elif res.status_code == 503:
                    try:
                        err_data = res.json()
                    except Exception:
                        err_data = {}

                    code = err_data.get("code") or "NO_TASKS"
                    sub_code = err_data.get("sub_code")
                    message = err_data.get("message") or res.text[:100]

                    sub_disp = f"/{sub_code}" if sub_code else ""
                    logger.info(f"[*] ⏸️ 작업 대기 (503): [{code}{sub_disp}] {message}")

                    self.last_wait_info = {
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status_code": 503,
                        "code": code,
                        "sub_code": sub_code,
                        "message": message,
                        "requested_devices": device_ids
                    }
                    if not recorded:
                        self._record_no_task(self.last_wait_info)
                        recorded = True
                else:
                    logger.warning(f"[-] 서버 응답 오류 ({res.status_code}): {res.text[:100]}")
            except Exception as e:
                logger.warning(f"[-] 할당 요청 실패 ({base_url}): {e}")

        if self.last_wait_info:
            code = self.last_wait_info.get("code", "")
            sub_code = self.last_wait_info.get("sub_code", "")
            sub_disp = f"/{sub_code}" if sub_code else ""
            logger.info(f"[*] ⏸️ 가용 작업 대기 유지 중: [{code}{sub_disp}] {self.last_wait_info.get('message')}")
        else:
            logger.error("[!] 모든 API 엔드포인트에 대한 작업 할당 요청 실패 (네트워크/서버 연결 실패).")
        return None

    def release_tasks(self, alloc_id: str, results: List[Dict[str, Any]]) -> bool:
        """
        [2단계] 작업 결과 보고 및 세션 반환 (POST /api/v1/release)
        
        Args:
            alloc_id: 할당 시 발급받았던 세션 ID (예: "2207")
            results: 단말기별 작업 결과 딕셔너리 리스트
            
        Returns:
            반환 성공 여부 (True/False)
        """
        # 필수 및 선택 필드 규격 정제
        formatted_results = []
        for r in results:
            raw_status = str(r.get("status", "FAILED")).upper()
            if raw_status in ["SUCCESS", "OK", "TRUE"]:
                status_str = "SUCCESS"
            elif raw_status in ["CANCELLED", "CANCELED"]:
                status_str = "CANCELLED"
            else:
                status_str = "FAILED"

            exec_sec = float(round(r.get("execution_sec", 0.0), 1)) if r.get("execution_sec") is not None else None

            item = {
                "device_id": str(r.get("device_id", "")),
                "status": status_str,
                "target_code": str(r.get("target_code", "")) if r.get("target_code") else None,
                "keyword": str(r.get("keyword", "")) if r.get("keyword") else None,
                
                # 핵심 플래그 (필수 bool)
                "is_searched": bool(r.get("is_searched", False)),
                "is_clicked": bool(r.get("is_clicked", False)),
                "is_exposed": bool(r.get("is_exposed", False)),
                
                # 순위 및 성능 (총 소요시간)
                "exposure_rank": int(r["exposure_rank"]) if r.get("exposure_rank") is not None else None,
                "execution_sec": exec_sec,
                "cycle_duration_sec": exec_sec,
                "free_storage_mb": int(r.get("free_storage_mb", 0)) if r.get("free_storage_mb") else None,
                
                # GPS Mock 좌표
                "gps_lat": r.get("gps_lat"),
                "gps_lng": r.get("gps_lng"),
                "latitude": r.get("gps_lat"),
                "longitude": r.get("gps_lng"),

                # 오류 사유
                "error_reason": r.get("error_reason"),

                # 프로필 및 식별자 (NNB, NAPP_DI, snapshot_size 포함)
                "snapshot_size": float(round(r["snapshot_size"], 1)) if r.get("snapshot_size") is not None else None,
                "ssaid": r.get("ssaid"),
                "adid": r.get("adid"),
                "nnb": r.get("nnb"),
                "napp_di": r.get("napp_di"),

                # 앱 설치 타임스탬프 및 버전 메타데이터 (v3.1 Standard)
                "install_ts": int(r["install_ts"]) if r.get("install_ts") is not None else None,
                "update_ts": int(r["update_ts"]) if r.get("update_ts") is not None else None,
                "installer_pkg": str(r.get("installer_pkg", "com.android.vending")),
                "app_version": str(r.get("app_version", "12.23.1")),
                "app_version_code": int(r.get("app_version_code", 12230102)),

                # 최종 배터리 잔량 (소수점 2자리 정밀도 Float, 서버 단순 기록용)
                "battery_level": round(float(r["battery_level"]), 2) if r.get("battery_level") is not None else None
            }
            # None 값 정리
            clean_item = {k: v for k, v in item.items() if v is not None}
            formatted_results.append(clean_item)

        payload = {
            "alloc_id": str(alloc_id),
            "results": formatted_results
        }

        # 로컬 JSON 반환 감사 로그 저장 (일자별 서브디렉토리, 최소 30일 보존) 및 일일 task JSONL 누적
        try:
            ts = int(time.time())
            release_dated_dir = get_dated_dir(RELEASE_HISTORY_DIR)
            with open(f"{release_dated_dir}/release_{alloc_id}_{ts}.json", "w", encoding="utf-8") as jf:
                json.dump(payload, jf, ensure_ascii=False, indent=2)
            prune_dir_by_age(RELEASE_HISTORY_DIR, retention_days=LOG_RETENTION_DAYS)

            # 일일 클라이언트 상세 JSONL 로그 추가
            import datetime
            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            daily_events_file = os.path.join(LOGS_DIR, f"task_events_{today_str}.jsonl")
            with open(daily_events_file, "a", encoding="utf-8") as elf:
                for res_item in formatted_results:
                    log_entry = {
                        "alloc_id": str(alloc_id),
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        **res_item
                    }
                    elf.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

        for base_url in self.hosts:
            endpoint = f"{base_url}/api/v1/release"
            try:
                logger.info(f"[*] 작업 결과 반환 전송 중 -> {endpoint} (alloc_id: {alloc_id})")
                res = requests.post(endpoint, json=payload, headers=self.headers, timeout=6.0)
                if res.status_code == 200:
                    logger.info(f"[✓] 작업 결과 반환 성공! 서버 응답: {res.text[:100]}")
                    return True
                else:
                    logger.warning(f"[-] 반환 응답 오류 ({res.status_code}): {res.text[:100]}")
            except Exception as e:
                logger.warning(f"[-] 반환 요청 실패 ({base_url}): {e}")

        logger.error(f"[!] alloc_id '{alloc_id}' 작업 반환 최종 실패.")
        return False
