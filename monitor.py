#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor.py

20대 단말기 플릿 실시간 TUI 시각화 모니터 (Fleet Live Terminal Monitor)
----------------------------------------------------------------------
사용자가 터미널에서 실행하여 20대 디바이스의 키워드, 진행 단계, 쿨타임,
"가만히 있는 이유"를 실시간으로 한눈에 파악할 수 있는 대시보드.

실행법:
  python3 monitor.py
"""

import os
import sys
import time
import json
import unicodedata
from pathlib import Path
from typing import Dict, Any, List

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from src.monitor.fleet_state import FleetStateManager
from src.device.device_selector import get_online_devices

# ANSI Colors
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_RED = "\033[91m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_BLUE = "\033[94m"
C_MAGENTA = "\033[95m"
C_CYAN = "\033[96m"
C_WHITE = "\033[97m"
C_BG_BLUE = "\033[44m"
C_BG_DARK = "\033[40m"


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


def format_state(state: str) -> str:
    if state == "SUCCESS":
        return f"{C_GREEN}✅ 성공{C_RESET}"
    elif state in ("DWELL", "LANDING_DWELL"):
        return f"{C_CYAN}⏱️ 체류중{C_RESET}"
    elif state == "SERP_FOUND":
        return f"{C_YELLOW}🎯 타겟발견{C_RESET}"
    elif state == "SHOP_NAV":
        return f"{C_MAGENTA}🛒 쇼핑이동{C_RESET}"
    elif state == "SEARCHING":
        return f"{C_BLUE}🔍 검색중{C_RESET}"
    elif state == "LAUNCHING":
        return f"{C_YELLOW}🚀 기동중{C_RESET}"
    elif state == "STAGGER_WAIT":
        return f"{C_DIM}⏳ 시차대기{C_RESET}"
    elif state == "NO_TASK_COOLDOWN":
        return f"{C_DIM}💤 쿨타임{C_RESET}"
    elif state in ("NOT_FOUND", "SHOPPING_MORE_NOT_FOUND"):
        return f"{C_RED}❌ 미노출{C_RESET}"
    elif state == "LOGIN_REQUIRED":
        return f"{C_RED}🚨 로그인{C_RESET}"
    elif state == "NOT_SHOPPING_KEYWORD":
        return f"{C_YELLOW}⚠️ 비쇼핑{C_RESET}"
    elif state == "IDLE":
        return f"{C_DIM}⚪ 유휴{C_RESET}"
    else:
        return f"{C_WHITE}{state[:8]}{C_RESET}"


def render_dashboard():
    # 터미널 화면 클리어 & 커서 홈
    sys.stdout.write("\033[2J\033[H")

    snap = FleetStateManager.get_snapshot()
    g = snap.get("global", {})
    devs = snap.get("devices", {})

    cycle = g.get("cycle", 0)
    ip = g.get("ip", "-")
    net_mode = g.get("net_mode", "lte").upper()
    g_status = g.get("status", "IDLE")
    g_detail = g.get("status_detail", "대기 중")
    cd_sec = g.get("cooldown_remaining_sec", 0)
    cd_reason = g.get("cooldown_reason", "")
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    # 온라인 단말기 목록 확보
    try:
        online_devs = get_online_devices()
    except Exception:
        online_devs = list(devs.keys())
    if not online_devs and devs:
        online_devs = sorted(list(devs.keys()))

    # 상단 헤더
    print(f"{C_BOLD}{C_BG_BLUE}{C_WHITE} 🚀 [N-Shop Macro V1] 20대 단말기 실시간 플릿 관제 모니터 (Live Dashboard) {C_RESET}")
    print(f"{C_BOLD}• 현재 시각: {C_CYAN}{now_str}{C_RESET} | {C_BOLD}현재 회차: {C_GREEN}Cycle #{cycle:02d}{C_RESET} | {C_BOLD}공인 IP: {C_YELLOW}{ip}{C_RESET} ({net_mode}) | {C_BOLD}온라인 단말기: {C_GREEN}{len(online_devs)}대{C_RESET}")
    
    # 가만히 있는 이유 / 글로벌 상태 알림창
    if cd_sec > 0:
        cd_min = cd_sec // 60
        cd_rem = cd_sec % 60
        print(f"{C_BOLD}• 시스템 상태: {C_YELLOW}⏳ 쿨타임 대기 중 (남은 시간: {cd_min:02d}:{cd_rem:02d}){C_RESET} - 사유: {C_WHITE}{cd_reason or '스토어 쿨타임/네트워크 안전 완충'}{C_RESET}")
        print(f"  {C_DIM}↳ 💡 [안내] 비정상 멈춤이 아니며, FDS 탐지 방지를 위해 설계된 정상적인 안전 대기 시간입니다.{C_RESET}")
    else:
        print(f"{C_BOLD}• 시스템 상태: {C_GREEN}⚡ {g_status}{C_RESET} ({g_detail})")
    
    print("=" * 115)
    # 테이블 헤더
    h_no = pad_str("No", 3, "center")
    h_dev = pad_str("단말기 Serial", 13, "center")
    h_st = pad_str("상태", 10, "center")
    h_kw = pad_str("진행 키워드", 22, "left")
    h_store = pad_str("스토어 / 몰", 16, "left")
    h_prog = pad_str("현재 진행 단계 / 순위", 24, "left")
    h_dur = pad_str("시간", 7, "right")
    h_res = pad_str("최근결과", 10, "center")

    print(f"{C_BOLD}{h_no} │ {h_dev} │ {h_st} │ {h_kw} │ {h_store} │ {h_prog} │ {h_dur} │ {h_res}{C_RESET}")
    print("─" * 115)

    # 행 출력
    success_cnt = 0
    active_cnt = 0
    for idx, d_id in enumerate(online_devs, 1):
        info = devs.get(d_id, {})
        st = info.get("state", "IDLE")
        kw = info.get("keyword", "-")
        store = info.get("store_name", "-")
        prog = info.get("progress", info.get("status_msg", "-"))
        dur = info.get("elapsed_sec", 0.0)
        res = info.get("last_result", "-")

        if st in ("LAUNCHING", "SEARCHING", "SERP_FOUND", "SHOP_NAV", "DWELL", "LANDING_DWELL"):
            active_cnt += 1
        if res == "SUCCESS":
            success_cnt += 1

        c_no = pad_str(str(idx), 3, "center")
        c_dev = pad_str(d_id, 13, "left")
        c_st = pad_str(format_state(st), 10, "center")
        c_kw = pad_str(kw, 22, "left")
        c_store = pad_str(store, 16, "left")
        c_prog = pad_str(prog, 24, "left")
        c_dur = pad_str(f"{dur:.1f}s" if dur > 0 else "-", 7, "right")
        c_res = pad_str(res, 10, "center")

        print(f"{c_no} │ {C_CYAN}{c_dev}{C_RESET} │ {c_st} │ {C_WHITE}{c_kw}{C_RESET} │ {C_YELLOW}{c_store}{C_RESET} │ {c_prog} │ {c_dur} │ {c_res}")

    print("=" * 115)
    print(f"{C_BOLD}📊 [실시간 집계] 총 {len(online_devs)}대 중 활동 중: {C_GREEN}{active_cnt}대{C_RESET} | 회차 성공: {C_GREEN}{success_cnt}건{C_RESET} | {C_DIM}(1초마다 자동 갱신, 종료: Ctrl+C){C_RESET}")


def main():
    try:
        while True:
            render_dashboard()
            time.sleep(1.0)
    except KeyboardInterrupt:
        print(f"\n{C_YELLOW}모니터링을 종료합니다.{C_RESET}")


if __name__ == "__main__":
    main()
