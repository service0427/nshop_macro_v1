#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/device/cookie_manager.py

Chromium/XWhale SQLite Cookies DB 조작 모듈
- 웜업으로 발생한 신생아 NNB/BUC 추출 (자가 충전용)
- 21분+ 숙성 NNB/BUC 주입 (치환)
- 파일 권한(chmod 600) 및 UID 소유권 보존
"""

import sqlite3
import hashlib
import uuid
import subprocess
from pathlib import Path
from typing import Tuple, Optional

from config.settings import NAVER_APP_PACKAGE, DEFAULT_DEVICE_ID
from src.device.adb_controller import run_adb_shell

def extract_newborn_and_inject_aged(
    device_id: str,
    aged_nnb: str,
    aged_buc: str = "",
    fresh_ssaid: Optional[str] = None,
    fresh_dadd: Optional[str] = None,
    fresh_dadv: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    1. 기기에서 최신 Cookies DB 추출
    2. 신생아 NNB/BUC 읽기 (자가 충전 풀 적재용)
    3. 숙성 NNB/BUC, SSAID(NAPP_DI), DA_DD(ADID), DA_DV(AppSetId) 동기화 교체
    4. 기기로 push 및 UID/권한 복구
    """
    pkg = NAVER_APP_PACKAGE
    cookie_db = f"/data/data/{pkg}/app_xwhale/Default/Cookies"
    tmp_device_cookie = f"/data/local/tmp/cookies_{device_id}.db"
    local_tmp_cookie = Path(f"/tmp/cookies_{device_id}.db")

    # 1. 단말기 내부에서 임시 디렉토리로 복사 후 권한 666
    run_adb_shell(device_id, f"su -c 'cp {cookie_db} {tmp_device_cookie} && chmod 666 {tmp_device_cookie}'")

    # 2. 로컬로 pull
    subprocess.run(["adb", "-s", device_id, "pull", tmp_device_cookie, str(local_tmp_cookie)], check=True, capture_output=True)

    # 3. SQLite 조작
    conn = sqlite3.connect(str(local_tmp_cookie))
    c = conn.cursor()

    # 3-1. 신생아 NNB/BUC 추출
    c.execute("SELECT value FROM cookies WHERE name = 'NNB'")
    newborn_nnb_row = c.fetchone()
    newborn_nnb = newborn_nnb_row[0] if newborn_nnb_row else None

    c.execute("SELECT value FROM cookies WHERE name = 'BUC'")
    newborn_buc_row = c.fetchone()
    newborn_buc = newborn_buc_row[0] if newborn_buc_row else ""

    # 3-2. 숙성 NNB/BUC 주입
    c.execute("UPDATE cookies SET value = ? WHERE name = 'NNB'", (aged_nnb,))
    if aged_buc:
        c.execute("UPDATE cookies SET value = ? WHERE name = 'BUC'", (aged_buc,))

    # 3-3. SSAID 기반 NAPP_DI 및 DA_DD(ADID), DA_DV(AppSetId) 동적 갱신
    if fresh_ssaid:
        fresh_napp_di = hashlib.md5(fresh_ssaid.encode("utf-8")).hexdigest()
        c.execute("UPDATE cookies SET value = ? WHERE name = 'NAPP_DI'", (fresh_napp_di,))

    if fresh_dadd:
        c.execute("UPDATE cookies SET value = ? WHERE name = 'DA_DD'", (fresh_dadd,))

    target_dadv = fresh_dadv or str(uuid.uuid4())
    c.execute("UPDATE cookies SET value = ? WHERE name = 'DA_DV'", (target_dadv,))

    conn.commit()
    conn.close()

    # 4. 단말기로 push 및 원복
    subprocess.run(["adb", "-s", device_id, "push", str(local_tmp_cookie), tmp_device_cookie], check=True, capture_output=True)
    push_cmd = (
        f"su -c '"
        f"cp {tmp_device_cookie} {cookie_db}; "
        f"APP_UID=$(stat -c %u /data/data/{pkg}); "
        f"chown $APP_UID:$APP_UID {cookie_db}; "
        f"chmod 600 {cookie_db}; "
        f"rm -f {tmp_device_cookie}; "
        f"'"
    )
    run_adb_shell(device_id, push_cmd)

    # 5. null.xml의 keyLastNNB 동기화
    run_adb_shell(device_id, f"su -c 'sed -i \"s/keyLastNNB\\\">.*<\\/string>/keyLastNNB\\\">{aged_nnb}<\\/string>/\" /data/data/{pkg}/shared_prefs/null.xml'")

    if local_tmp_cookie.exists():
        local_tmp_cookie.unlink()

    return newborn_nnb, newborn_buc
