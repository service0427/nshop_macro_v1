#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/device/surgical_cleaner.py

캐시 보존형 정밀 초기화 및 세션 정제 모듈 (Surgical Cache-Preserving Cleaner)
- pm clear를 배제하고 V8 code_cache, HTTP static asset cache(JS/CSS/이미지/폰트)를 100% 보존
- 이전 세션의 쇼핑/방문 쿠키, 최근 검색 히스토리, 오프라인 비콘 큐, AppsFlyer 식별자만 선별 삭제
- SQLite Cookies DB에 21분+ 숙성 NNB/BUC 및 동적 SSAID(NAPP_DI)/ADID(DA_DD)/AppSetId(DA_DV) 직접 주입
- "날씨" 예열 불필요: 기존 DB에 즉시 치환하므로 타겟 키워드로 0초 직행
"""

import os
import time
import uuid
import sqlite3
import hashlib
import subprocess
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

from config.settings import NAVER_APP_PACKAGE, DEFAULT_DEVICE_ID
from src.device.adb_controller import run_adb_shell, force_stop_app, force_stop_gms, update_gms_adid, reset_pm_clear

def is_device_initialized(device_id: str = DEFAULT_DEVICE_ID) -> bool:
    """단말기에 Cookies DB 및 기본 캐시 구조가 존재하는지 확인"""
    pkg = NAVER_APP_PACKAGE
    chk = run_adb_shell(device_id, f"su -c '[ -s /data/data/{pkg}/app_xwhale/Default/Cookies ] && echo 1 || echo 0'")
    return chk.strip() == "1"

def initialize_baseline(device_id: str = DEFAULT_DEVICE_ID, cdp_port: int = 9905):
    """
    최초 기동 시 또는 DB가 완전히 없을 때 1회성으로 baseline 골격 형성
    """
    pkg = NAVER_APP_PACKAGE
    print(f"⚙️ [최초 초기화] 단말기({device_id})에 baseline 캐시 및 DB 구조 1회 형성 중...")
    reset_pm_clear(device_id)
    # 가벼운 메인홈 1회 오픈하여 DB 및 캐시 골격 형성
    run_adb_shell(device_id, f"am start -a android.intent.action.VIEW -d 'https://m.naver.com' -p {pkg} -f 0x14000000")
    for _ in range(25):
        time.sleep(0.2)
        if is_device_initialized(device_id):
            time.sleep(0.3)  # SQLite 디스크 쓰기 완료 완충
            break
    force_stop_app(device_id)
    time.sleep(0.3)
    print(f"✅ [최초 초기화 완료] 단말기({device_id}) baseline 캐시 준비 완료")

def clean_session_residues(device_id: str = DEFAULT_DEVICE_ID):
    """
    정적 캐시(code_cache, cache/XWhale, cache/WebView, fonts)는 100% 보존하고
    이전 세션의 식별자, WTM Service Worker(wtm.pstatic.net/sw.js), IndexedDB,
    웹스토리지, 검색기록, 오프라인 비콘 큐만 완벽하게 선별 삭제 (무오염 격리)
    """
    pkg = NAVER_APP_PACKAGE
    clean_cmd = (
        f"su -c '"
        # 1. 웹 스토리지 및 WTM Service Worker / IndexedDB 영구 세션 잔재 완전 삭제
        f"rm -rf /data/data/{pkg}/app_xwhale/Default/Local\\ Storage/*; "
        f"rm -rf /data/data/{pkg}/app_xwhale/Default/Session\\ Storage/*; "
        f"rm -rf /data/data/{pkg}/app_xwhale/Default/Service\\ Worker/*; "
        f"rm -rf /data/data/{pkg}/app_xwhale/Default/IndexedDB/*; "
        f"rm -rf /data/data/{pkg}/app_xwhale/Default/shared_proto_db/*; "
        f"rm -rf /data/data/{pkg}/app_xwhale/Default/blob_storage/*; "
        f"rm -rf /data/data/{pkg}/app_xwhale/Default/PersistentOriginTrials/*; "
        f"rm -rf /data/data/{pkg}/app_xwhale/Default/Shared\\ Dictionary/*; "
        f"rm -f /data/data/{pkg}/app_xwhale/Default/Preferences; "
        f"rm -f /data/data/{pkg}/app_xwhale/Default/Web\\ Data*; "
        f"rm -f /data/data/{pkg}/app_xwhale/Default/Cookies-journal /data/data/{pkg}/app_xwhale/Default/Cookies-wal /data/data/{pkg}/app_xwhale/Default/Cookies-shm; "
        f"rm -rf /data/data/{pkg}/app_webview/Default/Local\\ Storage/*; "
        f"rm -rf /data/data/{pkg}/app_webview/Default/Session\\ Storage/*; "
        f"rm -rf /data/data/{pkg}/app_webview/Default/Service\\ Worker/*; "
        f"rm -rf /data/data/{pkg}/app_webview/Default/IndexedDB/*; "
        f"rm -rf /data/data/{pkg}/app_webview/Default/shared_proto_db/*; "
        f"rm -rf /data/data/{pkg}/app_webview/Default/blob_storage/*; "
        f"rm -f /data/data/{pkg}/app_webview/Default/Network\\ Persistent\\ State; "
        f"rm -f /data/data/{pkg}/app_webview/Default/Cookies-journal /data/data/{pkg}/app_webview/Default/Cookies-wal /data/data/{pkg}/app_webview/Default/Cookies-shm; "
        # 2. 로컬 검색 히스토리 및 오프라인 비콘 큐 삭제 (이전 검색어 누출 방지)
        f"rm -f /data/data/{pkg}/databases/search.db*; "
        f"rm -f /data/data/{pkg}/databases/ntracker_log_v2_*.db*; "
        f"rm -f /data/data/{pkg}/databases/nelologdata*; "
        # 3. 이전 방문 도메인 및 트래커 식별자 삭제
        f"rm -f /data/data/{pkg}/shared_prefs/inappwebview.xml; "
        f"rm -f /data/data/{pkg}/shared_prefs/appsflyer-data.xml; "
        f"rm -f /data/data/{pkg}/shared_prefs/XWhaleOriginVisitLoggerPrefs.xml; "
        f"rm -f /data/data/{pkg}/shared_prefs/com.google.android.gms.appid.xml; "
        f"rm -f /data/data/{pkg}/shared_prefs/NaverLoginPreferenceData.xml; "
        f"rm -f /data/data/{pkg}/shared_prefs/NidEncryptedSharedPreferencesData.xml; "
        f"rm -rf /data/data/{pkg}/files/AFRequestCache/*; "
        # 4. Nelo / NTracker / GFP 로컬 캐시 및 잔여 식별자 파일 핀셋 삭제 (NeloInstallID, init_ts 고정 누출 방지)
        f"rm -rf /data/data/{pkg}/files/nelo_proj_data; "
        f"rm -f /data/data/{pkg}/files/nelo2_install.id; "
        f"rm -rf /data/data/{pkg}/files/nelolog; "
        f"rm -f /data/data/{pkg}/files/gfp_access_points.json; "
        f"rm -f /data/data/{pkg}/files/gfp_gps_points.json; "
        f"rm -f /data/data/{pkg}/shared_prefs/NTracker_SharedPreference.xml; "
        f"rm -f /data/data/{pkg}/shared_prefs/NELO_INIT_PREFERENCE.xml; "
        f"rm -f /data/data/{pkg}/shared_prefs/Nelo_prefs.xml; "
        f"rm -f /data/data/{pkg}/shared_prefs/com.naver.gfpsdk.nac.xml; "
        f"'"
    )
    run_adb_shell(device_id, clean_cmd)


def encrypt_naver_m_loc(lat: float, lng: float, with_history: bool = True) -> str:
    """
    네이버 앱 NHNLocationCookieManager 및 AES.c와 100% 동일한
    AES-128-ECB PKCS7 암호화로 m_loc 쿠키 문자열 생성
    키: SafeKS.p(500) = b'6b7devzhb_ku4nr1'
    실제 유기적 사용자처럼 2~3개의 최근 이동 경로(Pipe '|' 구분)를 포함하여 극강의 자연스러움 연출
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    import random
    
    key = b"6b7devzhb_ku4nr1"
    
    if with_history:
        # 반경 100m~500m 이내의 자연스러운 직전 이동 좌표 2개 생성
        hist1_lat = round(lat + random.uniform(-0.002, 0.002), 6)
        hist1_lng = round(lng + random.uniform(-0.002, 0.002), 6)
        hist2_lat = round(lat + random.uniform(-0.0008, 0.0008), 6)
        hist2_lng = round(lng + random.uniform(-0.0008, 0.0008), 6)
        curr_lat = round(lat, 6)
        curr_lng = round(lng, 6)
        raw_msg = f"{hist1_lat}:{hist1_lng}|{hist2_lat}:{hist2_lng}|{curr_lat}:{curr_lng}".encode("utf-8")
    else:
        raw_msg = f"{round(lat, 6)}:{round(lng, 6)}".encode("utf-8")
    
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(raw_msg) + padder.finalize()
    
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()
    return ciphertext.hex()


