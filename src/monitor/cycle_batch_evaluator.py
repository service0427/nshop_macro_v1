#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/monitor/cycle_batch_evaluator.py

10회 사이클 배치 실행 종합 평가 & 24시간 무중단 관제 평가 도구
------------------------------------------------------------------
1. 로그인 발생 여부 전수 검증 (LOGIN_REQUIRED, LOGIN_GATE 등)
   - 발생 시: 강제 닫기 금지 원칙 준수, 원인 정밀 진단 (쿠키 결손, 클릭 이탈, Intent 스킴 등)
2. 오가닉 유효타 및 성공률 통계 (절대 철칙 1 준수: 광고 배제, 순수 오가닉)
3. 상품별 순위 변동 실시간 추적 (직전 회차/어제 대비 상승, 하락, SERP 1P 신규 진입)
4. 단말기별 성공/실패 현황 및 FDS 무결성 (6대 훅, 독립 식별자 유지 여부)
"""

import os
import sys
import json
import glob
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import defaultdict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

LOGS_DIR = ROOT_DIR / "logs"
TRAFFIC_DIR = LOGS_DIR / "traffic"


def load_run_file(fpath: str) -> Dict[str, Any]:
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"Error loading {fpath}: {e}")
        return {}


def find_latest_run_file(net_mode: str = "lte") -> Optional[Path]:
    pattern = str(LOGS_DIR / net_mode / "*" / "*" / f"run_{net_mode}_*.json")
    files = glob.glob(pattern)
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return Path(files[0])


def evaluate_batch(run_data: Dict[str, Any], baseline_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """10회 사이클 배치 실행 결과 분석"""
    cycles = run_data.get("cycles", [])
    if not cycles and "results" in run_data:
        # 단일 회차 구조 호환
        cycles = [run_data]

    total_tasks = 0
    total_success = 0
    status_counts = defaultdict(int)

    # [핵심 에러 유형별 추적 버킷]
    network_errors = []        # NETWORK_ERROR, net::ERR_*, DNS timeout
    serp_tab_misses = []       # SERP_TAB_NOT_FOUND, 메인홈 고착
    identity_rollbacks = []    # IDENTITY_ROLLBACK_DETECTED, HOOK_INTEGRITY_FAILED
    login_events = []          # LOGIN_REQUIRED, LOGIN_CHALLENGE_DETECTED, CAPTCHA
    shopping_more_misses = []  # SHOPPING_MORE_MISSED
    hard_timeouts = []         # HARD_TIMEOUT
    not_founds = []            # NOT_FOUND
    other_errors = []          # 기타 예외

    success_by_device = defaultdict(lambda: {"total": 0, "success": 0})
    products_eval = defaultdict(list)

    for c in cycles:
        c_num = c.get("cycle", 1)
        c_ip = c.get("ip", "unknown")
        results = c.get("results", [])
        for r in results:
            total_tasks += 1
            st = str(r.get("status", "UNKNOWN"))
            status_counts[st] += 1
            dev = r.get("device_id", "unknown")
            err_msg = str(r.get("error_message") or r.get("error") or "")
            success_by_device[dev]["total"] += 1

            item_info = {
                "cycle": c_num,
                "device": dev,
                "keyword": r.get("keyword"),
                "nv_mid": r.get("nv_mid"),
                "status": st,
                "error": err_msg,
                "ip": c_ip
            }

            if st == "SUCCESS" or r.get("success"):
                total_success += 1
                success_by_device[dev]["success"] += 1
            elif any(k in st or k in err_msg for k in ("NETWORK_ERROR", "NET_ERROR", "ERR_NAME", "ERR_CONNECTION", "연결할 수 없습니다", "DNS")):
                network_errors.append(item_info)
            elif any(k in st or k in err_msg for k in ("SERP_TAB_NOT_FOUND", "SERP_TAB", "TAB_NOT_FOUND", "SearchHomePage")):
                serp_tab_misses.append(item_info)
            elif any(k in st or k in err_msg for k in ("IDENTITY_ROLLBACK", "HOOK_INTEGRITY", "NAPP_DI", "IDENTITY_ERROR")):
                identity_rollbacks.append(item_info)
            elif any(k in st or k in err_msg for k in ("LOGIN_REQUIRED", "LOGIN_CHALLENGE", "LOGIN", "CAPTCHA", "nidlogin")):
                login_events.append(item_info)
            elif any(k in st or k in err_msg for k in ("SHOPPING_MORE_MISSED", "MORE_MISSED", "MORE_NOT_FOUND")):
                shopping_more_misses.append(item_info)
            elif st == "HARD_TIMEOUT" or "TIMEOUT" in st:
                hard_timeouts.append(item_info)
            elif st == "NOT_FOUND" or "NOT_FOUND" in st:
                not_founds.append(item_info)
            else:
                other_errors.append(item_info)

            mid = str(r.get("nv_mid") or "")
            if mid and mid != "None":
                products_eval[mid].append({
                    "cycle": c_num,
                    "keyword": r.get("keyword"),
                    "store_name": r.get("store_name"),
                    "status": st,
                    "serp_rank": r.get("serp_rank"),
                    "shopping_rank": (r.get("js_target_rank") if (r.get("shopping_rank") == 1 and r.get("js_target_rank") and r.get("js_target_rank") > 1) else r.get("shopping_rank")),
                    "js_target_rank": r.get("js_target_rank"),
                    "shopping_page": r.get("shopping_page"),
                    "duration": r.get("duration_seconds", 0)
                })

    success_rate = round(total_success / total_tasks * 100, 1) if total_tasks else 0.0

    # [사용자 지침] 연결된 디바이스별 시간당 작업 성공/실패 및 시간대별 통계 산출
    batch_dur_sec = sum(float(c.get("cycle_dur", 0)) for c in cycles)
    if batch_dur_sec <= 0:
        batch_dur_sec = max(len(cycles) * 115.0, 1.0)
    batch_dur_hr = max(batch_dur_sec / 3600.0, 0.01)

    import subprocess
    connected_adb_devices = []
    try:
        adb_out = subprocess.check_output(["adb", "devices"], timeout=2).decode()
        connected_adb_devices = [l.split()[0] for l in adb_out.strip().split("\n")[1:] if "\tdevice" in l and not l.startswith("emulator")]
    except Exception:
        pass

    import datetime
    today_str = datetime.datetime.now().strftime("%Y%m%d")
    hist_file = LOGS_DIR / f"execution_history_{today_str}.jsonl"

    cum_dev_stats = defaultdict(lambda: {"total": 0, "success": 0, "fail": 0})
    hourly_breakdown = defaultdict(lambda: {"total": 0, "success": 0, "fail": 0})
    first_hist_ts = None
    last_hist_ts = None

    if hist_file.exists():
        try:
            with open(hist_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                        ts = d.get("timestamp") or ""
                        if not ts:
                            continue
                        if not first_hist_ts or ts < first_hist_ts:
                            first_hist_ts = ts
                        if not last_hist_ts or ts > last_hist_ts:
                            last_hist_ts = ts
                        dev_h = d.get("device_id", "unknown")
                        st_h = d.get("status")
                        is_succ_h = (st_h == "SUCCESS" or d.get("success") is True)
                        hour_str = ts[11:13] if len(ts) >= 13 else "??"

                        cum_dev_stats[dev_h]["total"] += 1
                        hourly_breakdown[hour_str]["total"] += 1
                        if is_succ_h:
                            cum_dev_stats[dev_h]["success"] += 1
                            hourly_breakdown[hour_str]["success"] += 1
                        else:
                            cum_dev_stats[dev_h]["fail"] += 1
                            hourly_breakdown[hour_str]["fail"] += 1
                    except Exception:
                        pass
        except Exception:
            pass

    session_dur_hr = 0.0
    if first_hist_ts and last_hist_ts:
        try:
            t1 = datetime.datetime.strptime(first_hist_ts, "%Y-%m-%d %H:%M:%S")
            t2 = datetime.datetime.strptime(last_hist_ts, "%Y-%m-%d %H:%M:%S")
            session_dur_hr = max((t2 - t1).total_seconds() / 3600.0, 0.05)
        except Exception:
            pass
    if session_dur_hr <= 0:
        session_dur_hr = batch_dur_hr

    device_hourly_stats = {}
    all_known_devices = sorted(list(set(connected_adb_devices) | set(success_by_device.keys()) | set(cum_dev_stats.keys())))

    for dev in all_known_devices:
        b_stat = success_by_device.get(dev, {"total": 0, "success": 0})
        b_tot = b_stat["total"]
        b_succ = b_stat["success"]
        b_fail = b_tot - b_succ
        b_rate = round(b_succ / b_tot * 100, 1) if b_tot else 0.0
        b_tph = round(b_tot / batch_dur_hr, 1)
        b_sph = round(b_succ / batch_dur_hr, 1)
        b_fph = round(b_fail / batch_dur_hr, 1)

        c_stat = cum_dev_stats.get(dev, {"total": 0, "success": 0, "fail": 0})
        c_tot = c_stat["total"]
        c_succ = c_stat["success"]
        c_fail = c_stat["fail"]
        c_rate = round(c_succ / c_tot * 100, 1) if c_tot else 0.0
        c_tph = round(c_tot / session_dur_hr, 1) if session_dur_hr > 0 else 0.0
        c_sph = round(c_succ / session_dur_hr, 1) if session_dur_hr > 0 else 0.0
        c_fph = round(c_fail / session_dur_hr, 1) if session_dur_hr > 0 else 0.0

        device_hourly_stats[dev] = {
            "batch_total": b_tot,
            "batch_success": b_succ,
            "batch_fail": b_fail,
            "batch_rate": b_rate,
            "batch_tph": b_tph,
            "batch_sph": b_sph,
            "batch_fph": b_fph,
            "cum_total": c_tot,
            "cum_success": c_succ,
            "cum_fail": c_fail,
            "cum_rate": c_rate,
            "cum_tph": c_tph,
            "cum_sph": c_sph,
            "cum_fph": c_fph,
            "is_connected": dev in connected_adb_devices,
        }

    return {
        "total_cycles": len(cycles),
        "total_tasks": total_tasks,
        "total_success": total_success,
        "success_rate": success_rate,
        "batch_duration_hr": round(batch_dur_hr, 2),
        "session_duration_hr": round(session_dur_hr, 2),
        "status_counts": dict(status_counts),
        "network_errors": network_errors,
        "serp_tab_misses": serp_tab_misses,
        "identity_rollbacks": identity_rollbacks,
        "login_events": login_events,
        "shopping_more_misses": shopping_more_misses,
        "hard_timeouts": hard_timeouts,
        "not_founds": not_founds,
        "other_errors": other_errors,
        "device_performance": dict(success_by_device),
        "device_hourly_stats": device_hourly_stats,
        "hourly_breakdown": dict(hourly_breakdown),
        "products": dict(products_eval)
    }


def get_historical_baselines() -> Dict[str, Dict[str, Any]]:
    """어제 및 이전 실행 기록에서 MID별 베이스라인 순위 추출"""
    import datetime
    baselines = defaultdict(lambda: {"serp": [], "shop": []})
    yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y%m%d")

    # 1. execution_history_{yesterday}.jsonl 로드
    hist_file = LOGS_DIR / f"execution_history_{yesterday}.jsonl"
    if hist_file.exists():
        try:
            with open(hist_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                        mid = str(d.get("nv_mid") or "")
                        if mid and mid != "None":
                            if d.get("serp_rank") is not None:
                                baselines[mid]["serp"].append(d["serp_rank"])
                            if d.get("shopping_rank") is not None:
                                baselines[mid]["shop"].append(d["shopping_rank"])
                    except Exception:
                        pass
        except Exception:
            pass

    # 2. run_*.json 보조 로드
    y_runs = glob.glob(str(LOGS_DIR / "**" / yesterday / "**" / "run_*.json"), recursive=True)
    for f in set(y_runs):
        data = load_run_file(f)
        cycles = data.get("cycles", []) if isinstance(data, dict) else []
        if not cycles and isinstance(data, dict) and "results" in data:
            cycles = [data]
        for c in cycles:
            for r in c.get("results", []):
                mid = str(r.get("nv_mid") or "")
                if mid and mid != "None":
                    if r.get("serp_rank") is not None:
                        baselines[mid]["serp"].append(r["serp_rank"])
                    if r.get("shopping_rank") is not None:
                        baselines[mid]["shop"].append(r["shopping_rank"])
    return baselines


def generate_evaluation_report(eval_res: Dict[str, Any], baselines: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    if baselines is None:
        baselines = get_historical_baselines()

    lines = []
    lines.append("=" * 85)
    cyc_cnt = eval_res.get('total_cycles', 10)
    lines.append(f"📊 [{cyc_cnt}회 사이클 배치 실행 종합 평가 & 시스템 무결성 리포트]")
    lines.append("=" * 85)
    lines.append(f"• 총 사이클 수 : {eval_res['total_cycles']}회")
    lines.append(f"• 총 실행 타수 : {eval_res['total_tasks']}타")
    lines.append(f"• 유효타 성공  : {eval_res['total_success']}타 ({eval_res['success_rate']}%)")
    lines.append("• 상태별 분포 : " + ", ".join([f"{k}: {v}건" for k, v in eval_res['status_counts'].items()]))

    lines.append("\n" + "-" * 85)
    lines.append("🚨 1. 시스템 무결성 & 핵심 에러 유형별 전수 집계")
    lines.append("-" * 85)

    net_errs = eval_res.get("network_errors", [])
    serp_errs = eval_res.get("serp_tab_misses", [])
    id_errs = eval_res.get("identity_rollbacks", [])
    login_errs = eval_res.get("login_events", [])
    more_errs = eval_res.get("shopping_more_misses", [])
    timeout_errs = eval_res.get("hard_timeouts", [])
    nf_errs = eval_res.get("not_founds", [])
    other_errs = eval_res.get("other_errors", [])

    lines.append(f"• 🌐 네트워크 에러 (NETWORK_ERROR / ERR_*)        : {len(net_errs):>2}건 {'✅ 정상 (0건)' if not net_errs else '⚠️ 주의'}")
    lines.append(f"• 📱 앱 기동 / SERP 탭 미발견 (SERP_TAB_NOT_FOUND) : {len(serp_errs):>2}건 {'✅ 정상 (0건)' if not serp_errs else '⚠️ 주의'}")
    lines.append(f"• 🛡️ 식별자 롤백 / 훅 실패 (IDENTITY_ROLLBACK)     : {len(id_errs):>2}건 {'✅ 정상 (0건)' if not id_errs else '⚠️ 주의'}")
    lines.append(f"• 🔒 FDS 로그인 / 캡차 차단 (LOGIN_REQUIRED)       : {len(login_errs):>2}건 {'✅ 정상 (0건)' if not login_errs else '⚠️ 주의'}")
    lines.append(f"• 🛒 쇼핑 더보기 버튼 미발견 (SHOPPING_MORE_MISSED) : {len(more_errs):>2}건")
    lines.append(f"• ⏱️ 단말기 하드 타임아웃 (HARD_TIMEOUT)           : {len(timeout_errs):>2}건")
    lines.append(f"• 🔍 타겟 상품 미노출 (NOT_FOUND)                 : {len(nf_errs):>2}건")
    if other_errs:
        lines.append(f"• ❓ 기타 예외 발생                               : {len(other_errs):>2}건")

    if net_errs:
        lines.append("\n   [⚠️ 네트워크 에러 세부 내역]")
        for ev in net_errs[:5]:
            lines.append(f"     ↳ Cycle #{ev['cycle']} | 단말: {ev['device']} | 키워드: '{ev['keyword']}' | {ev['error'][:60]}")
    if serp_errs:
        lines.append("\n   [⚠️ SERP 탭 미발견 세부 내역]")
        for ev in serp_errs[:5]:
            lines.append(f"     ↳ Cycle #{ev['cycle']} | 단말: {ev['device']} | 키워드: '{ev['keyword']}' | {ev['error'][:60]}")
    if id_errs:
        lines.append("\n   [⚠️ 식별자 롤백 세부 내역]")
        for ev in id_errs[:5]:
            lines.append(f"     ↳ Cycle #{ev['cycle']} | 단말: {ev['device']} | 키워드: '{ev['keyword']}' | {ev['error'][:60]}")
    if login_errs:
        lines.append("\n   [⚠️ 로그인/보안확인 세부 내역]")
        for ev in login_errs[:5]:
            lines.append(f"     ↳ Cycle #{ev['cycle']} | 단말: {ev['device']} | 키워드: '{ev['keyword']}' | {ev['error'][:60]}")

    lines.append("\n" + "-" * 85)
    lines.append("📈 2. 상품별 순위 변동 및 어제 베이스라인 대비 평가")
    lines.append("-" * 85)
    products = eval_res.get("products", {})
    lines.append(f"{'MID':<13} | {'키워드':<14} | {'스토어':<12} | {'유효타':<8} | {'현재 노출 순위':<18} | {'어제 대비 순위 변동'}")
    lines.append("-" * 85)

    for mid, plist in sorted(products.items(), key=lambda x: x[1][0].get("keyword", "")):
        kw = plist[0].get("keyword", "-")
        store = plist[0].get("store_name", "-")
        succ_cnt = sum(1 for p in plist if p.get("status") == "SUCCESS")
        total_p = len(plist)

        serp_ranks = [p.get("serp_rank") for p in plist if p.get("serp_rank") is not None]
        shop_ranks = [p.get("shopping_rank") for p in plist if p.get("shopping_rank") is not None]

        current_serp = min(serp_ranks) if serp_ranks else None
        current_shop = min(shop_ranks) if shop_ranks else None

        if current_serp is not None:
            rank_str = f"SERP {current_serp}위 (1P 노출)"
        elif current_shop is not None:
            rank_str = f"SHOP {current_shop}위"
        else:
            rank_str = "미노출/NOT_FOUND"

        delta_str = "-"
        base = baselines.get(mid)
        if base:
            b_serp = min(base["serp"]) if base["serp"] else None
            b_shop = min(base["shop"]) if base["shop"] else None

            if b_serp and current_serp:
                diff = b_serp - current_serp
                if diff > 0:
                    delta_str = f"🔺 {diff}위 상승 ({b_serp} -> {current_serp})"
                elif diff < 0:
                    delta_str = f"🔻 {abs(diff)}위 하락 ({b_serp} -> {current_serp})"
                else:
                    delta_str = f"동일 ({current_serp}위 유지)"
            elif b_shop and current_shop:
                diff = b_shop - current_shop
                if diff > 0:
                    delta_str = f"🔺 {diff}위 상승 ({b_shop} -> {current_shop})"
                elif diff < 0:
                    delta_str = f"🔻 {abs(diff)}위 하락 ({b_shop} -> {current_shop})"
                else:
                    delta_str = f"동일 ({current_shop}위 유지)"
            elif not b_serp and current_serp:
                delta_str = f"🚀 SERP 1P 신규 진입! (-> {current_serp}위)"
            elif b_serp and not current_serp and current_shop:
                delta_str = f"SERP -> 쇼핑탭 이동 ({current_shop}위)"

        lines.append(f"{mid:<13} | {kw:<14} | {store:<12} | {succ_cnt}/{total_p:<6} | {rank_str:<18} | {delta_str}")

    lines.append("\n" + "-" * 95)
    lines.append("📱 3. 연결된 디바이스별 시간당 작업 성공/실패 현황 (최근 10회 및 가동 세션 누적)")
    lines.append("-" * 95)
    dev_hourly = eval_res.get("device_hourly_stats", {})
    if dev_hourly:
        lines.append(f"{'단말기 ID':<13} | {'최근10회':<10} | {'성공률':<7} | {'시간당 성공':<10} | {'시간당 실패':<10} | {'시간당 총타수':<10} | {'누적 성공/총타수 (성공률)':<22}")
        lines.append("-" * 95)
        for dev, s in sorted(dev_hourly.items()):
            b_str = f"{s['batch_success']}/{s['batch_total']}"
            c_str = f"{s['cum_success']}/{s['cum_total']} ({s['cum_rate']}%)"
            sph_str = f"{s['batch_sph']}타/h"
            fph_str = f"{s['batch_fph']}타/h"
            tph_str = f"{s['batch_tph']}타/h"
            rate_str = f"{s['batch_rate']}%"
            lines.append(f"{dev:<13} | {b_str:<10} | {rate_str:<7} | {sph_str:<10} | {fph_str:<10} | {tph_str:<10} | {c_str:<22}")
    else:
        dev_perf = eval_res.get("device_performance", {})
        for dev, stat in sorted(dev_perf.items()):
            rate = round(stat['success'] / stat['total'] * 100, 1) if stat['total'] else 0
            lines.append(f"• {dev:<13} : {stat['success']:>2}/{stat['total']:>2} 성공 ({rate:>5.1f}%)")

    hourly_bd = eval_res.get("hourly_breakdown", {})
    if hourly_bd:
        lines.append("\n" + "-" * 95)
        lines.append("⏰ 4. 시간대별(Hourly) 작업 성공/실패 및 성공률 추이")
        lines.append("-" * 95)
        lines.append(f"{'시간대':<14} | {'총작업':<8} | {'성공':<8} | {'실패':<8} | {'성공률':<8}")
        lines.append("-" * 95)
        for h in sorted(hourly_bd.keys()):
            h_st = hourly_bd[h]
            h_tot = h_st["total"]
            h_succ = h_st["success"]
            h_fail = h_st["fail"]
            h_rate = round(h_succ / h_tot * 100, 1) if h_tot else 0.0
            lines.append(f"{h}:00~{h}:59    | {h_tot:>6}건 | {h_succ:>6}건 | {h_fail:>6}건 | {h_rate:>6.1f}%")

    lines.append("=" * 95)
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="10회 사이클 배치 실행 평가기")
    parser.add_argument("--file", type=str, default=None, help="평가할 run_*.json 파일 경로 (단일 파일)")
    parser.add_argument("--limit", type=int, default=10, help="평가할 최근 사이클 수 (기본: 10회)")
    parser.add_argument("--net-mode", type=str, default="lte", help="네트워크 모드")
    args = parser.parse_args()

    if args.file:
        target_file = Path(args.file)
        if not target_file.exists():
            print(f"❌ 대상 파일을 찾을 수 없습니다: {target_file}")
            sys.exit(1)
        print(f"🔍 [평가 대상 단일 파일]: {target_file}")
        data = load_run_file(str(target_file))
        res = evaluate_batch(data)
    else:
        pattern = str(LOGS_DIR / args.net_mode / "*" / "*" / f"run_{args.net_mode}_*.json")
        all_files = glob.glob(pattern)
        if not all_files:
            print(f"❌ 평가할 {args.net_mode} 실행 파일을 찾을 수 없습니다.")
            sys.exit(1)
        all_files.sort(key=os.path.getmtime, reverse=True)
        selected_files = all_files[:args.limit]
        selected_files.reverse()  # 시간순 정렬
        print(f"🔍 [최근 {len(selected_files)}개 사이클 종합 평가]:")
        batch_cycles = [load_run_file(f) for f in selected_files]
        batch_data = {
            "mode": args.net_mode,
            "total_cycles": len(batch_cycles),
            "cycles": batch_cycles
        }
        res = evaluate_batch(batch_data)

    print(generate_evaluation_report(res))
