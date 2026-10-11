#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/analysis/audit_telemetry_cookies.py

네이버 공식 앱(com.nhn.android.search) 내부의
모든 쿠키, 식별자, nlog/nlogapp 로깅 파라미터, SharedPreferences 전수 조사 스크립트.
"""

import sys
import os
import re
import json
import sqlite3
import zipfile
import subprocess
from pathlib import Path

DEV_ID = "R3CR70FFFEK"
PKG = "com.nhn.android.search"
APK_PATH = Path("apks/naver_app/base.apk")

def audit_xwhale_cookies():
    print("\n" + "=" * 80)
    print("1. [XWhale WebView SQLite 쿠키 전수 조사]")
    print("=" * 80)
    
    tmp_remote = "/data/local/tmp/c_audit.db"
    tmp_local = "/tmp/c_audit.db"
    subprocess.run(f"adb -s {DEV_ID} shell \"su -c 'cp /data/data/{PKG}/app_xwhale/Default/Cookies {tmp_remote} && chmod 666 {tmp_remote}'\"", shell=True, check=True)
    subprocess.run(f"adb -s {DEV_ID} pull {tmp_remote} {tmp_local} >/dev/null 2>&1", shell=True, check=True)

    conn = sqlite3.connect(tmp_local)
    c = conn.cursor()
    c.execute("SELECT host_key, name, value, path, is_secure, is_httponly, expires_utc FROM cookies ORDER BY host_key, name")
    rows = c.fetchall()
    conn.close()
    Path(tmp_local).unlink(missing_ok=True)

    cookie_catalog = []
    print(f" • 총 검출된 쿠키 수: {len(rows)}개\n")
    print(f"{'도메인 (host_key)':^30} | {'쿠키명 (name)':^22} | {'값 샘플 (value)':^38} | {'보안/HTTPOnly':^12}")
    print("-" * 110)
    for r in rows:
        dom, name, val, path, sec, http_only, exp = r
        val_sample = val if len(val) <= 36 else val[:33] + "..."
        flags = f"{'SEC' if sec else ''}/{'HTTP' if http_only else 'JS'}"
        print(f"{dom:30s} | {name:22s} | {val_sample:38s} | {flags:^12}")
        cookie_catalog.append({
            "domain": dom,
            "name": name,
            "value": val,
            "path": path,
            "is_secure": bool(sec),
            "is_httponly": bool(http_only),
            "expires_utc": exp
        })
    return cookie_catalog

def audit_shared_prefs():
    print("\n" + "=" * 80)
    print("2. [단말기 SharedPreferences 내 주요 식별자/트래커 전수 조사]")
    print("=" * 80)
    
    out = subprocess.run(f"adb -s {DEV_ID} shell \"su -c 'ls /data/data/{PKG}/shared_prefs/'\"", shell=True, capture_output=True, text=True).stdout
    files = [f.strip() for f in out.splitlines() if f.strip().endswith('.xml')]
    
    prefs_summary = {}
    for f in sorted(files):
        content = subprocess.run(f"adb -s {DEV_ID} shell \"su -c 'cat /data/data/{PKG}/shared_prefs/{f}'\"", shell=True, capture_output=True, text=True).stdout
        # 간단 파싱
        items = re.findall(r'<(string|boolean|int|long)\s+name="([^"]+)"(?:\s+value="([^"]+)")?>([^<]*)</', content)
        prefs_summary[f] = []
        for typ, k, v_attr, v_tag in items:
            val = v_attr if v_attr else v_tag
            prefs_summary[f].append((k, val))

    for fname, items in prefs_summary.items():
        if items and any(k for k, _ in items if any(term in k.lower() for term in ['id', 'nnb', 'time', 'user', 'track', 'device', 'key'])):
            print(f"\n 📁 [{fname}]")
            for k, v in items:
                v_short = v if len(v) <= 60 else v[:57] + "..."
                print(f"    • {k:35s} = {v_short}")

def audit_apk_telemetry():
    print("\n" + "=" * 80)
    print("3. [네이버 공식 APK DEX 역공학: nlogapp / DA_DD / DA_DV / Telemetry 분석]")
    print("=" * 80)

    with zipfile.ZipFile(APK_PATH, 'r') as z:
        dex_names = [n for n in z.namelist() if n.endswith('.dex')]
        all_dex = {d: z.read(d) for d in dex_names}

    # 1. nlogapp 엔드포인트 탐색
    nlogapp_matches = []
    for d, data in all_dex.items():
        for m in re.finditer(rb'/(nlogapp[^\x00"\']*)', data):
            nlogapp_matches.append((d, m.group(1).decode('utf-8', errors='ignore')))
    
    print("\n 🔍 [nlogapp 관련 내부 REST API 엔드포인트]")
    for d, ep in sorted(set(nlogapp_matches)):
        print(f"   • [{d}] /{ep}")

    # 2. DA_DD, DA_DV, da-dd, da-dv 탐색
    print("\n 🔍 [DA_DD / DA_DV / da-dd (Device Authentication / Display Ad) 정의]")
    for d, data in all_dex.items():
        for term in [b'DA_DD', b'DA_DV', b'da-dd', b'da-dv', b'NAPP_DI', b'NAC', b'NACT', b'BUC', b'SRT30', b'SRT5']:
            idx = 0
            while True:
                idx = data.find(term, idx)
                if idx == -1: break
                # 주변 60바이트
                snippet = data[max(0, idx-40): min(len(data), idx+60)]
                printable = ''.join(chr(b) if 32 <= b <= 126 else ' ' for b in snippet)
                # print first 2 occurrences of each
                # print(f"   [{d}] {term.decode()}: {printable.strip()}")
                idx += len(term)
                break

if __name__ == "__main__":
    audit_xwhale_cookies()
    audit_shared_prefs()
    audit_apk_telemetry()