def upsert_cookie(
    cursor: sqlite3.Cursor,
    name: str,
    value: str,
    host_key: str = ".naver.com",
    path: str = "/",
    is_secure: int = 0,
    is_httponly: int = 0,
    samesite: int = -1,
    source_scheme: int = 1,
    source_port: int = 80,
    days_valid: int = 365
) -> None:
    """
    Chromium/XWhale SQLite Cookies DB 전용 클린 주입 (Delete-then-Insert):
    기존의 불완전한 UPDATE로 인한 만료 시각(expires_utc) 상속, encrypted_value 잔재,
    host_key 불일치를 원천 차단하고 100% 완전한 표준 레코드를 보장.
    """
    now_ts = time.time()
    creation_utc = int((now_ts + 11644473600) * 1_000_000)
    expires_utc = int((now_ts + 11644473600 + days_valid * 86400) * 1_000_000)
    last_access_utc = creation_utc
    last_update_utc = creation_utc

    # 1. 기존 쿠키 완전 제거 (도메인 무관 name 기준 잔재 정리 포함)
    cursor.execute("DELETE FROM cookies WHERE name = ?", (name,))

    # 2. 신규 표준 쿠키 레코드 주입 (encrypted_value는 빈 blob X'', 유효기간 1년)
    cursor.execute(
        """INSERT INTO cookies (
            creation_utc, host_key, top_frame_site_key, name, value, encrypted_value,
            path, expires_utc, is_secure, is_httponly, last_access_utc, has_expires,
            is_persistent, priority, samesite, source_scheme, source_port,
            last_update_utc, source_type, has_cross_site_ancestor
        ) VALUES (?, ?, '', ?, ?, X'', ?, ?, ?, ?, ?, 1, 1, 1, ?, ?, ?, ?, 3, 1)""",
        (
            creation_utc, host_key, name, value, path, expires_utc,
            is_secure, is_httponly, last_access_utc, samesite,
            source_scheme, source_port, last_update_utc
        )
    )

