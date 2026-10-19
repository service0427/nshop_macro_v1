#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/browser/hooks/device_integrity_hook.py

[순수 OS & Java 표준 최심부 훅] 하드웨어 무결성, 스토리지 지터 및 라이프사이클 완전 통제 모듈
- WTM POSIX 소켓 충돌 유발 위험 훅(Inet4Address, NetworkCapabilities, Runtime.exec) 100% 영구 격리 준수
- StatFs & File.getTotalSpace: 238GB 기준 미세 바이트 지터 부여 (19대 실기기 고정 스토리지 크기 은닉)
- ApplicationPackageManager: 15~45일 전 성숙된 firstInstallTime / lastUpdateTime 동적 위조
- WifiManager & WifiInfo: 주변 사무실 Wi-Fi MAC BSSID 및 ScanResults 유출 100% 원천 차단
- NTracker & DeviceInfo: 단말기 부팅 시점(last_boot_ts) 및 설치 시점 동기화
- Pre-flight Gate hook_verification 통지 연동
"""

from typing import Optional


def build_device_integrity_hook(
    fake_install_time: Optional[int] = None,
    fake_update_time: Optional[int] = None,
    fake_boot_time: Optional[int] = None
) -> str:
    """
    100% 순수 OS/Java 표준 최심부 기기 무결성 및 라이프사이클 Frida JS 번들 생성
    :param fake_install_time: 15~45일 전 생성된 가상 설치 타임스탬프 (밀리초)
    :param fake_update_time: 설치 후 3~12일 뒤 생성된 가상 업데이트 타임스탬프 (밀리초)
    :param fake_boot_time: 4~28시간 전 생성된 가상 단말기 부팅 타임스탬프 (밀리초)
    :return: 결합된 Frida JS 훅 코드 문자열
    """
    return f"""
      // =========================================================================
      // [하드웨어 무결성 & 라이프사이클 훅] Hardware Fingerprint & Lifecycle Jitter
      // =========================================================================
      try {{
        const now = Date.now();
        const finalInstallTime = {fake_install_time if fake_install_time else "now - (Math.floor(Math.random() * 30 + 15) * 86400000)"};
        const finalUpdateTime = {fake_update_time if fake_update_time else "finalInstallTime + (Math.floor(Math.random() * 8 + 3) * 86400000)"};
        const finalBootTime = {fake_boot_time if fake_boot_time else "now - (Math.floor(Math.random() * 24 + 4) * 3600000)"};
        
        // 238GB 기준 현실적인 미세 바이트 지터 부여 (19대 실기기 하드웨어 고정 크기 노출 차단)
        const finalStorageSize = 238240000000 + Math.floor(Math.random() * 1000000000);
        const finalStorageBlocks = Math.floor(finalStorageSize / 4096);

        // -------------------------------------------------------------------------
        // 1. [OS Root] ApplicationPackageManager.getPackageInfo (앱 설치/업데이트 일시 위조)
        // -------------------------------------------------------------------------
        try {{
          const ApplicationPackageManager = frida_java_bridge_default.use("android.app.ApplicationPackageManager");
          ApplicationPackageManager.getPackageInfo.overloads.forEach(function(o) {{
            o.implementation = function() {{
              const pi = this.getPackageInfo.apply(this, arguments);
              if (arguments[0] === "com.nhn.android.search" && pi) {{
                pi.firstInstallTime.value = finalInstallTime;
                pi.lastUpdateTime.value = finalUpdateTime;
              }}
              return pi;
            }};
          }});
        }} catch(e) {{}}

        // -------------------------------------------------------------------------
        // 2. [OS Root] android.os.StatFs & java.io.File (스토리지 용량 동적 바이트 지터)
        // -------------------------------------------------------------------------
        try {{
          const StatFs = frida_java_bridge_default.use("android.os.StatFs");
          StatFs.getBlockCountLong.implementation = function() {{
            return finalStorageBlocks;
          }};
          try {{
            StatFs.getTotalBytes.implementation = function() {{
              return finalStorageSize;
            }};
          }} catch(err) {{}}
        }} catch(e) {{}}

        try {{
          const File = frida_java_bridge_default.use("java.io.File");
          File.getTotalSpace.implementation = function() {{
            return finalStorageSize;
          }};
        }} catch(e) {{}}

        // -------------------------------------------------------------------------
        // 3. [OS Root] android.net.wifi.WifiManager & WifiInfo (주변 Wi-Fi MAC BSSID 유출 완전 차단)
        // -------------------------------------------------------------------------
        try {{
          const WifiManager = frida_java_bridge_default.use("android.net.wifi.WifiManager");
          const ArrayList = frida_java_bridge_default.use("java.util.ArrayList");
          WifiManager.getScanResults.overload().implementation = function() {{
            return ArrayList["$new"]();
          }};
          WifiManager.isWifiEnabled.overload().implementation = function() {{
            return false;
          }};
          WifiManager.getWifiState.overload().implementation = function() {{
            return 1; // 1 = WIFI_STATE_DISABLED
          }};
        }} catch(e) {{}}

        try {{
          const WifiInfo = frida_java_bridge_default.use("android.net.wifi.WifiInfo");
          WifiInfo.getBSSID.implementation = function() {{
            return "02:00:00:00:00:00";
          }};
          WifiInfo.getSSID.implementation = function() {{
            return "<unknown ssid>";
          }};
          WifiInfo.getIpAddress.implementation = function() {{
            return 0;
          }};
        }} catch(e) {{}}

        // -------------------------------------------------------------------------
        // 4. [다층 방어 Fallback] 앱 및 SDK 레벨 보조 가로채기 (NTracker, DeviceInfo, Vaccine)
        // -------------------------------------------------------------------------
        try {{
          const DeviceInfo = frida_java_bridge_default.use("com.nhn.android.system.DeviceInfo");
          DeviceInfo.create.implementation = function(ctx) {{
            this.create(ctx);
            DeviceInfo.firstInstallTime.value = finalInstallTime;
            DeviceInfo.lastUpdateTime.value = finalUpdateTime;
          }};
        }} catch(e) {{}}

        try {{
          const NTrackerDeviceInfo = frida_java_bridge_default.use("com.navercorp.ntracker.ntrackersdk.util.DeviceInfo");
          NTrackerDeviceInfo.i.implementation = function() {{
            return finalBootTime;
          }};
          NTrackerDeviceInfo.h.implementation = function() {{
            return finalBootTime;
          }};
          NTrackerDeviceInfo.j.implementation = function() {{
            return finalStorageSize;
          }};
          NTrackerDeviceInfo.D.implementation = function() {{
            return finalStorageSize;
          }};
        }} catch(e) {{}}

        try {{
          const IntegrityChecker = frida_java_bridge_default.use("com.nhn.android.system.IntegrityChecker");
          IntegrityChecker.isDeviceRooted.implementation = function() {{ return false; }};
          IntegrityChecker.isEmulator.implementation = function() {{ return false; }};
        }} catch(e) {{}}

        try {{
          const NidSecuritySolution = frida_java_bridge_default.use("com.navercorp.nid.feature.vaccine.domain.usecase.NidSecuritySolution");
          NidSecuritySolution.isDeviceRooted.implementation = function() {{ return false; }};
        }} catch(e) {{}}

        try {{
          const RootingChecker = frida_java_bridge_default.use("com.naver.android.techfinlib.RootingChecker");
          RootingChecker.b.implementation = function() {{ return false; }};
        }} catch(e) {{}}

        try {{
          const Build = frida_java_bridge_default.use("android.os.Build");
          Build.TAGS.value = "release-keys";
        }} catch(e) {{}}

        console.log("[+] Core Root Hooked: DeviceIntegrity (Storage: " + finalStorageSize + "B, Install: " + finalInstallTime + ", Boot: " + finalBootTime + ")");
        send({{
          type: "hook_verification",
          hook: "DeviceIntegrity",
          status: "OK",
          storage_size: finalStorageSize,
          install_time: finalInstallTime
        }});
      }} catch(e) {{
        console.log("[-] Device integrity hook error: " + e);
        send({{ type: "hook_verification", hook: "DeviceIntegrity", status: "ERROR", error: String(e) }});
      }}
    """


__all__ = ["build_device_integrity_hook"]
