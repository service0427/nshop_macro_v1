#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py

N-Shop Macro V1 마스터 통합 실행 엔트리포인트 (Master Unified Runner)
---------------------------------------------------------------------
더 이상 개별 스크립트(run_bench, run_parallel 등)를 번갈아 쓸 필요 없이,
단일 실행 파일에 직관적인 CLI 플래그를 조합하여 모든 환경과 타겟을 제어합니다.

핵심 기능:
  1. 완전 병렬 멀티프로세스(Multi-Processing) 엔진 (20개 독립 OS 프로세스)
  2. 중앙 API 실시간 할당 기본 + CLI 수동 파라미터 오버라이딩 (--keyword, --nvmid 등)
  3. 유연한 라이프사이클 종료 제어:
     - --until HH:MM (예: 18:30, 23:50 도달 시 자동 안전 마감)
     - --cycles N    (지정 회차 반복 후 종료)
     - --once        (1회 즉시 실행 후 종료)
  4. 다중 네트워크 모드 지원:
     - --net-mode lte (화웨이 LTE 동글 고속 토글)
     - --net-mode wg  (MikroTik WireGuard 원격 유선 라우터 모드, --router-num 지정)
  5. 2대 안전장치 기본 강제:
     - 기기당 60초 하드 타임아웃 (--timeout 60)
     - 회차당 최소 60초 완충 보장 (--min-cycle-dur 60)
     - PC 메인 유선 이더넷(enp42s0) 100% 보존