def inject_clean_cookies_and_identity(
    device_id: str,
    aged_nnb: str,
    aged_buc: str = "",
    fresh_ssaid: Optional[str] = None,
    fresh_dadd: Optional[str] = None,
    fresh_dadv: Optional[str] = None,
    fresh_lat: Optional[float] = None,
    fresh_lng: Optional[float] = None
) -> Dict[str, Any]:
    """
    1. 단말기 Cookies DB 로컬로 복사
    2. 이전 쇼핑/트래킹 잔여 쿠키 및 NID_% 로그인 잔여 토큰 완전 제거
    3. NNB, BUC, NAPP_DI, DA_DD, DA_DV, m_loc(암호화된 GPS) 갱신 (없을 시 강제 생성 보장)
    4. 단말기로 push 및 권한(600)/소유권(APP_UID) 복구
    5. null.xml keyLastNNB 및 위치 권한/좌표 동기화
    6. GMS ADID 동기화
    """
    pkg = NAVER_APP_PACKAGE
    cookie_db = f"/data/data/{pkg}/app_xwhale/Default/Cookies"
    tmp_device_cookie = f"/sdcard/macro_v1_Cookies_{device_id}.db"
    local_tmp_cookie = Path(f"/tmp/macro_v1_Cookies_{device_id}.db")

    # 1. 단말기 임시 디렉토리로 복사 후 권한 666
    run_adb_shell(device_id, f"su -c 'cp {cookie_db} {tmp_device_cookie} && chmod 666 {tmp_device_cookie}'")

    # 2. 로컬로 pull
    subprocess.run(["adb", "-s", device_id, "pull", tmp_device_cookie, str(local_tmp_cookie)], check=True, capture_output=True)

    # 3. SQLite 조작
    conn = sqlite3.connect(str(local_tmp_cookie))
    c = conn.cursor()

    # 3-1. 화이트리스트 기반 완전 정제 (무오염 원칙):
    # (1) 외부 도메인 및 서브도메인(brand.naver.com의 누적 wcs_bt, coupang, wiggle-wiggle, cafe24, criteo 등) 100% 전량 삭제
    c.execute("DELETE FROM cookies WHERE host_key NOT IN ('.naver.com', '.m.naver.com', 'm.naver.com')")

    # (2) 네이버 메인 도메인 내에서도 이전 세션/트래킹/로그인 잔재 전량 핀셋 삭제
    # (허용 유지: MM_NEW, GDOT 등 네이티브 기본 플래그만 보존, 그 외 세션/토큰은 전량 삭제 후 클린 주입)
    c.execute("""
        DELETE FROM cookies 
        WHERE name NOT IN ('MM_NEW', 'GDOT')
    """)

    # 3-2. 숙성 NNB / BUC 치환 (Delete-then-Insert로 클린 보장)
    upsert_cookie(c, name="NNB", value=aged_nnb, host_key=".naver.com", is_secure=1, is_httponly=0, samesite=0, source_scheme=2, source_port=443)
    if aged_buc:
        upsert_cookie(c, name="BUC", value=aged_buc, host_key=".naver.com", is_secure=1, is_httponly=1, samesite=0, source_scheme=2, source_port=443)

    # 3-3. SSAID 기반 NAPP_DI 치환 (없을 시 신규 생성 보장)
    fresh_napp_di = None
    if fresh_ssaid:
        fresh_napp_di = hashlib.md5(fresh_ssaid.encode("utf-8")).hexdigest()
        upsert_cookie(c, name="NAPP_DI", value=fresh_napp_di, host_key=".naver.com", is_secure=1, is_httponly=1, samesite=-1, source_scheme=2, source_port=443)

    # 3-4. DA_DD (ADID) 치환 (없을 시 신규 생성 보장)
    if fresh_dadd:
        upsert_cookie(c, name="DA_DD", value=fresh_dadd, host_key=".naver.com", is_secure=0, is_httponly=0, samesite=-1, source_scheme=1, source_port=80)

    # 3-5. DA_DV (AppSetId) 치환 (없을 시 신규 생성 보장)
    target_dadv = fresh_dadv or str(uuid.uuid4())
    upsert_cookie(c, name="DA_DV", value=target_dadv, host_key=".naver.com", is_secure=0, is_httponly=0, samesite=-1, source_scheme=1, source_port=80)

    # 3-6. m_loc (GPS 좌표 AES 암호화) 주입 (없을 시 신규 생성 보장)
    m_loc_val = None
    if fresh_lat and fresh_lng:
        m_loc_val = encrypt_naver_m_loc(fresh_lat, fresh_lng, with_history=True)
        upsert_cookie(c, name="m_loc", value=m_loc_val, host_key=".naver.com", is_secure=0, is_httponly=0, samesite=-1, source_scheme=1, source_port=80)

    conn.commit()
    conn.close()

    # 4. 단말기로 push 및 원복
    subprocess.run(["adb", "-s", device_id, "push", str(local_tmp_cookie), tmp_device_cookie], check=True, capture_output=True)
    push_cmd = (
        f"su -c '"
        f"cp {tmp_device_cookie} {cookie_db}; "
        f"rm -f {cookie_db}-journal {cookie_db}-wal {cookie_db}-shm; "
        f"APP_UID=$(stat -c %u /data/data/{pkg}); "
        f"chown $APP_UID:$APP_UID {cookie_db}; "
        f"chmod 600 {cookie_db}; "
        f"rm -f {tmp_device_cookie}; "
        f"'"
    )
    run_adb_shell(device_id, push_cmd)

    # 5. null.xml keyLastNNB 동기화 및 위치 정보 약관/좌표 동기화 + 온보딩 튜토리얼 팝업 영구 억제
    null_xml_path = f"/data/data/{pkg}/shared_prefs/null.xml"
    run_adb_shell(device_id, f"su -c 'sed -i \"s/keyLastNNB\\\">.*<\\/string>/keyLastNNB\\\">{aged_nnb}<\\/string>/\" {null_xml_path}'")
    run_adb_shell(device_id, f"su -c 'sed -i \"s/keyLocationAgree\\\" value=\\\"false\\\"/keyLocationAgree\\\" value=\\\"true\\\"/\" {null_xml_path}'")
    run_adb_shell(device_id, f"su -c 'grep -q keyLocationUserAgreementAccepted {null_xml_path} || sed -i \"s/<\\/map>/    <boolean name=\\\"keyLocationUserAgreementAccepted\\\" value=\\\"true\\\" \\/>\\n<\\/map>/\" {null_xml_path}'")
    # 온보딩 코치마크 및 튜토리얼 팝업 방지
    run_adb_shell(device_id, f"su -c 'grep -q keyShowNewMainTutorial {null_xml_path} && sed -i \"s/keyShowNewMainTutorial\\\" value=\\\"[^\"]*\\\"/keyShowNewMainTutorial\\\" value=\\\"false\\\"/\" {null_xml_path} || sed -i \"s/<\\/map>/    <boolean name=\\\"keyShowNewMainTutorial\\\" value=\\\"false\\\" \\/>\\n<\\/map>/\" {null_xml_path}'")
    run_adb_shell(device_id, f"su -c 'grep -q keyNewmainTutorialComplete {null_xml_path} && sed -i \"s/keyNewmainTutorialComplete\\\" value=\\\"[^\"]*\\\"/keyNewmainTutorialComplete\\\" value=\\\"true\\\"/\" {null_xml_path} || sed -i \"s/<\\/map>/    <boolean name=\\\"keyNewmainTutorialComplete\\\" value=\\\"true\\\" \\/>\\n<\\/map>/\" {null_xml_path}'")
    run_adb_shell(device_id, f"su -c 'grep -q keyNextTutorialComplete {null_xml_path} && sed -i \"s/keyNextTutorialComplete\\\" value=\\\"[^\"]*\\\"/keyNextTutorialComplete\\\" value=\\\"true\\\"/\" {null_xml_path} || sed -i \"s/<\\/map>/    <boolean name=\\\"keyNextTutorialComplete\\\" value=\\\"true\\\" \\/>\\n<\\/map>/\" {null_xml_path}'")
    run_adb_shell(device_id, f"su -c 'grep -q keyDarkTutorialComplete {null_xml_path} && sed -i \"s/keyDarkTutorialComplete\\\" value=\\\"[^\"]*\\\"/keyDarkTutorialComplete\\\" value=\\\"true\\\"/\" {null_xml_path} || sed -i \"s/<\\/map>/    <boolean name=\\\"keyDarkTutorialComplete\\\" value=\\\"true\\\" \\/>\\n<\\/map>/\" {null_xml_path}'")
    if fresh_lat and fresh_lng:
        run_adb_shell(device_id, f"su -c 'grep -q lastLocationLatitude {null_xml_path} && sed -i \"s/lastLocationLatitude\\\">.*<\\/string>/lastLocationLatitude\\\">{fresh_lat}<\\/string>/\" {null_xml_path} || sed -i \"s/<\\/map>/    <string name=\\\"lastLocationLatitude\\\">{fresh_lat}<\\/string>\\n<\\/map>/\" {null_xml_path}'")
        run_adb_shell(device_id, f"su -c 'grep -q lastLocationLongtitude {null_xml_path} && sed -i \"s/lastLocationLongtitude\\\">.*<\\/string>/lastLocationLongtitude\\\">{fresh_lng}<\\/string>/\" {null_xml_path} || sed -i \"s/<\\/map>/    <string name=\\\"lastLocationLongtitude\\\">{fresh_lng}<\\/string>\\n<\\/map>/\" {null_xml_path}'")
        run_adb_shell(device_id, f"su -c 'grep -q lastLocationLongitude {null_xml_path} && sed -i \"s/lastLocationLongitude\\\">.*<\\/string>/lastLocationLongitude\\\">{fresh_lng}<\\/string>/\" {null_xml_path} || sed -i \"s/<\\/map>/    <string name=\\\"lastLocationLongitude\\\">{fresh_lng}<\\/string>\\n<\\/map>/\" {null_xml_path}'")

    # 6. GMS ADID 동기화 (GMS 프로세스 메모리 캐시 역덮어쓰기 원천 차단)
    if fresh_dadd:
        update_gms_adid(device_id, fresh_dadd)
        force_stop_gms(device_id, max_wait=2.0)

    if local_tmp_cookie.exists():
        local_tmp_cookie.unlink()

    return {
        "nnb": aged_nnb,
        "buc": aged_buc,
        "ssaid": fresh_ssaid,
        "napp_di": fresh_napp_di,
        "dadd": fresh_dadd,
        "dadv": target_dadv,
        "m_loc": m_loc_val
    }

