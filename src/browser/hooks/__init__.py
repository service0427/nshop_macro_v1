#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/browser/hooks/__init__.py

Frida 후킹 모듈 통합 관리자 (100% Pure Core Root Hook Bundler)

[전체 아키텍처 원칙]:
1. 순수 안드로이드 OS 및 Java 표준 최심부(Core Root) 우선 정책:
   - 앱 내부 클래스나 특정 라이브러리(NTracker, Nelo, ClientIdUtils 등) 땜빵 코드를 배제하고,
     앱 버전 업그레이드/리팩토링/난독화에도 불변하는 안드로이드 OS 표준 프레임워크 및 Java 최심부 표준 API를 타겟팅함
2. 엄격한 주입 우선순위 파이프라인 (Execution Priority Pipeline):
   - [Priority 0] Bootstrap: Application Context ClassLoader 확보 (앱 패키지 내부 클래스 접근 보장)
   - [Priority 1] Device Integrity & Anti-Rooting: 앱 시작 직후 백그라운드 스레드가 검사하는
                  스토리지(StatFs), 사설 IP(Inet4Address), 루팅(Runtime.exec/File.exists), 설치시간(PackageManager) 최우선 제어
   - [Priority 2] Hardware Identity (SSAID): Settings$Secure android_id 가로채기 (NAPP_DI 파생의 절대적 근원)
   - [Priority 3] Google Identity & GMS: AccountManager(구글 계정 상시 로그인) + AppSetId(Scope 1) + ADID(추적 허용)
   - [Priority 4] Network & Telephony: NetworkCapabilities(Wi-Fi 차단 -> Cellular 활성) + TelephonyManager(KT LTE 45008)
   - [Priority 5] Location (GPS & m_loc): LocationManager + FusedLocation (모의 위치 탐지 차단 및 현실적 내륙 좌표 주입)