"""

import os
import sys
import time
import json
import argparse
import asyncio
import subprocess
import concurrent.futures
import glob
import unicodedata
import logging
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple, Set

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from config.settings import CENTRAL_API_BASE, LOGS_DIR, TIMINGS, CONFIG_DIR
from src.core.api_client import CentralApiClient
from src.device.device_selector import get_online_devices
from src.device.network_controller import get_network_controller
from src.monitor.fleet_state import FleetStateManager


def visual_len(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ('F', 'W') else 1 for ch in str(s))


def truncate_visual(s: str, max_w: int) -> str:
    s = str(s)
    if visual_len(s) <= max_w:
        return s
    res = []
    w = 0
    for ch in s:
        ch_w = 2 if unicodedata.east_asian_width(ch) in ('F', 'W') else 1
        if w + ch_w > max_w - 2:
            break
        res.append(ch)
        w += ch_w
    return "".join(res) + ".."


def pad_str(s: str, width: int, align: str = 'left') -> str:
    s = truncate_visual(s, width)
    vl = visual_len(s)
    pad = max(0, width - vl)
    if align == 'right':
        return ' ' * pad + s
    elif align == 'center':
        left = pad // 2
        right = pad - left
        return ' ' * left + s + ' ' * right
    else:
        return s + ' ' * pad


def load_recent_failure_history(logs_dir: Path, net_mode: str, lookback_cycles: int = 30) -> Tuple[Dict[str, int], Dict[str, float]]:
    """
    최근 실행 결과(오늘 로그)로부터 미노출 실패 이력 및 격리 목록 복원:
    - 판매처 묶음 상품(카탈로그): 1회 이상 실패 시 즉시 격리
    - 일반 단독 상품: 3회 이상 연속 실패 시 격리
    - 최근 SUCCESS 기록된 상품: 실패 카운트 0 리셋 및 격리 해제
    """
    failure_counts: Dict[str, int] = defaultdict(int)
    quarantined: Dict[str, float] = {}
    today = time.strftime("%Y%m%d")
    cycle_files = sorted(glob.glob(str(logs_dir / net_mode / today / "*" / f"run_{net_mode}_{today}_*.json")))
    if not cycle_files:
        return failure_counts, quarantined

    recent = cycle_files[-lookback_cycles:] if len(cycle_files) >= lookback_cycles else cycle_files
    now_ts = time.time()

    for fpath in recent:
        try:
            file_mtime = os.path.getmtime(fpath)
            # 4시간(14,400초) 이상 지난 과거 로그의 실패는 재점검 대상이므로 격리하지 않음
            if now_ts - file_mtime >= 4 * 3600:
                continue

            with open(fpath, "r", encoding="utf-8") as f:
                d = json.load(f)
                for r in d.get("results", []):
                    mid = str(r.get("nv_mid") or "")
                    if not mid:
                        continue
                    st = r.get("status")
                    is_cat = bool(r.get("compare_id") or r.get("is_catalog") or r.get("target_type") == "CATALOG" or r.get("card_type") == "CATALOG_CARD")
                    if st == "SUCCESS":
                        failure_counts[mid] = 0
                        quarantined.pop(mid, None)
                    elif st in ("NOT_FOUND", "NOT_SHOPPING_KEYWORD") or (str(st).startswith("NOT_FOUND")):
                        # [오직 순수 40위 밖 미노출만 상품 쿨다운] CLICK_MISSED, TIMEOUT 등 단말기 환경 오류는 상품 풀에서 배제하지 않음
                        if is_cat:
                            quarantined[mid] = file_mtime
                        else:
                            failure_counts[mid] += 1
                            if failure_counts[mid] >= 3:
                                quarantined[mid] = file_mtime
        except Exception:
            pass

    return failure_counts, quarantined


def load_today_product_success_counts(logs_dir: Path) -> Dict[str, int]:
    """오늘(당일) execution_history_{today}.jsonl 로부터 MID별 누적 유효타(SUCCESS) 성공 횟수 집계"""
    today = time.strftime("%Y%m%d")
    hist_file = logs_dir / f"execution_history_{today}.jsonl"
    counts: Dict[str, int] = defaultdict(int)
    if not hist_file.exists():
        return counts
    try:
        with open(hist_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    mid = str(d.get("nv_mid") or "")
                    if mid and mid != "None" and (d.get("status") == "SUCCESS" or d.get("success")):
                        counts[mid] += 1
                except Exception:
                    pass
    except Exception:
        pass
    return counts


class ProcessTeeStream:
    """단말기 독립 워커의 콘솔 출력(stdout/stderr)을 터미널 화면과 단말기 전용 process.log 파일로 동시 분기 기록"""
    def __init__(self, filepath: Path, orig_stream):
        self.orig_stream = orig_stream
        self.filepath = filepath
        try:
            self.file = open(filepath, "a", encoding="utf-8", buffering=1)
        except Exception:
            self.file = None

    def write(self, data):
        if self.orig_stream:
            try:
                self.orig_stream.write(data)
                self.orig_stream.flush()
            except Exception:
                pass
        if self.file:
            try:
                self.file.write(data)
                self.file.flush()
            except Exception:
                pass

    def flush(self):
        if self.orig_stream:
            try:
                self.orig_stream.flush()
            except Exception:
                pass
        if self.file:
            try:
                self.file.flush()
            except Exception:
                pass

    def close(self):
        if self.file:
            try:
                self.file.close()
            except Exception:
                pass
            self.file = None


# ==============================================================================
# 1. 독립 OS 워커 프로세스 진입점 (Worker Process Entrypoint)
# ==============================================================================
def worker_process_entry(task_dict: Dict[str, Any], api_base: str, start_delay: float, timeout_sec: float) -> Dict[str, Any]:
    """
    독립 OS 프로세스에서 실행되는 단일 단말기 전용 타격 진입점
    (독립 GIL, 독립 메모리, 전용 이벤트 루프, 하드 타임아웃 강제)
    """
    dev_id = task_dict["device_id"]
    cycle_ymd = task_dict.get("cycle_ymd") or time.strftime("%Y%m%d")
    cycle_his = task_dict.get("cycle_his") or time.strftime("%H%M%S")
    dev_log_dir = LOGS_DIR / "traffic" / cycle_ymd / cycle_his / dev_id
    dev_log_dir.mkdir(parents=True, exist_ok=True)
    process_log_path = dev_log_dir / "process.log"

    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    tee_out = ProcessTeeStream(process_log_path, orig_stdout)
    tee_err = ProcessTeeStream(process_log_path, orig_stderr)
    sys.stdout = tee_out
    sys.stderr = tee_err

    # 워커 프로세스 로거 핸들러 바인딩 (process.log 및 콘솔 동시 스트리밍 보장)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)
    log_handler = logging.StreamHandler(tee_out)
    log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s", datefmt="%H:%M:%S"))
    root_logger.addHandler(log_handler)

    if start_delay > 0:
        FleetStateManager.update_device(
            device_id=dev_id,
            state="STAGGER_WAIT",
            keyword=task_dict.get("keyword", "-"),
            store_name=task_dict.get("store_name", "-"),
            target_mid=str(task_dict.get("nv_mid", "-")),
            progress=f"기동 시차 대기 ({start_delay:.1f}s)",
            status_msg="LTE 대역폭 보호 시차 대기"
        )
        time.sleep(start_delay)

    FleetStateManager.update_device(
        device_id=dev_id,
        state="LAUNCHING",
        keyword=task_dict.get("keyword", "-"),
        store_name=task_dict.get("store_name", "-"),
        target_mid=str(task_dict.get("nv_mid", "-")),
        progress="1회용 클린 기동",
        status_msg="네이버 앱 기동 및 무결성 검증"
    )
    pid = os.getpid()
    t0 = time.time()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        from src.pipeline.models import TaskInput
        from src.pipeline.executor import execute_task_pipeline as execute_task

        task_input = TaskInput(
            task_id=task_dict["task_id"],
            keyword=task_dict["keyword"],
            nv_mid=task_dict.get("nv_mid", ""),
            target_rank=task_dict.get("target_rank"),
            compare_id=task_dict.get("compare_id"),
            store_name=task_dict.get("store_name", ""),
            nnb=task_dict.get("nnb"),
            buc=task_dict.get("buc"),
            device_id=dev_id,
            dwell_seconds=task_dict.get("dwell_seconds", 10),
            ip=task_dict.get("ip", "unknown"),
            scroll_mode=task_dict.get("scroll_mode", "real_swipe"),
            cycle_ymd=task_dict.get("cycle_ymd"),
            cycle_his=task_dict.get("cycle_his"),
            target_cycle_dur=task_dict.get("target_cycle_dur", 60.0),
            task_start_time=t0,
            node_id=task_dict.get("node_id", "node-default"),
            ip_c_class=task_dict.get("ip_c_class"),
            keyword_candidates=task_dict.get("keyword_candidates")
        )

        # [하드 타임아웃 강제 차단]
        try:
            result = loop.run_until_complete(asyncio.wait_for(execute_task(task_input), timeout=timeout_sec))
        except asyncio.TimeoutError:
            dur = round(time.time() - t0, 2)
            print(f"⏰ [PID {pid:>5}] [{dev_id}] 하드 타임아웃 초과 ({timeout_sec}s 강제 차단 및 앱 종료)")
            subprocess.run(f"adb -s {dev_id} shell am force-stop com.nhn.android.search", shell=True, timeout=5)
            err_res = {
                "device_id": dev_id,
                "task_id": task_dict.get("task_id"),
                "status": "HARD_TIMEOUT",
                "success": False,
                "error_message": f"개별 단말기 최대 제한시간({timeout_sec}초) 초과로 인한 강제 종료",
                "duration_seconds": dur
            }
            try:
                client = CentralApiClient(api_base)
                client.report_task(err_res)
            except Exception:
                pass
            return err_res

        dur = round(time.time() - t0, 2)
        result["duration_seconds"] = dur
        result["device_id"] = dev_id
        result["task_id"] = task_dict["task_id"]
        result["keyword"] = task_dict.get("keyword", "")
        if not result.get("nv_mid"):
            result["nv_mid"] = task_dict.get("nv_mid", "")
        if task_dict.get("compare_id"):
            result["compare_id"] = task_dict.get("compare_id")
        result["is_catalog"] = bool(task_dict.get("compare_id") or result.get("is_catalog") or result.get("target_type") == "CATALOG" or result.get("card_type") == "CATALOG_CARD")
        if not result.get("store_name"):
            result["store_name"] = task_dict.get("store_name", "")

        st = result.get("status", "UNKNOWN")
        search_type = result.get("search_type") or ("m.search" if (result.get("match_type") == "SERP" or result.get("serp_rank")) else "msearch")
        click_source = result.get("click_source") or ("SERP (m.search.naver.com)" if search_type == "m.search" else "SHOPPING_TAB (msearch.shopping.naver.com)")

        if search_type == "m.search":
            serp_r = result.get("serp_rank")
            rank_str = f"SERP {serp_r}위" if serp_r is not None else "SERP"
        else:
            shp_r = result.get("shopping_rank")
            shp_p = result.get("shopping_page") or 1
            rank_str = f"쇼핑 {shp_p}P {shp_r}위" if shp_r is not None else "쇼핑탭"

        keyword = task_dict.get("keyword") or "-"
        store = result.get("store_name") or task_dict.get("store_name") or "-"
        audit_path = result.get("audit_log_path")
        landing_url = result.get("landing_url")

        print(f"🏁 [PID {pid:>5}] [{dev_id}] 타격 완료 ({dur}s) -> 상태: {st} | 경로: {click_source} | 순위: {rank_str} | 키워드: '{keyword}' | 몰: {store}")
        FleetStateManager.update_device(
            device_id=dev_id,
            state=st,
            elapsed_sec=dur,
            last_result=st,
            rank=rank_str,
            progress=f"{st} ({rank_str})"
        )
        if landing_url:
            print(f"   ↳ 🌐 [랜딩 URL]: {landing_url[:110]}")
        if audit_path:
            print(f"   ↳ 📡 [트래픽 감사로그]: {audit_path}")

        # 중앙 API 결과 보고 (수집 모드 시 생략)
        if int(task_dict.get("task_id", 0)) >= 990000:
            return result

        client = CentralApiClient(api_base)
        try:
            report_res = client.report_task(result)
            result["api_reported"] = report_res.get("success", False)
            rep_payload = report_res.get("reported_payload") or {}
            print(f"   ↳ 📊 [API 리턴/보고]: search_type='{rep_payload.get('search_type')}' | match_type='{rep_payload.get('match_type')}' | serp_rank={rep_payload.get('serp_rank')} | shopping_rank={rep_payload.get('shopping_rank')} | store='{rep_payload.get('store_name')}' | reported={result['api_reported']}")
        except Exception as e:
            result["api_reported"] = False
            result["api_report_error"] = str(e)
            print(f"   ↳ ⚠️ [중앙 API 보고 실패]: {e}")

        return result
    except Exception as e:
        dur = round(time.time() - t0, 2)
        print(f"❌ [PID {pid:>5}] [{dev_id}] 예외 발생 ({dur}s): {e}")
        err_res = {
            "device_id": dev_id,
            "task_id": task_dict.get("task_id"),
            "status": "FATAL_EXCEPTION",
            "success": False,
            "error_message": str(e),
            "duration_seconds": dur
        }
        try:
            client = CentralApiClient(api_base)
            client.report_task(err_res)
        except Exception:
            pass
        return err_res
    finally:
        sys.stdout = orig_stdout
        sys.stderr = orig_stderr
        tee_out.close()
        tee_err.close()
        loop.close()


def wake_devices_parallel(devices: List[str]):
    """20대 단말기 화면 언락 및 펼침 상태 병렬 보장"""
    def _wake(d):
        subprocess.run(
            f"adb -s {d} shell 'cmd device_state state 3; input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard'",
            shell=True, capture_output=True, timeout=5
        )
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(devices), 20)) as ex:
        list(ex.map(_wake, devices))


def is_until_reached(until_str: Optional[str], start_time: Optional[float] = None) -> bool:
    """당일/익일 목표 시각(HH:MM 또는 YYYY-MM-DD HH:MM) 도달 여부 판정 (자정 통과 완벽 지원)"""
    if not until_str:
        return False
    try:
        import datetime
        now = datetime.datetime.now()
        s_time = datetime.datetime.fromtimestamp(start_time) if start_time else now

        clean_str = until_str.strip()
        if "-" in clean_str:
            target_dt = datetime.datetime.strptime(clean_str, "%Y-%m-%d %H:%M")
        else:
            parts = clean_str.split(":")
            h, m = int(parts[0]), int(parts[1])
            target_dt = s_time.replace(hour=h, minute=m, second=0, microsecond=0)
            if target_dt <= s_time:
                target_dt += datetime.timedelta(days=1)

        return now >= target_dt
    except Exception:
        return False


def build_cycle_tasks(
    target_devices: List[str],
    current_ip: str,
    cycle: int,
    args: argparse.Namespace,
    client: CentralApiClient,
    cycle_ymd: Optional[str] = None,
    cycle_his: Optional[str] = None,
    exclude_mids: Optional[set] = None
) -> List[Dict[str, Any]]:
    """
    회차별 작업 리스트 생성:
    - 기본: 중앙 API에서 실시간 할당받음 (NOT_FOUND 상품은 exclude_mids로 제외하여 다른 랜덤 상품 자동 할당)
    - 오버라이딩: CLI에 입력된 파라미터(--keyword, --nvmid 등)가 있으면 최우선 강제 덮어쓰기
    """
    has_full_manual = bool(args.keyword and (args.nvmid or getattr(args, "target_rank", None) is not None))
    assigned_by_dev = {}

    import socket
    node_id_val = getattr(args, "node_id", None) or socket.gethostname() or "node-default"
    c_class_val = None
    if current_ip and "." in current_ip:
        parts = current_ip.split(".")
        if len(parts) >= 3:
            c_class_val = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"

    # [50대 대표 대형 키워드 오가닉 30~40위 순수 단일 상품 수집 모드]
    if getattr(args, "harvest_major", False):
        from src.tools.harvest_fleet_35 import MAJOR_ECOMMERCE_KEYWORDS_50
        raw_dir = LOGS_DIR / "harvest" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        existing_kws = set()
        for f in raw_dir.glob("*.json"):
            stem = f.stem
            kw = stem.split("_")[0]
            existing_kws.add(kw)

        pending_kws = [k for k in MAJOR_ECOMMERCE_KEYWORDS_50 if k not in existing_kws]
        if not pending_kws:
            print("🎉 [수집 완료] 50대 대표 키워드 전수 수집 완료!")
            return []
        active_pool = pending_kws

        prepared_tasks = []
        for idx, dev_id in enumerate(target_devices):
            if idx < len(active_pool):
                target_kw = active_pool[idx]
                td = {
                    "task_id": 990000 + (cycle * 100) + idx,
                    "keyword": target_kw,
                    "target_rank": 999,
                    "nv_mid": "",
                    "store_name": "",
                    "device_id": dev_id,
                    "ip": current_ip,
                    "nnb": None,
                    "buc": None,
                    "node_id": node_id_val,
                    "ip_c_class": c_class_val,
                    "dwell_seconds": 1,
                    "scroll_mode": "none",
                    "cycle_ymd": cycle_ymd,
                    "cycle_his": cycle_his,
                    "target_cycle_dur": 20.0
                }
                prepared_tasks.append(td)
        return prepared_tasks

    use_v2 = not getattr(args, "api_v1", False)
    if not has_full_manual:
        try:
            ex_list = list(exclude_mids) if exclude_mids else []
            if use_v2:
                # [차세대 v2 지능형 스케줄러] 유니크 상품 마스터, 슬롯 합산 100타 상한 캡, 1~5순위 키워드 풀 자동 회전
                v2_payload = {
                    "node_id": node_id_val,
                    "net_mode": args.net_mode,
                    "router_num": getattr(args, "router_num", "001"),
                    "public_ip": current_ip,
                    "ip_c_class": c_class_val,
                    "devices": target_devices,
                    "local_quarantine_mids": ex_list
                }
                alloc_res = client.allocate_v2(v2_payload)
                tasks_data = alloc_res.get("tasks", [])
                assigned_by_dev = {t["device_id"]: t for t in tasks_data if "device_id" in t}
            else:
                # [v1 레거시 스케줄러] nshop_list 직접 매칭
                assign_res = client.assign(device_ids=target_devices, ip=current_ip, exclude_mids=ex_list)
                tasks_data = assign_res.get("tasks", [])
                if not tasks_data and ex_list:
                    reduced_ex = ex_list[:len(ex_list)//2]
                    assign_res = client.assign(device_ids=target_devices, ip=current_ip, exclude_mids=reduced_ex)
                    tasks_data = assign_res.get("tasks", [])
                    if not tasks_data:
                        assign_res = client.assign(device_ids=target_devices, ip=current_ip)
                        tasks_data = assign_res.get("tasks", [])
                assigned_by_dev = {t["device_id"]: t for t in tasks_data if "device_id" in t}
        except Exception as e:
            print(f"⚠️ [중앙 API 할당 통신 예외] {e}")

    prepared_tasks = []
    for idx, dev_id in enumerate(target_devices):
        if dev_id in assigned_by_dev:
            td = assigned_by_dev[dev_id].copy()
        elif has_full_manual:
            td = {
                "task_id": 900000 + (cycle * 100) + idx,
                "keyword": args.keyword or "실리콘 수영가방 수영장 수영복 사우나 목욕 물놀이 가방 바구니 비치백 M",
                "nv_mid": args.nvmid or "89781061246",
                "store_name": getattr(args, "store", None) or "키지다이브",
                "device_id": dev_id,
                "ip": current_ip,
                "nnb": None,
                "buc": None
            }
        else:
            # 순수 API 모드: 중앙 API에서 해당 기기에 작업을 할당하지 않은 경우 (스토어 쿨다운 등) 안전 유휴 대기
            continue

        # 사용자 CLI 오버라이딩 적용 (최우선)
        if args.keyword:
            td["keyword"] = args.keyword
        if args.nvmid:
            td["nv_mid"] = args.nvmid
        if getattr(args, "target_rank", None) is not None:
            td["target_rank"] = args.target_rank
            if not args.nvmid:
                td["nv_mid"] = ""  # target_rank 기반 타격 시 nv_mid 불필요
        if args.compare_id is not None:
            td["compare_id"] = args.compare_id
        if getattr(args, "store", None):
            td["store_name"] = args.store
        if args.nnb:
            td["nnb"] = args.nnb
        if args.buc:
            td["buc"] = args.buc
        if args.task_id:
            td["task_id"] = int(args.task_id) if str(args.task_id).isdigit() else args.task_id

        td["ip"] = current_ip
        td["node_id"] = node_id_val
        td["ip_c_class"] = c_class_val
        td["dwell_seconds"] = args.dwell
        td["scroll_mode"] = getattr(args, "scroll_mode", "real_swipe")
        td["cycle_ymd"] = cycle_ymd
        td["cycle_his"] = cycle_his
        td["target_cycle_dur"] = getattr(args, "target_cycle_dur", 60.0)
        prepared_tasks.append(td)

    return prepared_tasks


# ==============================================================================
# 2. 메인 CLI 진입점 (Main CLI Entrypoint)
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="N-Shop Macro V1 Master Unified Runner (run.py)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시 (Examples):
  # 1. [상용 실전] LTE 동글 모드로 오늘 밤 23:50까지 무중단 자동 순환
  python3 run.py --net-mode lte --until 23:50

  # 2. [파주 라우터] MikroTik 001번으로 10회 연속 사이클 타격
  python3 run.py --net-mode wg --router-num 001 --cycles 10

  # 3. [전국 라우터 순환] 파주(001) -> 계산(002) -> 청라(004) 순환 타격
  python3 run.py --net-mode wg --router-list 001,002,004 --cycles 6

  # 4. [수동 오버라이딩 (nvmid)] 특정 상품을 20대 전원으로 1회 즉시 타격
  python3 run.py --keyword "보관백" --nvmid "41733443548" --once

  # 5. [디버깅 오버라이딩 (순위)] 특정 오가닉 순위(예: 10등 또는 40등)를 1회 즉시 타격
  python3 run.py --keyword "노트북" --target-rank 10 --once
  python3 run.py --keyword "노트북" --target-rank 40 --once

  # 6. [단일 기기 점검] R3CR70FFFEK 1대만 1회 단독 실행
  python3 run.py -d R3CR70FFFEK --once

  # 7. [보조 진단 명령]
  python3 run.py --ip-only      # 현재 공인 IP 확인
  python3 run.py --check        # 20대 단말기 연결 상태 진단
  python3 run.py --wake         # 20대 단말기 화면 언락
  python3 run.py --clear-app    # 20대 네이버 앱 일괄 force-stop
  python3 run.py --grid         # 20대 실시간 화면 그리드 관제
        """
    )

    # 1) 네트워크 및 IP 제어
    net_group = parser.add_argument_group("네트워크 및 IP 설정 (Network & IP)")
    net_group.add_argument("--net-mode", type=str, default="lte", choices=["lte", "wg", "local"],
                           help="네트워크 모드 (lte: 화웨이 동글, wg: MikroTik WireGuard, local: PC 메인 이더넷, 기본: lte)")
    net_group.add_argument("--router-num", type=str, default="001",
                           help="WireGuard 모드 시 원격 MikroTik 라우터 번호 (기본: 001 파주)")
    net_group.add_argument("--router-list", type=str, default=None,
                           help="WireGuard 모드 시 회차별 순환할 라우터 목록 (콤마 구분: 001,002,004)")
    net_group.add_argument("--no-toggle", action="store_true",
                           help="회차 간 IP 토글을 수행하지 않고 현재 IP 그대로 유지")
    net_group.add_argument("--min-cycle-dur", type=float, default=TIMINGS.MIN_CYCLE_DURATION,
                           help="회차당 최소 완충 소요시간 (초, 기본: 0.0초, 미사용 시 즉시 토글)")

    # 2) 실행 라이프사이클 및 종료 조건
    sched_group = parser.add_argument_group("스케줄 및 종료 조건 (Schedule & Termination)")
    sched_group.add_argument("--until", type=str, default=None,
                             help="당일 목표 종료 시각 (HH:MM 형식, 예: 18:30, 23:50)")
    sched_group.add_argument("--cycles", type=int, default=None,
                             help="지정 횟수 반복 실행 후 종료 (예: 3, 10)")
    sched_group.add_argument("--once", action="store_true",
                             help="단 1회만 실행하고 즉시 종료 (--cycles 1과 동일)")
    sched_group.add_argument("--interval", type=int, default=int(TIMINGS.IP_TOGGLE_SETTLE_INTERVAL),
                             help="토글 후 통신망 안정화 대기 시간 (초, 20대 USB 테더링/DNS 전파 완충)")
    sched_group.add_argument("--target-cycle-dur", type=float, default=TIMINGS.TARGET_CYCLE_DURATION,
                             help="목표 1회 사이클 전체 소요 시간 (초, QoS 대역폭 분산 및 동적 체류 완충)")
    sched_group.add_argument("--eval-interval", type=int, default=10,
                             help="종합 평가 리포트 생성 및 순위 변동 분석 주기 (회차 단위, 기본: 10회)")
    sched_group.add_argument("--node-id", type=str, default=None,
                             help="분산 워커 노드 식별자 (미지정 시 호스트명 자동 사용)")

    # 3) 단말기 선택
    dev_group = parser.add_argument_group("단말기 대상 설정 (Device Target)")
    dev_group.add_argument("-c", "--count", type=int, default=20,
                           help="온라인 단말기 중 투입할 대수 (기본: 20대)")
    dev_group.add_argument("-d", "--device", "--devices", dest="devices", type=str, default=None,
                           help="특정 단말기 시리얼 지정 (단일 기기 또는 콤마 구분: R3CR70FFFEK,R3CR70K98XZ)")

    # 4) 작업 및 타겟 파라미터 오버라이딩
    override_group = parser.add_argument_group("작업 및 타겟 오버라이딩 (Task Overrides)")
    override_group.add_argument("--keyword", type=str, default=None, help="검색 키워드 강제 지정")
    override_group.add_argument("--nvmid", type=str, default=None, help="타겟 상품 nv_mid 강제 지정")
    override_group.add_argument("--exclude-mids", type=str, default=None,
                                help="제외할 nv_mid 목록 (콤마 구분, 예: 86717220700,88196932962)")
    override_group.add_argument("--target-rank", "--rank", dest="target_rank", type=int, default=None,
                                help="타겟 오가닉 순위 지정 (예: 10, 40. nvmid 대신 순위로 타격)")
    override_group.add_argument("--compare-id", type=str, default=None, help="카탈로그 매칭 compare_id 강제 지정")
    override_group.add_argument("--store", type=str, default=None, help=argparse.SUPPRESS)
    override_group.add_argument("--nnb", type=str, default=None, help="쿠키 NNB 값 강제 지정")
    override_group.add_argument("--buc", type=str, default=None, help="쿠키 BUC 값 강제 지정")
    override_group.add_argument("--task-id", type=str, default=None, help="특정 Task ID 수동 지정")
    override_group.add_argument("--dwell", type=int, default=int(TIMINGS.DWELL_DEFAULT_SECONDS), help="상세페이지 체류 시간 (초, 기본: 40초)")
    override_group.add_argument("--scroll-mode", type=str, default="real_swipe", choices=["real_swipe", "js", "none"],
                                help="상세페이지 스크롤 체류 모드 (기본: real_swipe)")
    override_group.add_argument("--timeout", type=float, default=TIMINGS.DEVICE_HARD_TIMEOUT, help="개별 단말기 하드 타임아웃 (초, QoS 대역폭 저하 및 체류 90초 동기화 보장)")
    override_group.add_argument("--api-v2", action="store_true", default=True,
                                help="차세대 v2 지능형 스케줄러(유니크 상품, 슬롯 100타 상한 캡, 1~5순위 키워드 풀) 사용 (기본: True)")
    override_group.add_argument("--max-hits-per-item", type=int, default=100,
                                help="당일 상품(MID)당 최대 유효타 상한 캡 (기본: 100회, 도달 시 오늘 타격 제외 및 전원 완료 시 종료)")
    override_group.add_argument("--api-v1", action="store_true", default=False,
                                help="과거 v1 레거시 스케줄러(nshop_list 직접 매칭) 강제 사용")
    override_group.add_argument("--no-wake", action="store_true", help="화면 언락 및 깨우기 절차 생략")
    override_group.add_argument("--harvest-major", action="store_true",
                                help="50대 대표 대형 키워드 35위 오가닉 상품 20대 병렬 수집 모드")

    # 5) 보조 진단 명령
    diag_group = parser.add_argument_group("보조 진단 및 유틸리티 명령 (Diagnostics & Utilities)")
    diag_group.add_argument("--check", action="store_true", help="단말기 연결 상태 진단만 출력 후 즉시 종료")
    diag_group.add_argument("--ip-only", action="store_true", help="현재 외부 공인 IP 확인만 출력 후 즉시 종료")
    diag_group.add_argument("--wake", action="store_true", help="대상 단말기 화면 언락 및 펼침만 수행 후 종료")
    diag_group.add_argument("--clear-app", action="store_true", help="대상 단말기 네이버 앱 강제 종료(force-stop)만 수행 후 종료")
    diag_group.add_argument("--wifi-off", action="store_true", help="대상 단말기 Wi-Fi 일괄 강제 비활성화(OFF) 후 종료")
    diag_group.add_argument("--battery", action="store_true", help="대상 단말기 배터리 잔량 및 충전 상태 일괄 점검 후 종료")
    diag_group.add_argument("--grid", action="store_true", help="20대 단말기 실시간 화면 그리드 관제(scrcpy) 실행")
    diag_group.add_argument("--dry-run", action="store_true", help="실제 타격 없이 네트워크 및 작업 할당 계획만 검증 후 종료")

    args = parser.parse_args()

    # --once 플래그 처리
    if args.once:
        args.cycles = 1

    # [Local 모드] PC 메인 유선 이더넷은 고정 IP이므로 --no-toggle 기본 강제 적용
    if args.net_mode == "local":
        args.no_toggle = True

    # --------------------------------------------------------------------------
    # 보조 진단 및 단말기 타겟 확정
    # --------------------------------------------------------------------------
    all_online_devs = get_online_devices(force_refresh=True)

    if args.check:
        print("=" * 65)
        print(f"📱 [단말기 상태 진단] 총 {len(all_online_devs)}대 온라인 감지:")
        for idx, d in enumerate(all_online_devs, 1):
            print(f"   [{idx:02d}] {d}")
        print("=" * 65)
        return

    if args.devices:
        target_devices = [d.strip() for d in args.devices.split(",") if d.strip()]
    else:
        target_devices = all_online_devs[:args.count]

    if not target_devices and not (args.ip_only or args.grid):
        print("❌ 작업에 투입할 수 있는 온라인 단말기가 없습니다.")
        return

    sample_dev = target_devices[0] if target_devices else (all_online_devs[0] if all_online_devs else None)

    # 1) 화면 언락 전용 실행 (--wake)
    if args.wake:
        print(f"☀️ [{len(target_devices)}대 단말기 화면 언락 및 펼침 상태 동기화]...")
        wake_devices_parallel(target_devices)
        print(f"✅ {len(target_devices)}대 단말기 화면 언락 및 활성화 완료.")
        return

    # 2) 네이버 앱 강제 종료 전용 실행 (--clear-app)
    if args.clear_app:
        print(f"🛑 [{len(target_devices)}대 단말기 네이버 공식 앱 일괄 force-stop]...")
        def _stop_app(d):
            subprocess.run(f"adb -s {d} shell am force-stop com.nhn.android.search", shell=True, capture_output=True, timeout=5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(target_devices), 20)) as ex:
            list(ex.map(_stop_app, target_devices))
        print(f"✅ {len(target_devices)}대 단말기 네이버 앱 완전 종료 완료.")
        return

    # 3) Wi-Fi 일괄 강제 비활성화 (--wifi-off)
    if args.wifi_off:
        print(f"📶 [{len(target_devices)}대 단말기 Wi-Fi 일괄 100% OFF 강제]...")
        def _disable_wifi(d):
            subprocess.run(f"adb -s {d} shell svc wifi disable", shell=True, capture_output=True, timeout=5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(target_devices), 20)) as ex:
            list(ex.map(_disable_wifi, target_devices))
        print(f"✅ {len(target_devices)}대 단말기 Wi-Fi 비활성화 완료 (순수 USB 역테더링 보장).")
        return

    # 4) 배터리 잔량 점검 (--battery)
    if args.battery:
        print("=" * 65)
        print(f"🔋 [{len(target_devices)}대 단말기 배터리 잔량 및 충전 상태 점검]")
        print("=" * 65)
        def _get_bat(d):
            r = subprocess.run(f"adb -s {d} shell dumpsys battery", shell=True, capture_output=True, text=True, timeout=5)
            level = "-"
            status = "-"
            for line in r.stdout.splitlines():
                if "level:" in line:
                    level = line.split("level:")[1].strip() + "%"
                elif "status:" in line:
                    st_code = line.split("status:")[1].strip()
                    status = "완충(Full)" if st_code == "5" else ("충전중(Charging)" if st_code == "2" else ("방전중(Discharging)" if st_code == "3" else f"상태({st_code})"))
            return d, level, status
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(target_devices), 20)) as ex:
            bat_results = list(ex.map(_get_bat, target_devices))
        for d, lvl, st in bat_results:
            print(f"  • [{d}] 배터리: {lvl:<5} | {st}")
        print("=" * 65)
        return

    # 5) 실시간 화면 그리드 관제 (--grid)
    if args.grid:
        print("🖥️ [20대 실시간 화면 그리드 관제(scrcpy) 기동]...")
        grid_sh = ROOT_DIR / "install" / "start_scrcpy_grid.sh"
        if grid_sh.exists():
            subprocess.run(f"bash {grid_sh}", shell=True)
        else:
            print(f"❌ {grid_sh} 파일이 존재하지 않습니다.")
        return

    # 네트워크 컨트롤러 초기 준비
    router_list = [r.strip() for r in args.router_list.split(",") if r.strip()] if args.router_list else None
    initial_router = router_list[0] if router_list else args.router_num
    ctrl = get_network_controller(mode=args.net_mode, router_num=initial_router)
    ctrl.setup()

    # 6) 외부 공인 IP 단독 확인 (--ip-only)
    if args.ip_only:
        ctrl.setup()
        curr_ip = ctrl.get_public_ip(sample_device=sample_dev)
        mode_desc = 'PC 메인 유선 이더넷(enp42s0)' if args.net_mode == 'local' else ('LTE 동글' if args.net_mode == 'lte' else f'MikroTik Node-{initial_router}')
        print(f"🌐 [실측 공인 IP] 모드: {args.net_mode.upper()} ({mode_desc}) | IP: {curr_ip}")
        return

    client = CentralApiClient(CENTRAL_API_BASE)

    # 7) 모의 실행 검증 (--dry-run)
    if args.dry_run:
        print("🔍 [DRY-RUN 모드: 실제 단말기 클릭 없이 네트워크 및 작업 할당 계획 검증]")
        ctrl.setup()
        ctrl.connect_devices(target_devices)
        curr_ip = ctrl.get_public_ip(sample_device=sample_dev, max_retries=3)
        print(f"🌐 [실측 공인 IP]: {curr_ip} (모드: {args.net_mode.upper()})")
        tasks = build_cycle_tasks(target_devices, curr_ip, 1, args, client)
        print(f"\n📋 [총 {len(tasks)}개 작업 할당 계획표]:")
        for t in tasks:
            rank_str = f" | rank={t['target_rank']}위" if t.get('target_rank') is not None else ""
            mid_str = f" | nv_mid={t['nv_mid']}" if t.get('nv_mid') else ""
            print(f"  • [{t['device_id']}] TaskID={t['task_id']} | 키워드='{t['keyword']}'{rank_str}{mid_str} | 체류={t.get('dwell_seconds')}s")
        print("\n✅ DRY-RUN 정상 완료: 실제 타격을 수행하지 않고 종료합니다.")
        return

    # --------------------------------------------------------------------------
    # 러너 기동 안내 배너
    # --------------------------------------------------------------------------
    print("=" * 95)
    print("🚀 [N-Shop Macro V1 Master Unified Runner 가동]")
    r_info = f"MikroTik Node-순환({','.join(router_list)})" if router_list else f"MikroTik Node-{args.router_num}"
    mode_label = 'PC 메인 유선 이더넷(enp42s0 고정 IP)' if args.net_mode == 'local' else ('화웨이 LTE 동글' if args.net_mode == 'lte' else r_info)
    print(f"   • 네트워크 모드   : {args.net_mode.upper()} ({mode_label})")
    print(f"   • 투입 단말기 수 : {len(target_devices)}대 ({', '.join(target_devices[:5])}{'...' if len(target_devices) > 5 else ''})")
    print(f"   • 종료 목표 조건 : {'단 1회 즉시 실행 (--once)' if args.cycles == 1 else (f'목표 시각: {args.until}' if args.until else (f'{args.cycles}회 반복 실행' if args.cycles else '무한 연속 순환 (사용자 중단 명령 전까지 구동)'))}")
    print(f"   • 종합 평가 주기 : 매 {args.eval_interval}회차마다 순위 변동 및 FDS 무결성 자동 평가 리포트 생성")
    if args.keyword or args.nvmid or args.store:
        print(f"   • 타겟 오버라이딩 : 키워드='{args.keyword or '(API)'}' | nv_mid='{args.nvmid or '(API)'}' | 몰='{args.store or '(API)'}'")
    print(f"   • 핵심 안전장치   : 기기당 {args.timeout}s 하드 타임아웃 / 회차당 최소 {args.min_cycle_dur}s 완충 보장")
    print("=" * 95)

    # 0. 시스템 시작 단말기 환경 무결성 진단 & 베이스라인 자동 동기화 (최초 1회 필수 실행)
    from src.device.device_health_checker import run_fleet_health_check
    run_fleet_health_check(target_devices)

    # 1. 네트워크 컨트롤러 환경 초기화
    ctrl.setup()

    all_cycles_summary = []
    t_bench_start = time.time()
    cycle = 0
    failure_counts, quarantined_mids = load_recent_failure_history(LOGS_DIR, args.net_mode, lookback_cycles=30)
    if quarantined_mids:
        print(f"📋 [이전 이력 기반 격리 복원] 누적 3회 실패(일반) 및 1회 실패(카탈로그) 상품 총 {len(quarantined_mids)}건 배제 목록 초기 등록")

    from src.monitor.cycle_batch_evaluator import get_historical_baselines
    yesterday_baselines = get_historical_baselines()
    if yesterday_baselines:
        print(f"📊 [어제 순위 베이스라인 로드] 총 {len(yesterday_baselines)}개 상품의 어제 순위 데이터 매칭 준비 완료")

    daily_success_counts = load_today_product_success_counts(LOGS_DIR)
    max_hits_cap = getattr(args, "max_hits_per_item", 100)
    capped_today_mids = {mid for mid, count in daily_success_counts.items() if count >= max_hits_cap}
    if daily_success_counts:
        print(f"📊 [당일 누적 유효타 현황] 총 {len(daily_success_counts)}개 상품 활성 타격 중 (상품당 일일 {max_hits_cap}타 상한 캡 적용)")
        if capped_today_mids:
            print(f"🎯 [일일 {max_hits_cap}타 상한 달성 상품] 총 {len(capped_today_mids)}개 상품 오늘 목표 완료 -> 타격 제외 목록 등록")

    try:
        while True:
            # 종료 조건 1: --until 시각 도달 검사
            if is_until_reached(args.until, start_time=t_bench_start):
                print(f"\n⏰ [목표 시각 도달] 지정 시각({args.until})에 도달하여 안전하게 작업을 마감합니다.")
                break

            # 종료 조건 2: --cycles 완료 검사
            if args.cycles is not None and cycle >= args.cycles:
                print(f"\n🏁 [지정 회차 완료] 총 {args.cycles}회 실행 목표를 달성하여 마감합니다.")
                break

            cycle += 1
            cycle_ymd = time.strftime("%Y%m%d")
            cycle_his = time.strftime("%H%M%S")

            # 2시간(7200초) 이상 경과한 격리 상품 자동 해제 (재검증 기회 부여)
            now_ts = time.time()
            quarantined_mids = {mid: ts for mid, ts in quarantined_mids.items() if (now_ts - ts) < 7200}

            if args.net_mode == "wg" and router_list:
                current_router = router_list[(cycle - 1) % len(router_list)]
                ctrl = get_network_controller(mode="wg", router_num=current_router)
                ctrl.setup()
                router_tag = f"Node-{current_router}"
            elif args.net_mode == "wg":
                router_tag = f"Node-{args.router_num}"
            elif args.net_mode == "local":
                router_tag = "LocalEth"
            else:
                router_tag = "LTE"

            cyc_title = f"CYCLE {cycle:02d}" + (f"/{args.cycles:02d}" if args.cycles else "")
            print("\n" + "#" * 95)
            print(f"🔄 [{cyc_title}] 시작 ({time.strftime('%H:%M:%S')}) [저장소: logs/traffic/{cycle_ymd}/{cycle_his}/<device>/] - 통신망: {args.net_mode.upper()} ({router_tag})")
            if quarantined_mids:
                print(f"🚫 [미노출 상품 격리 가동 중] 현재 {len(quarantined_mids)}개 상품(NOT_FOUND) 배제 -> DB 다른 랜덤 활성 상품 할당 요청")
            print("#" * 95)
            t_cycle_start = time.time()

            # 2. 단말기 USB 중계 터널 및 클라이언트 일괄 기동
            ctrl.connect_devices(target_devices)

            # 3. 실측 공인 IP 확인 및 단말기-호스트 네이버 통신망 2중 개통 검증 게이트
            sample_dev = target_devices[0] if target_devices else None
            gate_passed = False
            current_ip = "UNKNOWN"
            naver_conn = {"success": False}

            for gate_try in range(1, 4):
                current_ip = ctrl.get_public_ip(sample_device=sample_dev, max_retries=6)
                naver_conn = ctrl.verify_naver_connectivity(sample_device=sample_dev, max_retries=TIMINGS.NAVER_CONNECT_MAX_RETRIES)
                if naver_conn.get("success") and current_ip != "UNKNOWN":
                    gate_passed = True
                    break
                print(f"⚠️ [통신망 미개통 경고] IP={current_ip}, Naver={naver_conn.get('success')} (시도 {gate_try}/3) -> 망 안정화 5초 대기...")
                time.sleep(5.0)
                if args.net_mode in ("lte", "local"):
                    # Gnirehtet 터널 재동기화
                    ctrl.connect_devices(target_devices)

            if not gate_passed:
                print("🚨 [통신망 개통 실패] 네이버 서버 통신이 연결되지 않았습니다. 단말기 보호를 위해 이번 회차를 안전하게 건너뜁니다.")
                if args.net_mode == "lte" and not args.no_toggle:
                    ctrl.toggle_ip(cycle=cycle)
                continue

            print(f"🌐 [1단계: 실측 공인 IP]: {current_ip}")
            dev_probe_info = f" | 단말기={sample_dev}(NNB:{naver_conn.get('dev_nnb')})" if sample_dev else ""
            print(f"   ↳ ✅ [네이버망 개통 검증 완료] HTTP {naver_conn['status_code']} | NNB={naver_conn['nnb']}{dev_probe_info} 발급 확인 (소요: {naver_conn['dur_sec']}s)")

            # 4. 화면 언락 및 대기
            if not args.no_wake:
                wake_devices_parallel(target_devices)

            # [사용자 지침] 4시간 쿨타임 만료 상품 격리 자동 해제 (순위 변화 재확인 게이트)
            now_ts = time.time()
            active_quarantined_mids = set()
            expired_quarantine = []
            for mid, q_ts in list(quarantined_mids.items()):
                if now_ts - q_ts < 4 * 3600:
                    active_quarantined_mids.add(mid)
                else:
                    expired_quarantine.append(mid)
                    quarantined_mids.pop(mid, None)
                    failure_counts[mid] = 0

            if expired_quarantine:
                print(f"⏰ [4시간 쿨타임 만료 재점검] {len(expired_quarantine)}개 상품 4시간 경과 -> 순위 변화 재확인 풀로 자동 복귀")

            # [Top 10 졸업 및 영구 제외 상품 로드]
            graduated_file = CONFIG_DIR / "graduated_mids.json"
            if graduated_file.exists():
                try:
                    with open(graduated_file, "r", encoding="utf-8") as gf:
                        g_data = json.load(gf)
                        g_mids = set(str(m).strip() for m in g_data.get("graduated_mids", []) if str(m).strip())
                        active_quarantined_mids.update(g_mids)
                except Exception:
                    pass

            if getattr(args, "exclude_mids", None):
                for em in args.exclude_mids.split(","):
                    if em.strip():
                        active_quarantined_mids.add(em.strip())

            # [20대 전원 동시 타격 보장 안전 캡]
            # 격리 목록이 너무 많아 20대 단말기가 NO_TASK로 쉬는 사태 원천 차단
            # 가용 상품 풀(50개) 중 최소 40개 이상이 항상 열려있도록 격리 상한선을 최대 10개로 제한
            if len(active_quarantined_mids) > 10:
                print(f"🛡️ [상품 풀 고갈 방지 안전 캡] 격리 목록 {len(active_quarantined_mids)}건 중 최근 10건만 유지하고 나머지는 20대 전원 동시 가동을 위해 풀로 복귀")
                sorted_by_recent = sorted(active_quarantined_mids, key=lambda m: quarantined_mids.get(m, 0), reverse=True)
                active_quarantined_mids = set(sorted_by_recent[:10])

            # [당일 100타 상한 캡 적용 - 100타 완료 상품은 오늘 타격 영구 제외 (오버플로 방지)]
            capped_today_mids = {mid for mid, count in daily_success_counts.items() if count >= max_hits_cap}
            if capped_today_mids:
                active_quarantined_mids.update(capped_today_mids)

            # [사용자 지침 2026-10-19] 통합검색 상위 노출 상품 영구 제외 (업체 유료광고/외부트래픽 간섭 방지)
            SERP_TOP_EXCLUDED_MIDS = {
                "90881889708",  # 해바라기 샤워기 (대림바스 온라인 스토어) - SERP 15위 노출
                "89392774174",  # 메모리폼매트리스 (밤이오면) - SERP 14위 노출
            }
            active_quarantined_mids.update(SERP_TOP_EXCLUDED_MIDS)

            # 5. 회차별 작업 생성 (API 수신 or CLI 오버라이딩, 4시간 쿨다운 중인 상품 배제)
            prepared_tasks = build_cycle_tasks(
                target_devices, current_ip, cycle, args, client,
                cycle_ymd=cycle_ymd, cycle_his=cycle_his,
                exclude_mids=active_quarantined_mids
            )
            print(f"📦 [2단계: 작업 {len(prepared_tasks)}건 준비 완료] (오버라이딩: {'적용' if (args.keyword or args.nvmid) else 'API 기본'})")
            FleetStateManager.update_global(
                cycle=cycle,
                ip=current_ip,
                net_mode=args.net_mode,
                status="RUNNING" if prepared_tasks else "COOLDOWN_WAIT",
                status_detail=f"{len(prepared_tasks)}대 타격 진행 중" if prepared_tasks else "스토어 쿨다운 대기 (작업 0건)",
                cooldown_remaining_sec=0 if prepared_tasks else 60,
                cooldown_reason="" if prepared_tasks else "스토어 쿨다운 준수 (정상 동작)"
            )

            # 6. 완전 병렬 멀티프로세스 기동 (PID 독립 분리)
            cycle_results = []
            if not prepared_tasks:
                print("💤 [3단계: 작업 건수 0건] 중앙 API 할당 작업이 없어(스토어 쿨다운 대기) 단말기를 안전 유휴 상태로 유지합니다.")
                if getattr(args, "harvest_major", False):
                    print("🏁 [50대 대표 키워드 전수 수집 완료] 사이클을 종료하고 추출 단계로 전환합니다.")
                    break
                # 당일 100타 상한 달성으로 모든 등록 상품이 완료되었는지 판정
                if capped_today_mids and len(daily_success_counts) >= 10:
                    remaining_pool = [m for m, cnt in daily_success_counts.items() if cnt < max_hits_cap]
                    if not remaining_pool:
                        print(f"\n🎉 [당일 전 상품 {max_hits_cap}타 완료] 오늘 목표 작업량(각 100회)이 모두 소화되어 안전하게 작업을 마감합니다.")
                        break
            else:
                print(f"⚡ [3단계: {len(prepared_tasks)}대 완전 병렬 타격 기동 (PID {len(prepared_tasks)}개 분리)]...")
                stagger_gap = 0.5 if args.net_mode == "local" else 1.2
                import multiprocessing as mp
                mp_context = mp.get_context("spawn")
                with concurrent.futures.ProcessPoolExecutor(max_workers=len(prepared_tasks), mp_context=mp_context) as executor:
                    futures = {
                        executor.submit(worker_process_entry, task_dict, CENTRAL_API_BASE, idx * stagger_gap, args.timeout): task_dict["device_id"]
                        for idx, task_dict in enumerate(prepared_tasks)
                    }
                    for fut in concurrent.futures.as_completed(futures):
                        dev = futures[fut]
                        try:
                            res = fut.result()
                            cycle_results.append(res)
                        except Exception as e:
                            cycle_results.append({"device_id": dev, "status": "CRASH", "error_message": str(e), "duration_seconds": 0})

            # [사용자 지침 2026-10-14] 미노출 상품 차등 교체/격리 알고리즘:
            # - 판매처 묶음 상품 (카탈로그 / compare_id): 1회 실패 시 즉시 게시물 교체
            # - 일반 단독 상품: 3회 누적 실패 시 게시물 교체
            # - 성공 시: 실패 카운트 리셋 및 격리 해제
            newly_quarantined_cat = 0
            newly_quarantined_gen = 0
            for r in cycle_results:
                nv_mid = str(r.get("nv_mid") or "")
                if not nv_mid:
                    continue
                st = r.get("status")
                kw = r.get("keyword") or "-"
                is_cat = bool(r.get("compare_id") or r.get("is_catalog") or r.get("target_type") == "CATALOG" or r.get("card_type") == "CATALOG_CARD")

                if st == "SUCCESS":
                    failure_counts[nv_mid] = 0
                    if nv_mid in quarantined_mids:
                        quarantined_mids.pop(nv_mid, None)
                    daily_success_counts[nv_mid] += 1
                    cur_hits = daily_success_counts[nv_mid]
                    if cur_hits >= max_hits_cap:
                        print(f"🎯 [일일 {max_hits_cap}타 상한 달성] '{kw}' (MID: {nv_mid}) 오늘 누적 {cur_hits}회 유효타 완료 -> 오늘 타격 제외 (오버플로 방지)")
                elif st in ("NOT_FOUND", "NOT_SHOPPING_KEYWORD") or (str(st).startswith("NOT_FOUND")):
                    # [오직 순수 40위 밖 미노출만 상품 쿨다운] CLICK_MISSED, TIMEOUT 등 단말기 오류로 멀쩡한 상품을 격리하지 않음
                    if is_cat:
                        if nv_mid not in quarantined_mids:
                            quarantined_mids[nv_mid] = time.time()
                            newly_quarantined_cat += 1
                            print(f"⏳ [판매처 묶음 1회 미노출 4시간 쿨다운] '{kw}' (MID: {nv_mid}) 미노출 -> 4시간 후 순위 변화 재확인 예정")
                    else:
                        failure_counts[nv_mid] += 1
                        if failure_counts[nv_mid] >= 3:
                            if nv_mid not in quarantined_mids:
                                quarantined_mids[nv_mid] = time.time()
                                newly_quarantined_gen += 1
                                print(f"⏳ [일반 상품 3회 누적 미노출 4시간 쿨다운] '{kw}' (MID: {nv_mid}) {failure_counts[nv_mid]}회 미노출 -> 4시간 후 순위 변화 재확인 예정")
                        else:
                            print(f"⏳ [일반 상품 미노출 재시도 ({failure_counts[nv_mid]}/3회)] '{kw}' (MID: {nv_mid}) -> 3회 누적 실패 시 4시간 쿨다운 예정")

            total_new_quarantine = newly_quarantined_cat + newly_quarantined_gen
            if total_new_quarantine > 0:
                print(f"⏳ [미노출 상품 4시간 쿨다운 갱신] 신규 {total_new_quarantine}건 쿨다운 등록 (현재 쿨다운: {len(quarantined_mids)}건, 4시간 후 자동 해제 및 순위 재확인)")

            cycle_dur = round(time.time() - t_cycle_start, 2)
            success_cnt = sum(1 for r in cycle_results if r.get("status") == "SUCCESS")
            fail_cnt = len(cycle_results) - success_cnt
            avg_dur = round(sum(r.get("duration_seconds", 0) for r in cycle_results) / len(cycle_results), 1) if cycle_results else 0

            cycle_stat = {
                "cycle": cycle,
                "ip": current_ip,
                "cycle_dur": cycle_dur,
                "avg_dur": avg_dur,
                "total": len(cycle_results),
                "success": success_cnt,
                "fail": fail_cnt,
                "success_rate": round(success_cnt / len(cycle_results) * 100, 1),
                "results": cycle_results
            }
            all_cycles_summary.append(cycle_stat)

            # [사용자 지침 필수] logs/{net_mode}/{Ymd}/{His}/ 디렉토리에 회차 실행 결과 즉시 보존
            cycle_log_dir = LOGS_DIR / args.net_mode / cycle_ymd / cycle_his
            cycle_log_dir.mkdir(parents=True, exist_ok=True)
            cycle_log_path = cycle_log_dir / f"run_{args.net_mode}_{cycle_ymd}_{cycle_his}.json"
            with open(cycle_log_path, "w", encoding="utf-8") as f:
                json.dump(cycle_stat, f, ensure_ascii=False, indent=2)

            cycle_txt_path = cycle_log_dir / f"run_{args.net_mode}_{cycle_ymd}_{cycle_his}.txt"

            summary_lines = []
            summary_lines.append(f"📊 [{cyc_title} 마감] 소요: {cycle_dur}s | 성공: {success_cnt}/{len(cycle_results)} ({cycle_stat['success_rate']}%) | 평균: {avg_dur}s | IP: {current_ip}")
            summary_lines.append(f"   ↳ 📁 회차 결과 JSON: {cycle_log_path}")
            summary_lines.append(f"   ↳ 📁 회차 결과 텍스트: {cycle_txt_path}")
            pure_cnt = sum(1 for r in cycle_results if r.get("login_handling_type") == "PURE_ORGANIC" and not r.get("login_detected"))
            challenge_cnt = sum(1 for r in cycle_results if r.get("login_handling_type") == "LOGIN_CHALLENGE_DETECTED" or r.get("login_detected"))
            summary_lines.append(f"   ↳ 🛡️ [로그인 검증]: 순수 정상(PURE): {pure_cnt}건 | 🚨 FDS 챌린지 감지(CHALLENGE): {challenge_cnt}건")
            summary_lines.append(f"   ↳ 📁 개별 단말기 실행/트래픽 로그: logs/traffic/{cycle_ymd}/{cycle_his}/")
            summary_lines.append(f"\n   📋 [{cyc_title} 개별 단말기 실행 상세표 (JS사전탐색 · 로그인유형 · 클릭결과)]")

            tbl_headers = [
                ('단말기 ID', 12),
                ('상태', 10),
                ('로그인유형', 10),
                ('체인', 6),
                ('JS사전탐색', 12),
                ('스크롤', 6),
                ('클릭', 6),
                ('최종순위', 12),
                ('어제비교', 16),
                ('소요', 6),
                ('몰 이름', 12),
                ('키워드', 16)
            ]
            tbl_top = '   ┌' + '┬'.join('─' * (w + 2) for _, w in tbl_headers) + '┐'
            tbl_mid = '   ├' + '┼'.join('─' * (w + 2) for _, w in tbl_headers) + '┤'
            tbl_bot = '   └' + '┴'.join('─' * (w + 2) for _, w in tbl_headers) + '┘'

            summary_lines.append(tbl_top)
            summary_lines.append('   │ ' + ' │ '.join(pad_str(h, w, 'left') for h, w in tbl_headers) + ' │')
            summary_lines.append(tbl_mid)
            for r in sorted(cycle_results, key=lambda x: str(x.get('device_id'))):
                d_id = r.get("device_id", "-")
                d_st = r.get("status", "-")
                d_dur = f"{r.get('duration_seconds', 0):.1f}s"

                # 0) 체인 Hop 정보
                hop_cur = r.get("hop_count", 1)
                hop_tot = r.get("total_hops", 1)
                d_hop = f"H{hop_cur}/{hop_tot}"

                # 1) JS 사전 탐색 결과 (SERP vs 쇼핑탭 출처 명확히 표기)
                stype = r.get("js_search_type", "")
                rk = r.get("js_target_rank")
                cnt = r.get("js_total_count")
                if r.get("js_target_found"):
                    if stype == "SHOPPING":
                        d_js = f"쇼핑 {rk}위"
                    elif stype == "SERP":
                        d_js = f"SERP {rk}위"
                    else:
                        d_js = f"발견({rk}위)"
                elif cnt:
                    if stype == "SHOPPING":
                        d_js = f"쇼핑 무({cnt})"
                    elif stype == "SERP":
                        d_js = f"SERP 무({cnt})"
                    else:
                        d_js = f"미존재({cnt}개)"
                else:
                    d_js = "-"

                # 2) 실제 스크롤 횟수
                sc = r.get("scroll_count", 0)
                d_scroll = f"{sc}회" if sc > 0 else "-"

                # 3) 실제 클릭 성공유무
                if r.get("click_success"):
                    d_click = "성공"
                elif r.get("click_fail_reason"):
                    d_click = "실패"
                else:
                    d_click = "-"

                d_stype = r.get("search_type") or ("m.search" if (r.get("match_type") == "SERP" or r.get("serp_rank")) else ("msearch" if r.get("shopping_rank") else "-"))
                if d_stype == "m.search":
                    d_rk_str = f"SERP {r.get('serp_rank')}위" if r.get('serp_rank') is not None else "SERP"
                elif d_stype == "msearch":
                    shp_r = r.get('shopping_rank')
                    shp_p = r.get('shopping_page') or 1
                    d_rk_str = f"쇼핑 {shp_p}P {shp_r}위" if shp_r is not None else "쇼핑탭"
                else:
                    d_rk_str = "-"

                # 4) 어제 대비 순위 변동 계산
                mid = str(r.get("nv_mid") or "")
                d_delta = "-"
                base = yesterday_baselines.get(mid) if 'yesterday_baselines' in locals() and yesterday_baselines else None
                if base:
                    b_serp = min(base["serp"]) if base.get("serp") else None
                    b_shop = min(base["shop"]) if base.get("shop") else None
                    cur_serp = r.get("serp_rank")
                    cur_shop = r.get("shopping_rank")
                    if b_serp and cur_serp:
                        diff = b_serp - cur_serp
                        d_delta = f"🔺+{diff} ({b_serp}위)" if diff > 0 else (f"🔻{diff} ({b_serp}위)" if diff < 0 else f"동일 ({cur_serp}위)")
                    elif b_shop and cur_shop:
                        diff = b_shop - cur_shop
                        d_delta = f"🔺+{diff} ({b_shop}위)" if diff > 0 else (f"🔻{diff} ({b_shop}위)" if diff < 0 else f"동일 ({cur_shop}위)")
                    elif not b_serp and cur_serp:
                        d_delta = f"🚀SERP진입"
                    elif b_serp and not cur_serp and cur_shop:
                        d_delta = f"쇼핑탭이동"
                    elif (b_serp or b_shop) and d_st != "SUCCESS":
                        y_r = f"{b_serp}위" if b_serp else f"{b_shop}위"
                        d_delta = f"🔻미노출({y_r})"
                elif mid:
                    d_delta = "신규"

                d_kw = r.get("keyword") or "-"
                d_mall = r.get("store_name") or "-"

                # 5) 로그인 상태 구분 (순수 정상 vs 강제 제거 vs 로그인 발생)
                login_type = r.get("login_handling_type", "PURE_ORGANIC")
                if login_type == "FORCED_BYPASS":
                    d_login = "⚠️강제제거"
                elif login_type == "LOGIN_CHALLENGE_DETECTED":
                    d_login = "🚨로그인발생"
                elif r.get("login_detected"):
                    d_login = "⚠️로그인감지"
                else:
                    d_login = "순수정상"

                row_vals = [(d_id, 12), (d_st, 10), (d_login, 10), (d_hop, 6), (d_js, 12), (d_scroll, 6), (d_click, 6), (d_rk_str, 12), (d_delta, 16), (d_dur, 6), (d_mall, 12), (d_kw, 16)]
                summary_lines.append('   │ ' + ' │ '.join(pad_str(v, w, 'left') for v, w in row_vals) + ' │')
            summary_lines.append(tbl_bot + "\n")

            full_summary_text = "\n".join(summary_lines)
            print(full_summary_text)

            try:
                with open(cycle_txt_path, "w", encoding="utf-8") as f:
                    f.write(full_summary_text)
            except Exception:
                pass

            # [사용자 지침] 50회 구동 단위 종합 평가 리포트 자동 생성 및 출력
            if args.eval_interval > 0 and cycle % args.eval_interval == 0:
                try:
                    from src.monitor.cycle_batch_evaluator import evaluate_batch, generate_evaluation_report
                    last_eval_cycles = all_cycles_summary[-args.eval_interval:]
                    eval_payload = {
                        "mode": args.net_mode,
                        "total_cycles": len(last_eval_cycles),
                        "cycles": last_eval_cycles
                    }
                    eval_res = evaluate_batch(eval_payload)
                    eval_report_txt = generate_evaluation_report(eval_res)
                    print("\n" + "#" * 95)
                    print(f"🎯 [마일스톤: Cycle #{cycle} ({args.eval_interval}회 단위 종합 평가 & 순위 추적 리포트)]")
                    print("#" * 95)
                    print(eval_report_txt)
                    print("#" * 95 + "\n")

                    eval_report_path = cycle_log_dir / f"eval_report_{args.eval_interval}cycle_{cycle_ymd}_{cycle_his}_c{cycle}.txt"
                    with open(eval_report_path, "w", encoding="utf-8") as f_rep:
                        f_rep.write(eval_report_txt)
                    with open(LOGS_DIR / "latest_eval_report.txt", "w", encoding="utf-8") as f_latest:
                        f_latest.write(eval_report_txt)
                    with open(LOGS_DIR / "latest_eval_report.json", "w", encoding="utf-8") as f_latest_json:
                        json.dump(eval_res, f_latest_json, ensure_ascii=False, indent=2)
                    print(f"   ↳ 📁 {args.eval_interval}회 마일스톤 종합 평가 리포트 보존: {eval_report_path}\n")
                except Exception as e:
                    print(f"⚠️ [{args.eval_interval}회 종합 평가 리포트 생성 예외] {e}")

                # 24시간 경과 미사용 임시 로그/캡처 자동 안전 정제 (디스크 폭주 방지)
                try:
                    from scripts.cleanup_unused_logs_24h import run_cleanup
                    run_cleanup(dry_run=False, hours=24.0)
                except Exception as clean_err:
                    print(f"⚠️ [로그 자동 정제 예외] {clean_err}")

            # 다음 회차 진행 여부 검사
            next_needed = True
            if is_until_reached(args.until, start_time=t_bench_start):
                next_needed = False
            if args.cycles is not None and cycle >= args.cycles:
                next_needed = False

            # 7. [최소 완충 시간 보장 - 설정 시에만 대기]
            if next_needed and args.min_cycle_dur > 0:
                elapsed_since_start = time.time() - t_cycle_start
                if elapsed_since_start < args.min_cycle_dur:
                    wait_buffer = round(args.min_cycle_dur - elapsed_since_start, 1)
                    print(f"⏳ [토글 안정성 보장] 타격 완료 ({elapsed_since_start:.1f}s 경과) -> 망 안정화 및 FDS 방지를 위해 {args.min_cycle_dur}초 완충 대기 ({wait_buffer}s 추가 대기)...")
                    time.sleep(wait_buffer)

            # 8. 다음 회차 준비용 공인 IP 토글
            if next_needed and not args.no_toggle:
                print(f"\n🔄 [4단계: {args.net_mode.upper()} 공인 IP 즉시 토글 및 통신 정상화 대기]...")
                FleetStateManager.update_global(
                    status="IP_ROTATING",
                    status_detail=f"{args.net_mode.upper()} 공인 IP 고속 토글 및 통신 개통 검증 중",
                    cooldown_remaining_sec=15,
                    cooldown_reason="공인 IP 변경 및 네이버 개통 검증"
                )
                t_toggle = ctrl.toggle_ip(cycle=cycle)
                toggle_ok = t_toggle.get("success", False)
                old_ip = t_toggle.get("old_ip")
                new_ip = t_toggle.get("new_ip")
                t_dur = t_toggle.get("duration_sec", 0)

                if toggle_ok:
                    print(f"   ↳ ✅ 토글 성공: {old_ip} -> {new_ip} (소요: {t_dur}s)")
                else:
                    print(f"   ⚠️ 토글 경고: {old_ip} -> {new_ip} (소요: {t_dur}s)")

                # LTE 모뎀 실측 트래픽(Upload / Download) 출력
                if args.net_mode == "lte":
                    from src.device.huawei_dongle_controller import format_bytes
                    s_up = format_bytes(t_toggle.get("session_upload_bytes", 0))
                    s_down = format_bytes(t_toggle.get("session_download_bytes", 0))
                    tot_up = format_bytes(t_toggle.get("total_upload_bytes", 0))
                    tot_down = format_bytes(t_toggle.get("total_download_bytes", 0))
                    print(f"   ↳ 📊 [LTE 모뎀 트래픽 실측] Cycle #{cycle:02d} 세션 사용량: ↑ {s_up} / ↓ {s_down} | 누적 총량: ↑ {tot_up} / ↓ {tot_down}")

                verified_ip = ctrl.get_public_ip(sample_device=sample_dev, max_retries=6)
                print(f"   ↳ 통신 정상화 확인 실측 IP = {verified_ip}")

                # [사용자 지침 필수] lcs.naver.com/m 접근 및 NNB 쿠키 정상 발급 실측 검증
                print(f"   ↳ 🌐 [네이버망 개통 검증] {ctrl.interface_name} & 단말기({sample_dev or 'N/A'}) -> https://lcs.naver.com/m NNB 발급 확인...")
                naver_conn = ctrl.verify_naver_connectivity(sample_device=sample_dev, max_retries=TIMINGS.NAVER_CONNECT_MAX_RETRIES)
                if naver_conn.get("success"):
                    dev_info = f" | 단말기={sample_dev}(NNB:{naver_conn.get('dev_nnb')})" if sample_dev else ""
                    print(f"   ↳ ✅ [네이버망 개통 검증 완료] HTTP {naver_conn['status_code']} | NNB={naver_conn['nnb']}{dev_info} 발급 확인 (소요: {naver_conn['dur_sec']}s)")
                else:
                    print(f"   ↳ ⚠️ [네이버망 개통 경고] lcs.naver.com 응답 지연")

                print(f"   ↳ ⏳ 통신 안정화 대기 ({args.interval}s)...")
                FleetStateManager.update_global(
                    ip=verified_ip,
                    status="COOLDOWN_WAIT",
                    status_detail="회차 간 안전 대기",
                    cooldown_remaining_sec=int(args.interval),
                    cooldown_reason=f"망 안정화 완충 대기 ({args.interval}s)"
                )
                time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n\n🛑 [사용자 중단] Ctrl+C 입력으로 안전하게 종료합니다.")

    # --------------------------------------------------------------------------
    # 9. 최종 종합 리포트 출력
    # --------------------------------------------------------------------------
    total_bench_dur = round(time.time() - t_bench_start, 2)
    total_tasks = sum(c["total"] for c in all_cycles_summary)
    total_success = sum(c["success"] for c in all_cycles_summary)
    overall_rate = round(total_success / total_tasks * 100, 1) if total_tasks else 0
    unique_ips = list(dict.fromkeys(c["ip"] for c in all_cycles_summary if c["ip"] != "UNKNOWN"))

    print("\n" + "=" * 95)
    print(f"🏆 [N-Shop Macro V1 최종 종합 리포트]")
    print("=" * 95)
    final_mode_desc = 'PC 메인 유선 이더넷 (enp42s0)' if args.net_mode == 'local' else ('LTE Dongle' if args.net_mode == 'lte' else f'MikroTik Node-{args.router_num}')
    print(f"• 네트워크 모드   : {args.net_mode.upper()} ({final_mode_desc})")
    print(f"• 총 소요 시간   : {total_bench_dur}초 ({total_bench_dur/60:.1f}분)")
    print(f"• 총 실행 타수   : {total_tasks}타")
    print(f"• 전체 성공률    : {total_success}/{total_tasks} ({overall_rate}%)")
    print(f"• 획득 IP 목록   : {', '.join(unique_ips)}")
    print("-" * 95)
    print(f"{'회차':<6} | {'공인 IP':<17} | {'성공/총합':<10} | {'성공률':<8} | {'평균타격소요':<12} | {'사이클전체소요':<14}")
    print("-" * 95)

    for c in all_cycles_summary:
        print(f"#{c['cycle']:02d}    | {c['ip']:<17} | {c['success']}/{c['total']:<8} | {c['success_rate']}%   | {c['avg_dur']}s        | {c['cycle_dur']}s")

    print("=" * 95)

    ymd = time.strftime('%Y%m%d')
    his = time.strftime('%H%M%S')
    final_mode_dir = LOGS_DIR / args.net_mode / ymd / his
    final_mode_dir.mkdir(parents=True, exist_ok=True)
    result_path = final_mode_dir / f"run_{args.net_mode}_{ymd}_{his}.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({
            "mode": args.net_mode,
            "router_num": args.router_num,
            "total_cycles": len(all_cycles_summary),
            "total_tasks": total_tasks,
            "total_success": total_success,
            "overall_rate": overall_rate,
            "total_duration_seconds": total_bench_dur,
            "unique_ips": unique_ips,
            "cycles": all_cycles_summary
        }, f, ensure_ascii=False, indent=2)

    print(f"💾 종합 실행 결과 파일 저장 완료: {result_path}")

    # [수집 모드 자동 집계] 50대 대표 키워드 30~40위 순수 단일 상품 자동 추출 및 파일 보존
    if getattr(args, "harvest_major", False):
        try:
            from src.tools.extract_single_tail_products import extract_single_tail_products
            from src.tools.harvest_fleet_35 import MAJOR_ECOMMERCE_KEYWORDS_50
            targets = extract_single_tail_products(target_kws=MAJOR_ECOMMERCE_KEYWORDS_50)
            print("\n" + "=" * 105)
            print(f"🎉 [50대 대표 키워드 신규 기준 수집 완료] 50개 키워드 중 {len(targets)}개 30~40위 순수 단일 상품 확보")
            print(f"   • 단독 타겟 저장: logs/harvest/single_tail_targets_30_40.json")
            print("=" * 105)
            print(f"{'순위':<6} | {'키워드':<15} | {'MID':<13} | {'스토어/몰명':<16} | {'가격':>9}원 | 상품명")
            print("-" * 105)
            for c in targets:
                t_short = c['product_title'][:25] + ".." if len(c['product_title']) > 25 else c['product_title']
                print(f"{c['rank']:2d}위   | {c['keyword'][:14]:<15} | {c['nv_mid']:<13} | {c['mall_name'][:15]:<16} | {c['price']:>9,d}원 | {t_short}")
            print("=" * 105 + "\n")
        except Exception as e:
            print(f"⚠️ [수집 결과 자동 집계 예외] {e}")


if __name__ == "__main__":
    main()