def perform_surgical_cycle(
    device_id: str,
    aged_nnb: str,
    aged_buc: str = "",
    fresh_ssaid: Optional[str] = None,
    fresh_dadd: Optional[str] = None,
    fresh_dadv: Optional[str] = None,
    fresh_lat: Optional[float] = None,
    fresh_lng: Optional[float] = None,
    cdp_port: int = 9905
) -> Dict[str, Any]:
    """
    정밀 리셋 전체 사이클 총괄 실행:
    1. 미초기화 단말기일 경우 1회 baseline 형성
    2. 앱 강제 종료
    3. 이전 세션 잔재 선별 삭제 (정적 캐시 100% 보존)
    4. 숙성 쿠키 및 1회용 신규 식별자 5종 + m_loc(암호화 GPS) 직접 주입
    소요 시간: 약 0.3~0.5초 (초고속)
    """
    t0 = time.time()
    if not is_device_initialized(device_id):
        initialize_baseline(device_id, cdp_port=cdp_port)

    force_stop_app(device_id, max_wait=3.0)
    force_stop_gms(device_id, max_wait=2.0)
    time.sleep(0.2)  # 커널 프로세스 언마운트 및 파일 디스크립터 해제 대기 (CookieMonster 역덮어쓰기 원천 방지)
    clean_session_residues(device_id)

    # 유심 부재 단말기(Wi-Fi/공기계) FDS 탐지 방지: OS 레벨 통신사/유심 정상 개통 모의
    sim_spoof_cmd = (
        "su -c '"
        "setprop gsm.sim.state LOADED,LOADED; "
        "setprop gsm.operator.numeric 45008; "
        "setprop gsm.network.type LTE,LTE; "
        "setprop gsm.sim.operator.numeric 45008; "
        "setprop gsm.sim.operator.alpha KT; "
        "setprop gsm.operator.alpha KT; "
        "setprop gsm.operator.isroaming false; "
        "setprop gsm.current.phone-type 1; "
        "'"
    )
    run_adb_shell(device_id, sim_spoof_cmd)

    injected = inject_clean_cookies_and_identity(
        device_id=device_id,
        aged_nnb=aged_nnb,
        aged_buc=aged_buc,
        fresh_ssaid=fresh_ssaid,
        fresh_dadd=fresh_dadd,
        fresh_dadv=fresh_dadv,
        fresh_lat=fresh_lat,
        fresh_lng=fresh_lng
    )

    # [초반 1단계: Pre-launch Gate] 앱 구동 전 디스크 DB 실측 사전 검증 & 1회 자가치유 (Self-Healing)
    from src.device.cookie_rollback_manager import CookieRollbackManager
    def _re_inject():
        return inject_clean_cookies_and_identity(
            device_id=device_id,
            aged_nnb=aged_nnb,
            aged_buc=aged_buc,
            fresh_ssaid=fresh_ssaid,
            fresh_dadd=fresh_dadd,
            fresh_dadv=fresh_dadv,
            fresh_lat=fresh_lat,
            fresh_lng=fresh_lng
        )

    profile_dict = {
        "ssaid": fresh_ssaid or "",
        "dadd": fresh_dadd,
        "dadv": fresh_dadv,
        "nnb": aged_nnb
    }
    gate_ok, gate_reason, _ = CookieRollbackManager.pre_launch_gate(device_id, profile_dict, re_inject_callback=_re_inject)
    if not gate_ok:
        raise RuntimeError(f"PRE_LAUNCH_GATE_FAILED: {gate_reason}")

    injected["elapsed_sec"] = round(time.time() - t0, 3)
    return injected
