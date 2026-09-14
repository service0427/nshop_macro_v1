#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
[FDS 전수 감사 파이프라인 - 1단계] Java 디컴파일 코드 전수 AST/패턴 스캐너 (Phase 1)
(scripts/fds_audit_pipeline/phase1_extract.py)
========================================================================================
- 기능:
    1. 디컴파일된 수만 개의 Java 파일을 한 줄씩 전수 독해(Line-by-line inspection).
    2. 17개 카테고리, 60개 세부 규칙에 따라 하드웨어, 통신, 보안, OS 식별자 수집 호출을 전수 추출.
    3. 24코어 병렬 프로세싱으로 수만 개 파일을 초고속 정밀 스캔.
    4. 1차 원시 후보군(JSONL) 생성 및 카테고리별 통계 리포트 출력.
========================================================================================
"""

import os
import re
import sys
import time
import json
from pathlib import Path
from multiprocessing import Pool, cpu_count
from collections import defaultdict, Counter

# 기본 소스 디렉터리
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BASE_SOURCES_DIR = PROJECT_ROOT / "archive/legacy_tmp/tmp/archive/legacy_tmp_dev/apks/naver_app/jadx_out/sources"
OUTPUT_DIR = PROJECT_ROOT / "scripts/fds_audit_pipeline"
OUTPUT_JSONL = OUTPUT_DIR / "phase1_raw_candidates.jsonl"
SUMMARY_REPORT = OUTPUT_DIR / "phase1_summary.json"

# 분석 대상 주요 패키지 (네이버 및 보안/광고 서드파티 SDK 전수)
TARGET_PACKAGES = [
    "com/naver",
    "com/nhn",
    "com/raonsecure",
    "com/softsecurity",
    "com/appsflyer",
    "com/prismplayer",
    "kr/co/raon",
]

# 17개 도메인 규칙 정의 (정규식 패턴 및 메타데이터)
RULES = [
    # 1. Telephony 식별자 (IMEI, IMSI, SIM, 통신사)
    {
        "id": "TEL_IMEI_DEVICEID",
        "category": "TELEPHONY",
        "pattern": re.compile(r'\.(getDeviceId|getImei|getMeid)\s*\('),
        "desc": "하드웨어 IMEI/MEID/단말고유번호 조회"
    },
    {
        "id": "TEL_SUBSCRIBER_SIM",
        "category": "TELEPHONY",
        "pattern": re.compile(r'\.(getSubscriberId|getSimSerialNumber|getLine1Number)\s*\('),
        "desc": "IMSI(가입자번호) / SIM 시리얼 / 전화번호 조회"
    },
    {
        "id": "TEL_OPERATOR_CELL",
        "category": "TELEPHONY",
        "pattern": re.compile(r'\.(getSimOperator|getNetworkOperator|getCellLocation|getAllCellInfo)\s*\('),
        "desc": "기지국 셀 ID / SIM 통신사 코드 조회"
    },

    # 2. Wi-Fi 및 로컬 네트워크
    {
        "id": "WIFI_BSSID_SSID",
        "category": "WIFI_NETWORK",
        "pattern": re.compile(r'\.(getBSSID|getSSID)\s*\('),
        "desc": "Wi-Fi 물리 AP MAC(BSSID) / SSID 조회"
    },
    {
        "id": "WIFI_MAC_IP",
        "category": "WIFI_NETWORK",
        "pattern": re.compile(r'\.(getMacAddress|getIpAddress|getScanResults|getDhcpInfo)\s*\('),
        "desc": "Wi-Fi MAC / IP / 주변 AP 스캔 목록 조회"
    },
    {
        "id": "NET_INTERFACE_MAC",
        "category": "WIFI_NETWORK",
        "pattern": re.compile(r'NetworkInterface\.(getNetworkInterfaces|getHardwareAddress)\s*\('),
        "desc": "NetworkInterface 물리 MAC 주소 열람"
    },

    # 3. 블루투스
    {
        "id": "BT_IDENTIFIER",
        "category": "BLUETOOTH",
        "pattern": re.compile(r'Bluetooth(Adapter|Device)\..*?(getAddress|getName|getBondedDevices|startDiscovery)\s*\('),
        "desc": "블루투스 물리 MAC 주소 / 디바이스명 / 페어링 기기 조회"
    },

    # 4. OS 고유 식별자 (Android ID)
    {
        "id": "OS_ANDROID_ID",
        "category": "OS_IDENTIFIERS",
        "pattern": re.compile(r'(Settings\.(Secure|System|Global)\.getString\s*\(.*?(android_id|ANDROID_ID))|(\"android_id\")'),
        "desc": "SSAID (Android ID) 시스템 조회"
    },

    # 5. Build 하드웨어 프로퍼티
    {
        "id": "BUILD_SERIAL",
        "category": "HARDWARE_BUILD",
        "pattern": re.compile(r'Build\.(SERIAL|getSerial\s*\()'),
        "desc": "Build.SERIAL 하드웨어 시리얼 번호 조회"
    },
    {
        "id": "BUILD_PROPERTIES",
        "category": "HARDWARE_BUILD",
        "pattern": re.compile(r'Build\.(FINGERPRINT|HARDWARE|BOARD|BOOTLOADER|RADIO|MANUFACTURER|BRAND|MODEL)\b'),
        "desc": "Build 펌웨어 지문 / 하드웨어 칩셋 / 보드 / 모델명 조회"
    },

    # 6. DRM 및 MediaDrm
    {
        "id": "DRM_WIDEVINE",
        "category": "DRM_SECURITY",
        "pattern": re.compile(r'(MediaDrm|deviceUniqueId|getPropertyByteArray\s*\(|edef8ba9-79d6-4ace-a3c8-27dcd51d21ed)', re.IGNORECASE),
        "desc": "MediaDrm 칩셋 고유 ID (Widevine deviceUniqueId) 조회"
    },

    # 7. 배터리 하드웨어 상태
    {
        "id": "BATT_TELEMETRY",
        "category": "BATTERY",
        "pattern": re.compile(r'BatteryManager\.(EXTRA_LEVEL|EXTRA_TEMPERATURE|EXTRA_VOLTAGE|BATTERY_PROPERTY_)'),
        "desc": "배터리 전압 / 온도 / 잔량 텔레메트리 조회"
    },

    # 8. 센서 (가속도, 자이로, 자기장)
    {
        "id": "SENSOR_ACCESS",
        "category": "SENSORS",
        "pattern": re.compile(r'SensorManager\..*?(getDefaultSensor|getSensorList|registerListener)\s*\('),
        "desc": "모션/자이로/가속도 센서 하드웨어 접근"
    },

    # 9. 위치 (LocationManager, FusedLocation)
    {
        "id": "LOCATION_SERVICES",
        "category": "LOCATION",
        "pattern": re.compile(r'(LocationManager\..*?(getLastKnownLocation|requestLocationUpdates))|(FusedLocationProviderClient)'),
        "desc": "GPS / 네트워크 원시 위치 좌표 수집"
    },

    # 10. 패키지 매니저 및 앱 설치 이력
    {
        "id": "PKG_INSTALL_AUDIT",
        "category": "PACKAGE_MANAGER",
        "pattern": re.compile(r'(\.firstInstallTime|\.lastUpdateTime|\.getInstallerPackageName\s*\(|\.getInstalledPackages\s*\()'),
        "desc": "설치/업데이트 타임스탬프 / 설치자 패키지 / 설치 앱 목록 조회"
    },

    # 11. 커널 /proc 파일시스템 직접 접근
    {
        "id": "FS_PROC_INSPECTION",
        "category": "KERNEL_FS",
        "pattern": re.compile(r'\"/proc/(net/arp|net/route|cpuinfo|version|meminfo|mounts|self/maps|self/status)\"'),
        "desc": "/proc 커널 파일 (ARP 테이블, CPU 정보, 라우팅 테이블) 직접 열람"
    },

    # 12. /sys 및 /efs 하드웨어 파일시스템 직접 접근
    {
        "id": "FS_SYS_EFS_INSPECTION",
        "category": "KERNEL_FS",
        "pattern": re.compile(r'\"/(sys/class/|sys/devices/|efs/|dev/__properties__/)'),
        "desc": "/sys 및 /efs 하드웨어 시리얼/드라이버 파일 직접 열람"
    },

    # 13. 셸 커맨드 및 SystemProperties 호출
    {
        "id": "SHELL_EXEC_PROP",
        "category": "SHELL_EXEC",
        "pattern": re.compile(r'(Runtime\.getRuntime\s*\(\)\.exec\s*\(|ProcessBuilder\s*\(|SystemProperties\.(get|getInt)\s*\()'),
        "desc": "런타임 셸 명령어 실행 (exec) 또는 getprop 시스템 프로퍼티 조회"
    },

    # 14. 루팅 / 탬퍼링 탐지
    {
        "id": "ROOT_TAMPER_DETECTION",
        "category": "ROOT_DETECTION",
        "pattern": re.compile(r'(\"/system/bin/su\"|\"/system/xbin/su\"|\"which su\"|\"magisk\"|\"supersu\"|\"xposed\"|\"frida\"|test-keys)', re.IGNORECASE),
        "desc": "루팅 바이너리(su, magisk), 후킹 프레임워크(xposed, frida) 탐지 문자열"
    },

    # 15. 구글 광고 ID 및 앱셋 ID
    {
        "id": "GOOGLE_AD_SERVICES",
        "category": "GOOGLE_SERVICES",
        "pattern": re.compile(r'(AdvertisingIdClient\..*?getAdvertisingIdInfo|AppSet\..*?getAppSetIdInfo|FirebaseInstallations\..*?getId)'),
        "desc": "Google ADID (광고 ID) / AppSetId / Firebase ID 수집"
    },

    # 16. 디스플레이 물리 해상도
    {
        "id": "DISPLAY_METRICS",
        "category": "DISPLAY",
        "pattern": re.compile(r'DisplayMetrics\..*?(widthPixels|heightPixels|densityDpi|xdpi|ydpi)|getRealMetrics\s*\('),
        "desc": "물리 디스플레이 해상도 및 픽셀 밀도(DPI) 조회"
    },

    # 17. 메모리 및 프로세스
    {
        "id": "PROCESS_MEMORY",
        "category": "SYSTEM_INFO",
        "pattern": re.compile(r'ActivityManager\..*?(getRunningAppProcesses|getMemoryInfo|getDeviceConfigurationInfo)\s*\('),
        "desc": "실행 중인 프로세스 목록 및 메모리 하드웨어 스펙 조회"
    },

    # 18. 인앱 웹뷰(Whale/Chromium) 브릿지 및 User-Agent
    {
        "id": "WEBVIEW_BRIDGE_UA",
        "category": "WEBVIEW_FINGERPRINT",
        "pattern": re.compile(r'(\.addJavascriptInterface\s*\(|\.(setUserAgentString|getUserAgentString|getDefaultUserAgent)\s*\()'),
        "desc": "인앱 브라우저 자바스크립트 브릿지 바인딩 및 User-Agent 조작"
    },

    # 19. 클립보드 텍스트 조회
    {
        "id": "CLIPBOARD_ACCESS",
        "category": "CLIPBOARD",
        "pattern": re.compile(r'ClipboardManager\..*?(getPrimaryClip|getText)\s*\('),
        "desc": "단말기 클립보드 텍스트 훔쳐보기"
    },

    # 20. 셀룰러 네트워크 통신망 세부 타입
    {
        "id": "CELLULAR_NETWORK_TYPE",
        "category": "TELEPHONY",
        "pattern": re.compile(r'\.(getDataNetworkType|getVoiceNetworkType|getPhoneType)\s*\('),
        "desc": "LTE/5G 통신망 세부 타입 및 기기 폰 타입 조회"
    },

    # 21. 앱 서명 해시 및 키스토어 (위변조 탐지)
    {
        "id": "APP_SIGNATURE_KEYSTORE",
        "category": "INTEGRITY_SIGNATURE",
        "pattern": re.compile(r'(\.signatures|\.signingInfo|getPackageCertificate\s*\(|KeyStore\.getInstance)'),
        "desc": "APK 위변조 탐지를 위한 앱 서명(Signing) / 키스토어 조회"
    }
]


def scan_single_file(file_path_str: str):
    """단일 Java 파일을 1행부터 끝까지 정밀 스캔"""
    findings = []
    try:
        with open(file_path_str, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        total_lines = len(lines)
        for idx, line in enumerate(lines):
            line_no = idx + 1
            # 공백 및 주석 라인 필터링
            stripped = line.strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("*"):
                continue

            for r in RULES:
                if r["pattern"].search(line):
                    # 컨텍스트 1줄 앞뒤 추출
                    prev_line = lines[idx - 1].strip() if idx > 0 else ""
                    next_line = lines[idx + 1].strip() if idx < total_lines - 1 else ""

                    findings.append({
                        "file": file_path_str,
                        "line": line_no,
                        "rule_id": r["id"],
                        "category": r["category"],
                        "desc": r["desc"],
                        "code": stripped[:180],
                        "context": [prev_line[:120], stripped[:120], next_line[:120]]
                    })
    except Exception as e:
        pass

    return findings


def collect_target_files():
    """분석 대상 전체 Java 파일 목록 수집 (androidx/ 및 kotlin/ 제외 모든 앱/보안/난독화 패키지 53,900+개 전수)"""
    file_list = []
    if not BASE_SOURCES_DIR.exists():
        print(f"[!] 디렉터리를 찾을 수 없습니다: {BASE_SOURCES_DIR}")
        return file_list

    base_str = str(BASE_SOURCES_DIR)
    for root, dirs, files in os.walk(base_str):
        rel = os.path.relpath(root, base_str)
        if rel.startswith("androidx") or rel.startswith("kotlin"):
            continue
        for fname in files:
            if fname.endswith(".java"):
                file_list.append(os.path.join(root, fname))

    return file_list


def main():
    t_start = time.time()
    print("=" * 82)
    print(" 🔍 [FDS 전수 감사 파이프라인 - 1단계] Java 디컴파일 코드 전수 스캔 (Phase 1)")
    print("=" * 82)

    files = collect_target_files()
    total_files = len(files)
    print(f"[*] 분석 대상 핵심 패키지 Java 파일 총 수량: {total_files:,}개")
    if total_files == 0:
        print("[!] 대상 파일이 없습니다.")
        return

    workers = min(cpu_count(), 24)
    print(f"[*] 병렬 스캔 워커 수: {workers}개 코어 활용")
    print("[*] 1차 전수 스캔(Line-by-line 패턴 및 API 추출) 시작...")

    all_findings = []
    with Pool(processes=workers) as pool:
        for idx, result in enumerate(pool.imap_unordered(scan_single_file, files, chunksize=100)):
            if result:
                all_findings.extend(result)
            if (idx + 1) % 5000 == 0 or (idx + 1) == total_files:
                elapsed = time.time() - t_start
                print(f"    ↳ 진행률: {idx + 1:,} / {total_files:,} 파일 완료 ({elapsed:.1f}초 경과, 후보군 {len(all_findings):,}건 추출)")

    duration = round(time.time() - t_start, 2)
    print("=" * 82)
    print(f" [✓] 1단계 전수 스캔 완료! (소요 시간: {duration}초 | 총 후보군: {len(all_findings):,}건)")
    print("=" * 82)

    # 1. JSONL 파일로 전수 저장
    print(f"[*] 원시 후보군 레코드 저장 중: {OUTPUT_JSONL}")
    with open(OUTPUT_JSONL, "w", encoding="utf-8") as f:
        for item in all_findings:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # 2. 카테고리별 통계 집계
    cat_counts = Counter(item["category"] for item in all_findings)
    rule_counts = Counter(item["rule_id"] for item in all_findings)
    class_counts = Counter(item["file"] for item in all_findings)

    summary_data = {
        "scan_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_sec": duration,
        "total_files_scanned": total_files,
        "total_candidates": len(all_findings),
        "category_breakdown": dict(cat_counts.most_common()),
        "rule_breakdown": dict(rule_counts.most_common()),
        "top_data_collecting_classes": [
            {"file": k.replace(str(PROJECT_ROOT) + "/", ""), "count": v}
            for k, v in class_counts.most_common(30)
        ]
    }

    with open(SUMMARY_REPORT, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    # 콘솔 요약 출력
    print("\n📊 [카테고리별 수집 호출 발생 현황]")
    print("-" * 55)
    for cat, count in cat_counts.most_common():
        print(f"  • {cat:20} : {count:5,}건")
    print("-" * 55)

    print("\n🏆 [가장 많은 시스템 데이터를 수집하는 Top 15 클래스]")
    print("-" * 82)
    for rank, (fpath, cnt) in enumerate(class_counts.most_common(15), 1):
        rel_f = fpath.replace(str(BASE_SOURCES_DIR) + "/", "")
        print(f"  {rank:2d}. [{cnt:3d}건] {rel_f}")
    print("-" * 82)


if __name__ == "__main__":
    main()