"""

from typing import Optional
from src.browser.hooks.identity_hook import build_identity_hook
from src.browser.hooks.google_identity_hook import build_google_identity_hook
from src.browser.hooks.ad_id_hook import build_ad_id_hook
from src.browser.hooks.network_hook import build_network_hook
from src.browser.hooks.location_hook import build_location_hook
from src.browser.hooks.device_integrity_hook import build_device_integrity_hook


def build_hook_bundle(
    spoof_ssaid: Optional[str] = None,
    spoof_google_account: Optional[str] = None,
    spoof_dadd: Optional[str] = None,
    spoof_dadv: Optional[str] = None,
    spoof_network_type: Optional[str] = "cellular",
    spoof_mcc_mnc: Optional[str] = "450_08",
    spoof_lat: Optional[float] = 37.4979,
    spoof_lng: Optional[float] = 127.0276,
    spoof_acc: Optional[float] = 5.0,
    spoof_alt: Optional[float] = 35.0,
    spoof_bearing: Optional[float] = 0.0,
    fake_install_time: Optional[int] = None,
    fake_update_time: Optional[int] = None,
    fake_boot_time: Optional[int] = None,
    target_nnb: Optional[str] = None
) -> str:
    """
    100% 순수 OS/GMS 최심부 표준 API 훅 코드를 우선순위에 맞추어 결합한 최종 Frida JS 번들 생성
    :param spoof_ssaid: Android OS 표준 android_id (16자리 헥사)
    :param spoof_google_account: 가상 구글 계정 이메일 (AccountManager)
    :param spoof_dadd: Google ADID UUID (AdvertisingIdClient)
    :param spoof_dadv: Google AppSetId UUID (AppSetIdInfo Scope 1)
    :param spoof_network_type: "cellular" (LTE 환경 강제)
    :param spoof_mcc_mnc: "450_08" (KT LTE 통신사 코드)
    :param spoof_lat: 위도 (대한민국 내륙 도심)
    :param spoof_lng: 경도 (대한민국 내륙 도심)
    :param spoof_acc: GPS 오차 (3.5m ~ 9.5m)
    :param spoof_alt: 고도 (18.0m ~ 75.0m)
    :param spoof_bearing: 방위각 (0.0도 ~ 359.0도)
    :param fake_install_time: 15~45일 전 생성된 가상 설치 타임스탬프 (밀리초)
    :param fake_update_time: 설치 후 3~12일 뒤 생성된 가상 업데이트 타임스탬프 (밀리초)
    :param fake_boot_time: 4~28시간 전 생성된 가상 단말기 부팅 타임스탬프 (밀리초)
    :return: 결합된 Frida JS 스크립트 코드
    """
    hook_blocks = []

    # -------------------------------------------------------------------------
    # [우선순위 0] 공통 부트스트랩: 네이버 앱의 Application Context ClassLoader 확보
    # 네이버 앱의 멀티덱스 및 동적 클래스로더 환경에서 최상위 클래스에 접근하기 위해 최우선 실행
    # -------------------------------------------------------------------------
    bootstrap_code = """
      // [Priority 0] Bootstrap ClassLoader Hook
      try {
        const ActivityThread = frida_java_bridge_default.use("android.app.ActivityThread");
        const app = ActivityThread.currentApplication();
        if (app) {
          frida_java_bridge_default.classFactory.loader = app.getClassLoader();
        }
      } catch(e) {}
    """
    hook_blocks.append(bootstrap_code)

    # -------------------------------------------------------------------------
    # [우선순위 1] 기기 무결성, 라이프사이클, 스토리지 크기, 사설 IP 은닉, 루팅 차단
    # - 앱 기동 직후 백그라운드 스레드가 시스템 정보를 가장 먼저 스캔하므로 1순위로 즉시 방어벽 구축
    # - StatFs(스토리지 크기), Inet4Address(사설 Wi-Fi IP 원천 차단), Runtime.exec(루팅 명령 차단),
    #   ApplicationPackageManager(설치시간 위조), WifiManager(주변 BSSID 스캔 차단)
    # -------------------------------------------------------------------------
    hook_blocks.append(build_device_integrity_hook(
        fake_install_time=fake_install_time,
        fake_update_time=fake_update_time,
        fake_boot_time=fake_boot_time
    ))

    # -------------------------------------------------------------------------
    # [우선순위 2] 기기 고유 하드웨어 식별자 (OS Root: Settings$Secure android_id)
    # - 네이버 앱의 NAPP_DI 및 DeviceID 해시 연산의 근원이 되므로 2순위 주입
    # -------------------------------------------------------------------------
    if spoof_ssaid:
        hook_blocks.append(build_identity_hook(spoof_ssaid))

    # -------------------------------------------------------------------------
    # [우선순위 3] 구글 계정 및 광고 식별자 (OS Root: AccountManager + GMS: AppSetId + ADID)
    # - 구글 계정 등록 상태(AccountManager) 및 최고 신뢰 등급인 SCOPE_DEVELOPER(1) 주입
    # -------------------------------------------------------------------------
    if spoof_google_account or spoof_dadd or spoof_dadv:
        hook_blocks.append(build_google_identity_hook(
            spoof_google_account=spoof_google_account,
            spoof_dadd=spoof_dadd,
            spoof_dadv=spoof_dadv
        ))

    # -------------------------------------------------------------------------
    # [우선순위 4] 네트워크 수송망 및 통신사 (OS Root: NetworkCapabilities + TelephonyManager)
    # - Wi-Fi망 차단 및 순수 KT LTE 45008 개통 환경 모의
    # -------------------------------------------------------------------------
    if spoof_network_type or spoof_mcc_mnc:
        hook_blocks.append(build_network_hook(
            spoof_network_type=spoof_network_type,
            spoof_mcc_mnc=spoof_mcc_mnc
        ))

    # -------------------------------------------------------------------------
    # [우선순위 5] 위치 센서 (GPS) 및 m_loc 자동 생성 (OS Root: LocationManager + GMS: FusedLocation)
    # - 모의 위치(Mock Location) 탐지 무력화 및 순정 하드웨어 GPS 측정값 에뮬레이션
    # -------------------------------------------------------------------------
    if spoof_lat is not None and spoof_lng is not None:
        hook_blocks.append(build_location_hook(
            latitude=spoof_lat,
            longitude=spoof_lng,
            accuracy=spoof_acc or 5.0,
            altitude=spoof_alt or 35.0,
            bearing=spoof_bearing or 0.0
        ))
    
    # Pure macro mode: No artificial URL interceptor or request modification

    return "\n".join(hook_blocks)


__all__ = [
    "build_hook_bundle",
    "build_identity_hook",
    "build_google_identity_hook",
    "build_ad_id_hook",
    "build_network_hook",
    "build_location_hook",
    "build_device_integrity_hook"
]
