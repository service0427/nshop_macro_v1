#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/browser/hooks/identity_hook.py

[OS 최심부 훅] 안드로이드 기기 고유 식별자(SSAID / android_id) 완전 통제 모듈

[아키텍처 철칙 & 설계 원칙]:
1. OS 프레임워크 표준 API 최심부 타겟팅:
   - 앱 내부 클래스(NTracker, ClientIdUtils, LoginPreference 등)의 땜빵 코드를 일체 배제
   - 안드로이드 OS의 `android.provider.Settings$Secure.getString(cr, "android_id")`만 직접 가로챔
2. NAPP_DI 자동 파생 메커니즘:
   - 네이버 앱 내부의 모든 서브시스템(NTracker, LCS, Nelo, XWhale 브라우저)은 기동 시
     Settings.Secure.getString(cr, "android_id")를 1회 호출하고, 그 결과값의 MD5 해시를 취해
     자체 식별자인 `NAPP_DI` 및 `DeviceID`를 자동으로 연산/생성함
   - 따라서 이 OS Root 훅 하나만으로 네이버 앱 전역의 모든 파생 식별자가 100% 동기화되어 통제됨
3. 우선순위:
   - 번들러에서 2순위로 기동 (OS 부트스트랩 및 Integrity 체크 직후 주입)
"""

from typing import Optional


def build_identity_hook(spoof_ssaid: Optional[str] = None) -> str:
    """
    Android OS 표준 android_id (SSAID) 실시간 가로채기 Frida JS 코드 생성
    :param spoof_ssaid: 16자리 1회용 무작위 헥사 문자열 (예: 3237c4c0804fbf20)
    :return: 결합된 Frida JS 훅 코드 문자열
    """
    if not spoof_ssaid:
        return ""

    return f"""
      // =========================================================================
      // [OS Root] Android OS Settings.Secure.getString("android_id") 실시간 가로채기
      // =========================================================================
      try {{
        const Secure = frida_java_bridge_default.use("android.provider.Settings$Secure");

        // 1. 표준 ContentResolver를 통한 android_id 조회 가로채기
        Secure.getString.overload("android.content.ContentResolver", "java.lang.String").implementation = function(cr, name) {{
          if (name === "android_id") {{
            return "{spoof_ssaid}";
          }}
          return this.getString(cr, name);
        }};

        // 2. 다중 사용자 환경(Multi-User / Work Profile) getStringForUser 호환 가로채기
        try {{
          Secure.getStringForUser.overload("android.content.ContentResolver", "java.lang.String", "int").implementation = function(cr, name, u) {{
            if (name === "android_id") {{
              return "{spoof_ssaid}";
            }}
            return this.getStringForUser(cr, name, u);
          }};
        }} catch(e) {{}}

        console.log("[+] Core Root Hooked: Settings.Secure (android_id: {spoof_ssaid})");
      }} catch(e) {{
        console.log("[-] Settings.Secure hook error: " + e);
      }}
    """


__all__ = ["build_identity_hook"]
