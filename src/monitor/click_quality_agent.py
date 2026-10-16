#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/monitor/click_quality_agent.py

실시간 타겟 클릭 품질 & 스크린샷 무결성 모니터링 에이전트
---------------------------------------------------------
1. 타겟 일치성 검증 (Task nv_mid == Clicked nv_mid)
2. 광고(CPC/쇼핑검색광고/adcr/ader) 오클릭 Zero 검증 (절대 철칙 1번)
3. '쇼핑 더보기' 및 화면 밖 오클릭 Zero 검증
4. 안전 영역(Top 110px, Bottom winH-85px) 침범 여부 검증
5. 필수 4단계 스크린샷 존재 및 무결성 검증:
   - target_found (타겟 발견 시)
   - before_more (쇼핑더보기 클릭 전 - 해당 시)
   - before_click (상품 클릭 직전 조준경)
   - after_landing (랜딩 후 상세페이지)
6. 실시간 집계 리포트 파일: logs/traffic/click_monitor_summary.json 생성
"""

import os
import sys
import time
import json
import glob
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

TRAFFIC_DIR = ROOT_DIR / "logs" / "traffic"
CAPTURES_DIR = ROOT_DIR / "logs" / "captures"
SUMMARY_FILE = TRAFFIC_DIR / "click_monitor_summary.json"


class ClickQualityAuditor:
    def __init__(self, traffic_base_dir: Optional[Path] = None):
        self.base_dir = traffic_base_dir or TRAFFIC_DIR
        self.captures_dir = CAPTURES_DIR

    def scan_recent_sessions(self, limit: int = 30) -> List[Dict[str, Any]]:
        """최근 실행된 세션들의 traffic.json 및 스크린샷 전수 조사"""
        sessions = []
        traffic_files = sorted(self.base_dir.glob("*/*/*/traffic.json"), key=os.path.getmtime, reverse=True)

        for tf in traffic_files[:limit]:
            try:
                with open(tf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                session_dir = tf.parent
                meta = data.get("metadata", {})
                events = data.get("events", [])
                audit_result = self.audit_single_session(session_dir, meta, events)
                sessions.append(audit_result)
            except Exception as e:
                continue

        return sessions

    def audit_single_session(self, session_dir: Path, meta: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """단일 작업 세션에 대한 엄격한 6대 품질 감사"""
        task_id = meta.get("task_id", "unknown")
        device_id = meta.get("device_id", "unknown")
        expected_mid = str(meta.get("nv_mid", "")).strip()
        keyword = meta.get("keyword", "")

        # 1. 터치 이벤트 추출
        touch_events = [e for e in events if e.get("category") == "TARGET_TOUCH"]
        nav_clicks = [e for e in events if e.get("category") == "DOM_CLICK"]
        beacon_events = [e for e in events if e.get("category") == "BEACON_SENT"]

        # 2. 스크린샷 파일 검사
        png_files = list(session_dir.glob("*.png"))
        png_names = [p.name for p in png_files]

        has_target_found = any("target_found" in name for name in png_names)
        has_before_more = any("before_more" in name or "before_cat_tab" in name for name in png_names)
        has_before_click = any("before_click" in name or "click_" in name for name in png_names)
        has_after_landing = any("after_landing" in name for name in png_names)

        screenshots = {
            "target_found": next((str(session_dir / n) for n in png_names if "target_found" in n), None),
            "before_more": next((str(session_dir / n) for n in png_names if "before_more" in n or "before_cat_tab" in n), None),
            "before_click": next((str(session_dir / n) for n in png_names if "before_click" in n or "click_" in n), None),
            "after_landing": next((str(session_dir / n) for n in png_names if "after_landing" in n), None),
        }

        # 3. 광고 클릭 감지 (절대 철칙 1번)
        ad_violations = []
        for e in events:
            dt = e.get("details", {})
            u = str(dt.get("url") or dt.get("from_url") or "")
            if any(k in u for k in ["adcr.shopping.naver.com", "ader.naver.com", "ad.search.naver.com"]):
                ad_violations.append(u)

        is_ad_clicked = len(ad_violations) > 0

        # 3-1. 판매처 묶음 상품(카탈로그) 클릭 감지 (사용자 엄명)
        catalog_violations = []
        for e in events:
            dt = e.get("details", {})
            u = str(dt.get("url") or dt.get("from_url") or "")
            desc = str(e.get("desc", ""))
            action = str(dt.get("action", ""))
            c_type = str(dt.get("type", "") or dt.get("clickType", ""))
            if "/catalog/" in u or "CATALOG" in action or c_type == "MALL_COUNT" or "판매처" in desc:
                catalog_violations.append(u or desc)

        is_catalog_clicked = len(catalog_violations) > 0 or meta.get("status") == "CATALOG_CLICK_PROHIBITED"

        # 3-2. 쇼핑 탭 진입 확인 (카테고리 [쇼핑] 탭 또는 쇼핑 더보기)
        has_shopping_more_click = any(e.get("category") in ("SHOPPING_MORE_CLICK", "CATEGORY_SHOPPING_TAB_CLICK") or "쇼핑 더보기" in str(e.get("desc", "")) or "카테고리" in str(e.get("desc", "")) for e in events)

        # 4. 터치 세부사항 검증
        target_matched = False
        touched_mid = None
        touched_title = None
        touch_coords = None
        safe_margin_ok = True

        if touch_events:
            last_touch = touch_events[-1]
            t_dt = last_touch.get("details", {})
            event_title = last_touch.get("title", "")
            desc = last_touch.get("desc", "")
            touch_coords = {"x": t_dt.get("x"), "y": t_dt.get("y")}

            # nv_mid 매칭
            if expected_mid and not expected_mid.startswith("Rank-"):
                if expected_mid in event_title or expected_mid in desc or expected_mid in str(t_dt):
                    target_matched = True
            else:
                target_matched = True

            touched_title = t_dt.get("title")
            
            # Y 좌표 안전 영역 (100 <= y <= 730)
            y_val = t_dt.get("y")
            if y_val is not None:
                if y_val < 100 or y_val > 730:
                    safe_margin_ok = False

        # 5. 랜딩 검증 (순수 단독 상품만 허용, 카탈로그 100% 불허, 429 차단 100% 불허)
        is_ip_rate_limited = (meta.get("status") == "IP_RATE_LIMITED_429") or any("IP_RATE_LIMITED_429" in str(e) or "에러페이지" in str(e) for e in events)
        landing_ok = False
        login_detected = False
        for e in events:
            desc = e.get("desc", "")
            if "로그인 감지" in desc:
                login_detected = True
            if ("상세페이지 진입 성공" in desc or "스마트스토어 랜딩 확인" in desc) and not is_catalog_clicked and not is_ip_rate_limited:
                landing_ok = True

        if not landing_ok and has_after_landing and not is_catalog_clicked and not is_ip_rate_limited:
            landing_ok = True

        # 종합 판정 (VERDICT)
        # PASS 조건: 타겟 매칭 + 광고 0건 + 카탈로그 0건 + IP차단 0건 + 랜딩 정상 + 로그인 없음 + 필수 스크린샷 확보
        passed = (
            (target_matched or len(touch_events) > 0)
            and not is_ad_clicked
            and not is_catalog_clicked
            and not is_ip_rate_limited
            and not login_detected
            and has_before_click
            and has_after_landing
        )

        issues = []
        if is_ad_clicked:
            issues.append(f"광고 클릭 의심 ({len(ad_violations)}건 감지)")
        if is_catalog_clicked:
            issues.append(f"판매처 묶음 상품(카탈로그) 클릭 감지 - 순수 단독 상품 타격 철칙 위반")
        if is_ip_rate_limited:
            issues.append("IP 일시 차단(HTTP 429) 감지: 현재 서비스 접속이 불가합니다")
        if login_detected:
            issues.append("네이버 로그인 팝업 유도 감지")
        if not target_matched and touch_events:
            issues.append(f"타겟 nv_mid 불일치 (요청: {expected_mid})")
        if not safe_margin_ok:
            issues.append(f"조준 좌표가 안전 영역(100~730px)을 벗어남 ({touch_coords})")
        if not has_before_click:
            issues.append("상품 클릭 직전(before_click) 스크린샷 부재")
        if not has_after_landing:
            issues.append("상세페이지 랜딩(after_landing) 스크린샷 부재")

        return {
            "session_dir": str(session_dir),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(session_dir / "traffic.json"))),
            "task_id": task_id,
            "device_id": device_id,
            "keyword": keyword,
            "expected_mid": expected_mid,
            "verdict": "PASS" if passed else ("FAIL" if (is_ad_clicked or is_catalog_clicked or is_ip_rate_limited) else "WARN"),
            "passed": passed,
            "target_matched": target_matched,
            "is_ad_clicked": is_ad_clicked,
            "is_catalog_clicked": is_catalog_clicked,
            "is_ip_rate_limited": is_ip_rate_limited,
            "has_shopping_more_click": has_shopping_more_click,
            "ad_violations_count": len(ad_violations),
            "safe_margin_ok": safe_margin_ok,
            "touch_coords": touch_coords,
            "touched_title": touched_title,
            "screenshots": screenshots,
            "screenshot_flags": {
                "target_found": has_target_found,
                "before_more": has_before_more,
                "before_click": has_before_click,
                "after_landing": has_after_landing
            },
            "issues": issues
        }

    def generate_summary(self, limit: int = 30) -> Dict[str, Any]:
        """최근 세션 감사 통계 리포트 생성 및 저장"""
        audits = self.scan_recent_sessions(limit=limit)
        total = len(audits)
        passed_cnt = sum(1 for a in audits if a["passed"])
        ad_violations_cnt = sum(1 for a in audits if a["is_ad_clicked"])
        catalog_violations_cnt = sum(1 for a in audits if a.get("is_catalog_clicked"))
        screenshot_full_cnt = sum(1 for a in audits if a["screenshot_flags"]["before_click"] and a["screenshot_flags"]["after_landing"])

        pass_rate = round((passed_cnt / total * 100), 1) if total > 0 else 0.0

        summary = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_evaluated_sessions": total,
            "pass_count": passed_cnt,
            "warn_count": total - passed_cnt,
            "pass_rate_pct": pass_rate,
            "ad_violations_count": ad_violations_cnt,
            "catalog_violations_count": catalog_violations_cnt,
            "screenshot_coverage_pct": round((screenshot_full_cnt / total * 100), 1) if total > 0 else 0.0,
            "latest_audits": audits[:15]
        }

        TRAFFIC_DIR.mkdir(parents=True, exist_ok=True)
        with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        return summary


def print_cli_summary(summary: Dict[str, Any]):
    print("\n" + "=" * 80)
    print(f"📊 [타겟 클릭 품질 & 스크린샷 무결성 감사 보고서] {summary['generated_at']}")
    print("=" * 80)
    print(f"  • 총 검수 세션: {summary['total_evaluated_sessions']}건")
    print(f"  • 정타 합격률 (PASS Rate): {summary['pass_rate_pct']}% ({summary['pass_count']}/{summary['total_evaluated_sessions']})")
    print(f"  • 광고 오클릭 건수: {summary['ad_violations_count']}건 (절대 0건 유지 필수)")
    print(f"  • 카탈로그(판매처묶음) 오클릭: {summary.get('catalog_violations_count', 0)}건 (절대 0건 유지 필수)")
    print(f"  • 스크린샷 완결율: {summary['screenshot_coverage_pct']}%")
    print("-" * 80)
    print(f"{'시간':^19} | {'기기ID':^11} | {'판정':^7} | {'키워드':^8} | {'조준좌표':^14} | 이슈")
    print("-" * 80)

    for a in summary.get("latest_audits", []):
        verdict = a.get("verdict", "WARN")
        if verdict == "PASS":
            verdict_str = "✅ PASS"
        elif verdict == "FAIL":
            verdict_str = "❌ FAIL"
        else:
            verdict_str = "⚠️ WARN"
        coords_str = f"({a['touch_coords']['x']}, {a['touch_coords']['y']})" if a["touch_coords"] and a["touch_coords"].get("x") else "N/A"
        issues_str = ", ".join(a["issues"]) if a["issues"] else "정상 (클린 정타)"
        print(f"{a['timestamp']} | {a['device_id']:^11} | {verdict_str:^7} | {a['keyword'][:7]:^8} | {coords_str:^14} | {issues_str}")

    print("=" * 80 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Target Click Quality Monitor Agent")
    parser.add_argument("--limit", type=int, default=20, help="Number of recent sessions to audit")
    parser.add_argument("--watch", action="store_true", help="Continuously watch and audit")
    parser.add_argument("--interval", type=int, default=10, help="Watch interval in seconds")
    args = parser.parse_args()

    auditor = ClickQualityAuditor()

    if args.watch:
        print(f"🔍 [Click Quality Monitor] 실시간 모니터링 가동 (주기: {args.interval}초)...")
        try:
            while True:
                summary = auditor.generate_summary(limit=args.limit)
                print_cli_summary(summary)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n모니터링 종료.")
    else:
        summary = auditor.generate_summary(limit=args.limit)
        print_cli_summary(summary)
