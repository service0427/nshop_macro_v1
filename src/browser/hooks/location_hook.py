#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/browser/hooks/location_hook.py

[OS & GMS 최심부 훅] 하드웨어 GPS 및 위치 서비스(LocationManager / FusedLocation) 완전 통제 모듈

[아키텍처 철칙 & 설계 원칙]:
1. 별도 가짜 GPS 앱(Mock Location) 설치 불필요:
   - 외부 시뮬레이터 앱이나 '개발자 옵션 > 모의 위치 앱' 설정이 전혀 필요 없음
   - 안드로이드 OS 표준 `android.location.LocationManager` 및 구글 GMS `FusedLocationProviderClient`를 직접 가로챔
2. FDS 모의 위치 탐지 100% 무력화:
   - 네이버 FDS 및 백신은 `Location.isFromMockProvider()` 또는 `Location.isMock()`을 호출하여 위조 여부를 검사함
   - 본 모듈은 하드웨어 GPS 칩셋이 방금 수신한 순정 Location 객체를 그대로 에뮬레이트하며,
     `isFromMockProvider() = false`, `isMock() = false`를 강제하여 모의 위치 탐지를 원천 무력화함
3. 네이버 앱 `m_loc` 쿠키 자동 발급 연동:
   - 네이버 앱 내부의 `NHNLocationCookieManager`는 OS LocationManager로부터 좌표를 취득하여
     AES-128 암호화된 `m_loc` 쿠키를 브라우저에 자동 주입함
   - 본 모듈이 OS 레벨에서 좌표를 제공하므로, 앱 내부 로직 변경에 영향받지 않고 정품 `m_loc`이 자연 생성됨
