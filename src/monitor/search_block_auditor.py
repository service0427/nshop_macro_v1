#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/monitor/search_block_auditor.py

[네이버 FDS 검색/쇼핑 접속 차단 정밀 감사 및 통계 추적기]
- "쇼핑 서비스 접속이 일시적으로 제한되었습니다", FDS 로그인 챌린지, 캡차 등
  검색/쇼핑 진입 차단 현상을 독립된 구조화 로그(logs/search_blocks.jsonl)에 전수 기록
- 동일 공인 IP 재사용 시간 간격(IP Reuse Gap) 및 타임 윈도우 내 접근 빈도 추적
- 향후 차단 원인 정밀 규명을 위한 분석 통계 제공
"""

import os
import sys
import time
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List, Union
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
BLOCK_LOG_FILE = LOGS_DIR / "search_blocks.jsonl"
IP_HISTORY_FILE = LOGS_DIR / "ip_access_history.json"

logger = logging.getLogger("SearchBlockAuditor")


def record_ip_access(public_ip: str, device_id: str, keyword: str, action: str = "SEARCH"):
    """공인 IP별 접근 이력 및 타임스탬프 기록 (동일 IP 접근 간격 추적용)"""
    if not public_ip or public_ip in ("0.0.0.0", "unknown", "127.0.0.1"):
        return

    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        now = time.time()
        history: Dict[str, List[Dict[str, Any]]] = {}

        if IP_HISTORY_FILE.exists():
            try:
                with open(IP_HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = {}

        # 24시간 이전 오래된 기록 정제
        cutoff = now - 86400
        cleaned_history = {}
        for ip, records in history.items():
            valid_recs = [r for r in records if r.get("time", 0) > cutoff]
            if valid_recs:
                cleaned_history[ip] = valid_recs

        if public_ip not in cleaned_history:
            cleaned_history[public_ip] = []

        cleaned_history[public_ip].append({
            "time": now,
            "device_id": device_id,
            "keyword": keyword,
            "action": action
        })

        with open(IP_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(cleaned_history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug(f"IP access history write failed: {e}")


def get_ip_usage_stats(public_ip: str) -> Dict[str, Any]:
    """해당 공인 IP의 최근 접근 빈도 및 직전 접근과의 시간차(초) 계산"""
    if not public_ip or not IP_HISTORY_FILE.exists():
        return {"use_count_1h": 0, "use_count_24h": 0, "gap_from_prev_sec": None}

    try:
        with open(IP_HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)

        records = history.get(public_ip, [])
        if not records:
            return {"use_count_1h": 0, "use_count_24h": 0, "gap_from_prev_sec": None}

        now = time.time()
        one_hour_ago = now - 3600
        cnt_1h = sum(1 for r in records if r.get("time", 0) >= one_hour_ago)
        cnt_24h = len(records)

        # 직전 사용과의 시간 갭 (최근 2개 이상일 때)
        sorted_times = sorted([r.get("time", 0) for r in records], reverse=True)
        gap_sec = None
        if len(sorted_times) >= 2:
            gap_sec = round(sorted_times[0] - sorted_times[1], 1)

        return {
            "use_count_1h": cnt_1h,
            "use_count_24h": cnt_24h,
            "gap_from_prev_sec": gap_sec,
            "first_seen_ago_sec": round(now - sorted_times[-1], 1) if sorted_times else None
        }
    except Exception:
        return {"use_count_1h": 0, "use_count_24h": 0, "gap_from_prev_sec": None}


def record_search_block(
    stage: str,
    block_type: str,
    block_message: str,
    device_id: str,
    task_id: Union[int, str] = 0,
    keyword: str = "",
    nv_mid: str = "",
    store_name: str = "",
    public_ip: str = "",
    url: str = "",
    screenshot_path: Optional[str] = None,
    extra_details: Optional[Dict[str, Any]] = None
):
    """
    네이버 FDS 검색/쇼핑 차단 발생 시 전용 감사 로그에 영구 기록
    - stage: 'SERP', 'SHOP_NAV_MORE', 'SHOP_TAB', 'CATALOG', 'LANDING'
    - block_type: 'SHOPPING_ACCESS_BLOCKED', 'LOGIN_CHALLENGE_DETECTED', 'CAPTCHA_BLOCKED', 'SERVER_ERROR'
    """
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        now_ts = time.time()
        now_dt = datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M:%S")

        ip_stats = get_ip_usage_stats(public_ip) if public_ip else {}

        record = {
            "timestamp": now_dt,
            "time_epoch": round(now_ts, 3),
            "stage": stage,
            "block_type": block_type,
            "block_message": block_message,
            "device_id": device_id,
            "task_id": task_id,
            "keyword": keyword,
            "nv_mid": nv_mid,
            "store_name": store_name,
            "public_ip": public_ip,
            "ip_stats": ip_stats,
            "url": (url or "")[:200],
            "screenshot_path": screenshot_path,
            "extra_details": extra_details or {}
        }

        with open(BLOCK_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        gap_info = f" (직전 IP사용 갭: {ip_stats.get('gap_from_prev_sec')}s, 1시간내 {ip_stats.get('use_count_1h')}회)" if ip_stats.get('gap_from_prev_sec') is not None else ""
        logger.warning(
            f"🚫 [차단 감사 기록 완료] 단계={stage} | 유형={block_type} | 단말={device_id} | IP={public_ip}{gap_info} | 사유='{block_message[:60]}'"
        )
    except Exception as e:
        logger.error(f"Failed to record search block audit: {e}")


def get_block_statistics(window_minutes: int = 60) -> Dict[str, Any]:
    """지정된 시간 윈도우 내의 차단 빈도 및 통계 집계"""
    if not BLOCK_LOG_FILE.exists():
        return {
            "total_blocks": 0,
            "by_type": {},
            "by_stage": {},
            "by_ip": {},
            "by_keyword": {},
            "recent_records": []
        }

    now = time.time()
    cutoff = now - (window_minutes * 60)

    total = 0
    by_type = defaultdict(int)
    by_stage = defaultdict(int)
    by_ip = defaultdict(int)
    by_keyword = defaultdict(int)
    recent = []

    try:
        with open(BLOCK_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    t = data.get("time_epoch", 0)
                    if t >= cutoff:
                        total += 1
                        by_type[data.get("block_type", "UNKNOWN")] += 1
                        by_stage[data.get("stage", "UNKNOWN")] += 1
                        ip = data.get("public_ip") or "UNKNOWN_IP"
                        by_ip[ip] += 1
                        kw = data.get("keyword") or "UNKNOWN_KW"
                        by_keyword[kw] += 1
                        recent.append(data)
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"Error reading block log file: {e}")

    return {
        "window_minutes": window_minutes,
        "total_blocks": total,
        "by_type": dict(by_type),
        "by_stage": dict(by_stage),
        "by_ip": dict(sorted(by_ip.items(), key=lambda x: x[1], reverse=True)[:10]),
        "by_keyword": dict(sorted(by_keyword.items(), key=lambda x: x[1], reverse=True)[:10]),
        "recent_records": recent[-10:]
    }


def print_summary_report(window_minutes: int = 60):
    """차단 통계 요약 콘솔 리포트 출력"""
    stats = get_block_statistics(window_minutes)
    print("=" * 80)
    print(f"📊 [네이버 FDS 검색/쇼핑 접속 차단 통계 리포트] 최근 {window_minutes}분 기준")
    print(f"총 차단 건수: {stats['total_blocks']}건")
    print("-" * 80)
    print("📌 [차단 유형별 분포]")
    for b_type, cnt in stats["by_type"].items():
        print(f"  • {b_type:<30}: {cnt}건 ({cnt/max(1, stats['total_blocks'])*100:.1f}%)")

    print("\n📌 [발생 단계별 분포]")
    for stage, cnt in stats["by_stage"].items():
        print(f"  • {stage:<25}: {cnt}건")

    print("\n📌 [상위 빈출 공인 IP]")
    for ip, cnt in stats["by_ip"].items():
        print(f"  • {ip:<20}: {cnt}건")

    print("\n📌 [상위 빈출 키워드]")
    for kw, cnt in stats["by_keyword"].items():
        print(f"  • {kw:<25}: {cnt}건")
    print("=" * 80)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Search Block Auditor")
    parser.add_argument("--window", type=int, default=60, help="Window minutes to analyze (default: 60)")
    args = parser.parse_args()
    print_summary_report(args.window)
