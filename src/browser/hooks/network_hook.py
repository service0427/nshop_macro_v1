#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/browser/hooks/network_hook.py

[OS 최심부 훅] 네트워크 수송망(Cellular vs Wi-Fi) 및 이동통신사(TelephonyManager) 완전 통제 모듈

[아키텍처 철칙 & 설계 원칙]:
1. OS 프레임워크 표준 API 최심부 타겟팅:
   - 앱 레벨(ntracker, NetworkUtil, ConnectivityManager 보조 유틸 등)의 임시방편 코드를 배제
   - 안드로이드 OS의 `android.net.NetworkCapabilities` 및 `android.telephony.TelephonyManager` 직접 가로챔
2. FDS 관통 핵심 원리:
   - 네이버 FDS 및 텔레메트리(Nelo, NLog, LCS)는 단말기가 Wi-Fi망인지 셀룰러(LTE/5G)망인지를 판별하여
     트래픽 점수 가중치를 부여하고, Wi-Fi일 경우 공유기 BSSID 역추적 루틴을 가동함
   - 따라서 OS 런타임 레벨에서 TRANSPORT_WIFI(1)를 원천 차단하고 TRANSPORT_CELLULAR(0)를 활성화하며,
     SIM_STATE_READY(5), NETWORK_TYPE_LTE(13), 통신사 MCC/MNC(45008 KT)를 강제하여
     단말기가 100% 정상 개통된 순정 LTE 스마트폰 환경으로 인식되도록 보장함
"""

from typing import Optional


def build_network_hook(
    spoof_network_type: Optional[str] = "cellular",
    spoof_mcc_mnc: Optional[str] = "450_08"
) -> str:
    """
    네트워크 수송망 및 통신사 MCC/MNC 가로채기 Frida JS 코드 생성
    :param spoof_network_type: "cellular" (LTE 환경 강제 모의)
    :param spoof_mcc_mnc: "450_08" (KT LTE 통신사 코드)
    :return: 결합된 Frida JS 훅 코드 문자열
    """
    if not spoof_network_type and not spoof_mcc_mnc:
        return ""

    js_parts = []

    # -------------------------------------------------------------------------
    # 1. [OS Root] android.net.NetworkCapabilities (Wi-Fi 차단 -> Cellular 활성)
    # -------------------------------------------------------------------------
    if spoof_network_type:
        js_parts.append("""
          // [핵심 뿌리 1] Android OS NetworkCapabilities (Wi-Fi 차단 -> Cellular 활성)
          try {
            const NetworkCapabilities = frida_java_bridge_default.use("android.net.NetworkCapabilities");
            NetworkCapabilities.hasTransport.overload("int").implementation = function(transportType) {
              if (transportType === 1) { // 1 = TRANSPORT_WIFI (사무실 Wi-Fi 차단 모의)
                return false;
              }
              if (transportType === 0) { // 0 = TRANSPORT_CELLULAR (순수 이동통신 셀룰러망 활성)
                return true;
              }
              return this.hasTransport(transportType);
            };
            console.log("[+] Core Root Hooked: NetworkCapabilities.hasTransport (Wi-Fi OFF, Cellular ON)");
          } catch(e) {
            console.log("[-] NetworkCapabilities hook error: " + e);
          }
        """)

    # -------------------------------------------------------------------------
    # 2. [OS Root] android.telephony.TelephonyManager (KT LTE 45008 개통 상태 주입)
    # -------------------------------------------------------------------------
    if spoof_mcc_mnc:
        mcc_mnc_digits = spoof_mcc_mnc.replace("_", "") # "450_08" -> "45008"
        js_parts.append(f"""
          // [핵심 뿌리 2] Android OS TelephonyManager (KT LTE {mcc_mnc_digits} 정상 개통 모의)
          try {{
            const TelephonyManager = frida_java_bridge_default.use("android.telephony.TelephonyManager");

            // SIM 카드 통신사 코드 반환 (KT: 45008)
            TelephonyManager.getSimOperator.overload().implementation = function() {{
              return "{mcc_mnc_digits}";
            }};

            // 망 등록 통신사 코드 반환 (KT: 45008)
            TelephonyManager.getNetworkOperator.overload().implementation = function() {{
              return "{mcc_mnc_digits}";
            }};

            // SIM 카드 장착 상태 반환 (5 = SIM_STATE_READY)
            TelephonyManager.getSimState.overload().implementation = function() {{
              return 5;
            }};

            // 셀룰러 데이터 네트워크 타입 반환 (13 = NETWORK_TYPE_LTE)
            try {{
              TelephonyManager.getDataNetworkType.overload().implementation = function() {{
                return 13;
              }};
              TelephonyManager.getNetworkType.overload().implementation = function() {{
                return 13;
              }};
            }} catch(e) {{}}

            console.log("[+] Core Root Hooked: TelephonyManager (KT LTE {mcc_mnc_digits} READY)");
          }} catch(e) {{
            console.log("[-] TelephonyManager hook error: " + e);
          }}
        """)

    return "\n".join(js_parts)


__all__ = ["build_network_hook"]
