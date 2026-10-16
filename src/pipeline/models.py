#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/pipeline/models.py

Pipeline data structures, result tracking, and common utility constants.
"""

import os
import sys
import json
import time
import re
from pathlib import Path
from typing import Dict, Any, Optional, Union, List

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from config.settings import LOGS_DIR, CAPTURES_DIR, HISTORY_FILE

DEVICE_CDP_PORTS = {
    "R3CR70FFFEK": 9901,
    "R3CR70K98XZ": 9902,
    "R3CR70KB1RA": 9903,
    "R3CR70P0Y5E": 9904,
    "R3CR80BLS9K": 9905,
    "R3CR80HKLKL": 9906,
    "R3CR90CCP1D": 9907,
    "R3CRB0WCGET": 9908,
    "R3CRC0B4X2F": 9909,
    "R3CRC0XEZ5E": 9910,
    "R3CRC0XFL0R": 9911,
    "R3CRC0ZCD2Z": 9912,
    "R5CR80AML3N": 9913,
    "R5CR80ZYL9K": 9914,
    "R5CR81SA7RK": 9915,
    "R5CR82FNMVX": 9916,
    "R5CR82H78WT": 9917,
    "R5CR91SH8LM": 9918,
    "R5CRA28JXXF": 9919,
    "R5CRC2RDAFB": 9920,
}

_DYNAMIC_DEVICE_PORTS: Dict[str, int] = {}

def get_cdp_port(device_id: str) -> int:
    if device_id in DEVICE_CDP_PORTS:
        return DEVICE_CDP_PORTS[device_id]
    if device_id not in _DYNAMIC_DEVICE_PORTS:
        used = set(DEVICE_CDP_PORTS.values()).union(set(_DYNAMIC_DEVICE_PORTS.values()))
        port = 9921
        while port in used:
            port += 1
        _DYNAMIC_DEVICE_PORTS[device_id] = port
    return _DYNAMIC_DEVICE_PORTS[device_id]


def clean_keyword(keyword: str) -> str:
    if not keyword:
        return ""
    text = re.sub(r"\[.*?\]|\(.*?\)|<.*?>", " ", str(keyword))
    text = re.sub(r"[^\w\s가-힣a-zA-Z0-9]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


STOP_PREFIXES = {"국산", "국내산", "정품", "신상", "무료배송", "당일발송", "당일출고", "특가", "할인", "추천", "인기", "최신형", "100%", "총알배송"}

def shorten_keyword(keyword: str, max_words: int = 5) -> str:
    cleaned = clean_keyword(keyword)
    if not cleaned:
        return ""
    tokens = cleaned.split()
    tokens = [t for t in tokens if t not in STOP_PREFIXES]
    if not tokens:
        tokens = cleaned.split()
    return " ".join(tokens[:max_words])


class TaskInput:
    def __init__(
        self,
        task_id: Union[str, int],
        keyword: str,
        nv_mid: Optional[str] = None,
        target_rank: Optional[int] = None,
        compare_id: Optional[str] = None,
        store_name: Optional[str] = None,
        nnb: Optional[str] = None,
        buc: Optional[str] = None,
        use_remote_nnb: bool = True,
        device_id: Optional[str] = None,
        dwell_seconds: int = 15,
        profile: Optional[Dict[str, Any]] = None,
        ip: Optional[str] = None,
        scroll_mode: str = "real_swipe",
        cycle_ymd: Optional[str] = None,
        cycle_his: Optional[str] = None,
        session_dir: Optional[Union[str, Path]] = None,
        target_cycle_dur: float = 60.0,
        task_start_time: Optional[float] = None,
        node_id: str = "node-default",
        ip_c_class: Optional[str] = None,
        catalog_id: Optional[str] = None,
        expected_rank: Optional[int] = None,
        keyword_candidates: Optional[List[Dict[str, Any]]] = None,
        target_id: Optional[str] = None,
        filter_selector: Optional[str] = None
    ):
        self.task_id = str(task_id).strip()
        self.raw_keyword = keyword
        self.keyword = shorten_keyword(keyword, max_words=5)
        self.nv_mid = str(nv_mid).strip() if nv_mid else ""
        self.target_rank = int(target_rank) if target_rank is not None else None
        self.target_id = str(target_id).strip() if target_id else None
        self.compare_id = str(compare_id).strip() if compare_id else self.target_id
        if not self.target_id and self.compare_id:
            self.target_id = self.compare_id
        self.filter_selector = filter_selector.strip() if filter_selector else None
        self.store_name = store_name.strip() if store_name else None
        self.nnb = nnb.strip() if nnb else None
        self.buc = buc.strip() if buc else None
        self.use_remote_nnb = use_remote_nnb
        self.device_id = device_id
        self.dwell_seconds = dwell_seconds
        self.profile = profile
        self.ip = ip
        self.scroll_mode = scroll_mode
        self.cycle_ymd = cycle_ymd
        self.cycle_his = cycle_his
        self.session_dir = session_dir
        self.target_cycle_dur = float(target_cycle_dur)
        self.task_start_time = task_start_time
        self.node_id = node_id
        self.ip_c_class = ip_c_class
        self.catalog_id = catalog_id
        self.expected_rank = expected_rank
        self.keyword_candidates = keyword_candidates or []


class TaskResult:
    def __init__(
        self,
        task_id: str,
        keyword: str,
        nv_mid: Optional[str] = None,
        compare_id: Optional[str] = None,
        raw_keyword: Optional[str] = None,
        node_id: str = "node-default",
        ip_c_class: Optional[str] = None
    ):
        self.task_id = task_id
        self.raw_keyword = raw_keyword or keyword
        self.keyword = keyword
        self.nv_mid = nv_mid or ""
        self.compare_id = compare_id
        self.node_id = node_id
        self.ip_c_class = ip_c_class
        self.store_name: Optional[str] = None
        self.device_id: str = ""
        self.nnb: Optional[str] = None
        self.ip: str = "unknown"
        self.status: str = "INITIALIZED"
        self.success: bool = False
        self.error_message: Optional[str] = None
        self.serp_rank: Optional[int] = None
        self.shopping_rank: Optional[int] = None
        self.shopping_page: Optional[int] = None
        self.match_type: Optional[str] = None
        self.search_type: Optional[str] = None
        self.click_source: Optional[str] = None
        self.click_action: Optional[str] = None
        self.target_type: Optional[str] = None
        self.pre_click_url: Optional[str] = None
        self.target_product_url: Optional[str] = None
        self.touch_coordinates: Optional[Dict[str, float]] = None
        self.landing_url: Optional[str] = None
        self.landing_title: Optional[str] = None
        self.landing_dom_dump: Optional[Dict[str, Any]] = None
        self.target_found_screenshot: Optional[str] = None
        self.before_click_screenshot: Optional[str] = None
        self.after_click_screenshot: Optional[str] = None
        self.audit_log_path: Optional[str] = None
        self.session_dir: Optional[str] = None
        self.login_detected: bool = False
        self.login_handling_type: str = "PURE_ORGANIC"  # "PURE_ORGANIC" | "FORCED_BYPASS" | "LOGIN_CHALLENGE_DETECTED"
        self.login_intercept_count: int = 0
        self.login_intercept_details: List[str] = []
        self.duration_seconds: float = 0.0
        self.dwell_duration_seconds: float = 0.0
        self.timestamp: str = time.strftime("%Y-%m-%d %H:%M:%S")
        self.timing_profile: Dict[str, float] = {}
        self.action_history: List[Dict[str, Any]] = []
        self.jitter_history: List[Dict[str, Any]] = []
        self.dwell_history: List[Dict[str, Any]] = []
        self.js_target_found: bool = False
        self.js_target_rank: Optional[int] = None
        self.js_total_count: Optional[int] = None
        self.js_search_type: Optional[str] = None
        self.scroll_count: int = 0
        self.click_success: bool = False
        self.click_fail_reason: Optional[str] = None
        self.hop_count: int = 1
        self.total_hops: int = 1
        self.chain_hops: List[Dict[str, Any]] = []
        self.failed_phase: Optional[str] = None
        self.error_code: Optional[str] = None
        self.checkpoints: Dict[str, bool] = {
            "p1_clean_launch": False,
            "p1_hooks_verified": False,
            "p1_net_connected": False,
            "p2_serp_loaded": False,
            "p2_organic_section_found": False,
            "p2_serp_hit": False,
            "p3_more_btn_found": False,
            "p3_more_btn_clicked": False,
            "p3_shop_transitioned": False,
            "p4_next_data_verified": False,
            "p4_dom_rendered": False,
            "p4_target_clicked": False,
            "p5_landing_reached": False,
            "p5_dwell_flushed": False
        }
        self.action_guidance: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "raw_keyword": self.raw_keyword,
            "keyword": self.keyword,
            "nv_mid": self.nv_mid,
            "compare_id": self.compare_id,
            "store_name": self.store_name,
            "device_id": self.device_id,
            "nnb": self.nnb,
            "ip": self.ip,
            "node_id": self.node_id,
            "ip_c_class": self.ip_c_class,
            "status": self.status,
            "success": self.success,
            "failed_phase": self.failed_phase,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "checkpoints": self.checkpoints,
            "search_type": self.search_type,
            "click_source": self.click_source,
            "click_action": self.click_action,
            "serp_rank": self.serp_rank,
            "shopping_rank": self.shopping_rank,
            "shopping_page": self.shopping_page,
            "match_type": self.match_type,
            "target_type": self.target_type,
            "touch_coordinates": self.touch_coordinates,
            "landing_url": self.landing_url,
            "landing_title": self.landing_title,
            "target_found_screenshot": self.target_found_screenshot,
            "before_click_screenshot": self.before_click_screenshot,
            "after_click_screenshot": self.after_click_screenshot,
            "audit_log_path": self.audit_log_path,
            "duration_seconds": self.duration_seconds,
            "dwell_duration_seconds": self.dwell_duration_seconds,
            "timestamp": self.timestamp,
            "timing_profile": self.timing_profile,
            "action_history": self.action_history,
            "jitter_history": self.jitter_history,
            "dwell_history": self.dwell_history,
            "js_target_found": self.js_target_found,
            "js_target_rank": self.js_target_rank,
            "js_total_count": self.js_total_count,
            "js_search_type": self.js_search_type,
            "scroll_count": self.scroll_count,
            "click_success": self.click_success,
            "click_fail_reason": self.click_fail_reason,
            "hop_count": self.hop_count,
            "total_hops": self.total_hops,
            "chain_hops": self.chain_hops,
            "login_detected": self.login_detected,
            "login_handling_type": self.login_handling_type,
            "login_intercept_count": self.login_intercept_count,
            "login_intercept_details": self.login_intercept_details,
            "action_guidance": self.action_guidance
        }

    def to_v2_report_payload(self, net_mode: str = "lte") -> Dict[str, Any]:
        c_class = self.ip_c_class
        if not c_class and self.ip and "." in self.ip:
            parts = self.ip.split(".")
            if len(parts) >= 3:
                c_class = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"

        last_jitter = self.jitter_history[-1] if self.jitter_history else {}
        is_captcha = self.status == "CAPTCHA_BLOCKED" or "CAPTCHA" in str(self.error_code or "")
        is_login = self.login_detected or self.status == "LOGIN_REQUIRED"

        guidance = dict(self.action_guidance) if self.action_guidance else {}
        if not guidance:
            if not self.success and ("NOT_FOUND" in str(self.status) or "NOT_FOUND" in str(self.error_code or "")):
                guidance["suggested_action"] = "QUARANTINE_PRODUCT_CANDIDATE"
            elif is_captcha:
                guidance["suggested_action"] = "ROTATE_IP_IMMEDIATELY"
            elif self.success:
                guidance["suggested_action"] = "REGISTER_STORE_COOLDOWN"
            else:
                guidance["suggested_action"] = "LOG_ONLY"
            guidance["requires_immediate_ip_rotation"] = is_captcha
            guidance["store_cooldown_required"] = self.success

        return {
            "task_id": self.task_id,
            "node_id": self.node_id,
            "device_id": self.device_id,
            "net_mode": net_mode,
            "public_ip": self.ip,
            "ip_c_class": c_class,
            "final_status": "SUCCESS" if self.success else "FAILED",
            "failed_phase": self.failed_phase,
            "error_code": self.error_code or (None if self.success else self.status),
            "error_message": self.error_message,
            "checkpoints": self.checkpoints,
            "telemetry": {
                "total_duration_sec": round(float(self.duration_seconds), 2),
                "dwell_duration_sec": round(float(self.dwell_duration_seconds), 2),
                "search_type": self.search_type,
                "match_type": self.match_type,
                "serp_rank": self.serp_rank,
                "shopping_rank": self.shopping_rank,
                "shopping_page": self.shopping_page,
                "scroll_count": self.scroll_count,
                "rendered_items_count": self.js_total_count,
                "touch_coordinates": self.touch_coordinates,
                "use_jitter": last_jitter.get("use_jitter"),
                "hold_ms": last_jitter.get("hold_ms"),
                "captcha_detected": is_captcha,
                "login_popup_detected": is_login,
                "login_handling_type": self.login_handling_type,
                "login_intercept_count": self.login_intercept_count,
                "login_intercept_details": self.login_intercept_details
            },
            "action_guidance": guidance
        }


def save_task_history(record: Dict[str, Any]):
    try:
        ymd = time.strftime("%Y%m%d")
        daily_log_file = LOGS_DIR / f"execution_history_{ymd}.jsonl"
        with open(daily_log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        all_history = []
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    all_history = json.load(f)
            except Exception:
                all_history = []
        all_history.append(record)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(all_history[-500:], f, ensure_ascii=False, indent=2)
    except Exception:
        pass
