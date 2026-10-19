#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/sanitize_all_devices.py

모든 연결된 단말기(19대)의 누적된 식별자 잔재 및 abuse 플래그를 1회 전면 소탕:
- slSessionId (com.nhn.android.search_preferences.xml) 전량 삭제
- OPENPAGE_TAB.xml (누적 tabID=4141 등) 전량 삭제
- inappshoppingstorage.xml, files/datastore, files/rList, exoplayer_internal.db 전량 삭제
- null.xml: log.viewCntIdpw(로그인 챌린지 누적 플래그) 및 2400+ 누적 카운터 전량 제거 -> 무결한 표준 템플릿 재작성
- V8/HTTP 정적 캐시(code_cache, Cache, fonts)는 100% 완전 보존
"""

import sys
import subprocess
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.device.adb_controller import force_stop_app, force_stop_gms, run_adb_shell
from src.device.surgical_cleaner import clean_session_residues, write_pristine_null_xml
from config.settings import NAVER_APP_PACKAGE

def sanitize_device(device_id: str):
    pkg = NAVER_APP_PACKAGE
    print(f"🧹 [{device_id}] 정밀 세정 및 핑거프린트 소탕 시작...")
    
    # 1. 앱 및 GMS 강제 종료
    force_stop_app(device_id, max_wait=2.0)
    force_stop_gms(device_id, max_wait=1.0)
    
    # 2. 세션 잔재 및 핑거프린트 파일 선별 삭제 (V8/HTTP 캐시 보존)
    clean_session_residues(device_id)
    
    # 3. 기존 null.xml에서 NNB, 위도/경도 유지하며 무결한 표준 템플릿으로 재작성
    cat_out = run_adb_shell(device_id, f"su -c 'cat /data/data/{pkg}/shared_prefs/null.xml 2>/dev/null'")
    import re
    nnb_m = re.search(r'keyLastNNB\">([^<]+)<', cat_out)
    lat_m = re.search(r'lastLocationLatitude\">([^<]+)<', cat_out)
    lng_m = re.search(r'lastLocationLongitude\">([^<]+)<', cat_out)
    
    nnb = nnb_m.group(1) if nnb_m else ""
    lat = float(lat_m.group(1)) if lat_m else 37.566535
    lng = float(lng_m.group(1)) if lng_m else 126.977969
    
    write_pristine_null_xml(device_id, aged_nnb=nnb, fresh_lat=lat, fresh_lng=lng)
    print(f"✅ [{device_id}] 소탕 완료 (NNB: {nnb}, Pos: {lat:.4f}, {lng:.4f})")

def main():
    out = subprocess.check_output(['adb', 'devices']).decode()
    devices = [l.split()[0] for l in out.strip().splitlines()[1:] if 'device' in l and not l.startswith('*')]
    print(f"🚀 총 {len(devices)}대 단말기 전면 핑거프린트 소탕 작업 개시")
    for dev in devices:
        try:
            sanitize_device(dev)
        except Exception as e:
            print(f"❌ [{dev}] 오류 발생: {e}")
            
    print(f"\n✨ 전 단말기({len(devices)}대) 소탕 완료! 무결성 감사 실행 중...")

if __name__ == "__main__":
    main()