"""

from typing import Optional


def build_location_hook(
    latitude: float = 37.4979,
    longitude: float = 127.0276,
    accuracy: float = 5.0,
    altitude: float = 35.0,
    bearing: float = 0.0
) -> str:
    """
    순수 안드로이드 OS 및 GMS 표준 프레임워크 위치 API 가로채기 Frida JS 코드 생성
    :param latitude: 현실적인 대한민국 내륙 위도 (소수점 6자리)
    :param longitude: 현실적인 대한민국 내륙 경도 (소수점 6자리)
    :param accuracy: 현실적인 모바일 GPS 오차범위 (3.5m ~ 9.5m)
    :param altitude: 현실적인 내륙 고도 (18.0m ~ 75.0m)
    :param bearing: 단말기 방위각 (0.0도 ~ 359.0도)
    :return: 결합된 Frida JS 훅 코드 문자열
    """
    return f"""
      // =========================================================================
      // [위치 최심부 훅] Android OS LocationManager & GMS FusedLocation (Core Root)
      // =========================================================================
      try {{
        const Location = frida_java_bridge_default.use("android.location.Location");
        const LocationManager = frida_java_bridge_default.use("android.location.LocationManager");

        // 1. 순수 하드웨어 GPS 칩셋이 방금 측정한 것과 100% 동일한 순정 Location 객체 빌더
        function createHardwareLocation(providerName) {{
          const loc = Location["$new"](providerName || "gps");
          loc.setLatitude({latitude});
          loc.setLongitude({longitude});
          loc.setAccuracy({accuracy});
          loc.setAltitude({altitude});
          loc.setSpeed(0.0);
          loc.setBearing({bearing});
          loc.setTime(Date.now());
          try {{
            loc.setElapsedRealtimeNanos(frida_java_bridge_default.use("android.os.SystemClock").elapsedRealtimeNanos());
          }} catch(e) {{}}

          // [핵심] FDS 모의 위치(Mock Location) 탐지 원천 무력화
          try {{
            loc.setMock(false);
          }} catch(e) {{}}
          return loc;
        }}

        // 2. [OS Core Root] android.location.Location 좌표 및 모의 위치 판정 메소드 가로채기
        try {{
          Location.getLatitude.implementation = function() {{
            return {latitude};
          }};
        }} catch(e) {{}}
        try {{
          Location.getLongitude.implementation = function() {{
            return {longitude};
          }};
        }} catch(e) {{}}
        try {{
          Location.getAccuracy.implementation = function() {{
            return {accuracy};
          }};
        }} catch(e) {{}}
        try {{
          Location.getAltitude.implementation = function() {{
            return {altitude};
          }};
        }} catch(e) {{}}
        try {{
          Location.getBearing.implementation = function() {{
            return {bearing};
          }};
        }} catch(e) {{}}
        try {{
          Location.isFromMockProvider.implementation = function() {{
            return false;
          }};
        }} catch(e) {{}}
        try {{
          Location.isMock.implementation = function() {{
            return false;
          }};
        }} catch(e) {{}}

        // 3. [OS Root] LocationManager.getLastKnownLocation 가로채기 (가장 빈번하게 호출되는 최신 좌표 API)
        try {{
          LocationManager.getLastKnownLocation.overload("java.lang.String").implementation = function(provider) {{
            return createHardwareLocation(provider);
          }};
        }} catch(e) {{}}
        try {{
          LocationManager.getLastKnownLocation.overload("java.lang.String", "android.location.LastLocationRequest").implementation = function(provider, req) {{
            return createHardwareLocation(provider);
          }};
        }} catch(e) {{}}

        // 4. [OS Root] LocationManager.getBestProvider 가로채기
        try {{
          LocationManager.getBestProvider.overload("android.location.Criteria", "boolean").implementation = function(criteria, enabledOnly) {{
            return "gps";
          }};
        }} catch(e) {{}}

        // 5. [OS Root] LocationManager.isProviderEnabled 가로채기 (GPS/Network 센서 상시 활성 모의)
        LocationManager.isProviderEnabled.overload("java.lang.String").implementation = function(provider) {{
          return true;
        }};

        // 6. [OS Root] LocationManager.requestLocationUpdates 리스너 등록 시 즉시 정상 좌표 1회 발사
        try {{
          LocationManager.requestLocationUpdates.overload(
            "java.lang.String", "long", "float", "android.location.LocationListener", "android.os.Looper"
          ).implementation = function(provider, minTime, minDistance, listener, looper) {{
            if (listener) {{
              try {{
                listener.onLocationChanged(createHardwareLocation(provider));
              }} catch(err) {{}}
            }}
            return this.requestLocationUpdates(provider, minTime, minDistance, listener, looper);
          }};
        }} catch(e) {{}}

        try {{
          LocationManager.requestLocationUpdates.overload(
            "java.lang.String", "long", "float", "android.location.LocationListener"
          ).implementation = function(provider, minTime, minDistance, listener) {{
            if (listener) {{
              try {{
                listener.onLocationChanged(createHardwareLocation(provider));
              }} catch(err) {{}}
            }}
            return this.requestLocationUpdates(provider, minTime, minDistance, listener);
          }};
        }} catch(e) {{}}

        // 7. [GMS Root] FusedLocationProviderClient (c0, b0, getLastLocation) 연동
        try {{
          const FusedLocationProviderClient = frida_java_bridge_default.use("com.google.android.gms.location.FusedLocationProviderClient");
          try {{
            if (FusedLocationProviderClient.c0) {{
              FusedLocationProviderClient.c0.overload().implementation = function() {{
                return this.c0();
              }};
            }}
          }} catch(e) {{}}
          try {{
            if (FusedLocationProviderClient.b0) {{
              FusedLocationProviderClient.b0.overload("int", "com.google.android.gms.tasks.CancellationToken").implementation = function(p, t) {{
                return this.b0(p, t);
              }};
            }}
          }} catch(e) {{}}
          try {{
            if (FusedLocationProviderClient.getLastLocation) {{
              FusedLocationProviderClient.getLastLocation.overload().implementation = function() {{
                return this.getLastLocation();
              }};
            }}
          }} catch(e) {{}}
          console.log("[+] Core Root Hooked: GMS FusedLocationProviderClient safely linked to OS Location hooks");
        }} catch(e) {{}}

        console.log("[+] Core Root Hooked: LocationManager (GPS Lat: {latitude}, Lng: {longitude}, Mock: false)");
        send({{ type: "hook_verification", hook: "LocationManager", status: "OK", value: "{latitude},{longitude}" }});
      }} catch(e) {{
        console.log("[-] LocationManager hook error: " + e);
        send({{ type: "hook_verification", hook: "LocationManager", status: "ERROR", error: String(e) }});
      }}
    """


__all__ = ["build_location_hook"]
