#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/browser/hooks/google_identity_hook.py

[GMS & OS 최심부 훅] 구글 계정(Google Account) 및 GMS 식별자(ADID / AppSetId) 완전 통제 모듈

[아키텍처 철칙 & 설계 원칙]:
1. 앱 레벨 땜빵 일체 배제:
   - 네이버 앱 내부 클래스(NTracker, ClientIdUtils, 쿠키 조작)를 전혀 건드리지 않음
   - 안드로이드 OS 표준 `android.accounts.AccountManager`와 GMS 표준 라이브러리 최심부만 타겟팅
2. 네이버 FDS 관통 핵심 원리:
   - 네이버 앱과 결제/인증 모듈은 단말기에 '구글 계정이 등록되어 있는가' 및 'AppSetId의 Scope가 1인가'를
     단말기 신뢰도(Trust Score) 평가의 핵심 가중치로 사용함
   - 이 모듈을 통해 실제 로그인을 거치지 않고도 OS 런타임 레벨에서 정상 구글 실사용자로 100% 인식시킴

[훅 대상 핵심 API 3종]:
- 1차: `android.accounts.AccountManager` (OS Root)
  * `getAccountsByType("com.google")` / `getAccounts()`
  * ➔ 가상 구글 계정(`xxx@gmail.com`) 객체를 반환하여 상시 구글 로그인 상태 에뮬레이션
- 2차: `com.google.android.gms.appset.AppSetIdInfo` (GMS Root)
  * `a()` (getId) ➔ 1회용 신생 AppSetId UUID 반환
  * `b()` (getScope) ➔ `1` (SCOPE_DEVELOPER) 강제 반환 (구글 계정 연동 최고 신뢰 등급)
- 3차: `com.google.android.gms.ads.identifier.AdvertisingIdClient$Info` (GMS Root)
  * `a()` (getId) ➔ 1회용 신생 ADID UUID 반환
  * `b()` (isLimitAdTrackingEnabled) ➔ `false` (광고 추적 제한 없는 정상 사용자 상태)
"""

from typing import Optional


def build_google_identity_hook(
    spoof_google_account: Optional[str] = None,
    spoof_dadd: Optional[str] = None,
    spoof_dadv: Optional[str] = None
) -> str:
    """
    가상 구글 계정 및 GMS 식별자 실시간 가로채기 Frida JS 코드 생성
    :param spoof_google_account: 1회용 생성된 실사용자형 구글 이메일 (예: minjun.kim94@gmail.com)
    :param spoof_dadd: 1회용 Google ADID UUID (쿠키 DA_DD와 100% 동기화)
    :param spoof_dadv: 1회용 Google AppSetId UUID (쿠키 DA_DV와 100% 동기화)
    :return: 결합된 Frida JS 훅 코드 문자열
    """
    if not spoof_google_account and not spoof_dadd and not spoof_dadv:
        return ""

    js_parts = []

    # -------------------------------------------------------------------------
    # 1. [OS Root] android.accounts.AccountManager (구글 계정 상시 로그인 모의)
    # -------------------------------------------------------------------------
    if spoof_google_account:
        js_parts.append(f"""
          // [핵심 뿌리 1] Android OS AccountManager (가상 구글 계정 상시 로그인 주입)
          try {{
            const AccountManager = frida_java_bridge_default.use("android.accounts.AccountManager");
            const Account = frida_java_bridge_default.use("android.accounts.Account");

            // type == 'com.google' 조회 시 가상 계정 객체 배열 반환
            AccountManager.getAccountsByType.overload("java.lang.String").implementation = function(type) {{
              if (type === "com.google") {{
                const fakeAccount = Account["$new"]("{spoof_google_account}", "com.google");
                return frida_java_bridge_default.array("android.accounts.Account", [fakeAccount]);
              }}
              return this.getAccountsByType(type);
            }};

            // 전체 계정 목록 조회 시 com.google 계정이 없으면 가상 계정 자동 병합 반환
            AccountManager.getAccounts.overload().implementation = function() {{
              const orig = this.getAccounts();
              let hasGoogle = false;
              for (let i = 0; i < orig.length; i++) {{
                if (orig[i].type.value === "com.google") {{
                  hasGoogle = true;
                  break;
                }}
              }}
              if (!hasGoogle) {{
                const fakeAccount = Account["$new"]("{spoof_google_account}", "com.google");
                return frida_java_bridge_default.array("android.accounts.Account", [fakeAccount]);
              }}
              return orig;
            }};
            console.log("[+] Core Root Hooked: AccountManager (Google Account: {spoof_google_account})");
            send({{ type: "hook_verification", hook: "AccountManager", status: "OK", value: "{spoof_google_account}" }});
          }} catch(e) {{
            console.log("[-] AccountManager hook error: " + e);
            send({{ type: "hook_verification", hook: "AccountManager", status: "ERROR", error: String(e) }});
          }}
        """)

    # -------------------------------------------------------------------------
    # 2. [GMS Root] com.google.android.gms.appset.AppSetIdInfo (AppSetId & Scope 1)
    # -------------------------------------------------------------------------
    if spoof_dadv:
        js_parts.append(f"""
          // [핵심 뿌리 2] GMS AppSetIdInfo (UUID 및 SCOPE_DEVELOPER 강제 승격)
          try {{
            const AppSetIdInfo = frida_java_bridge_default.use("com.google.android.gms.appset.AppSetIdInfo");
            
            // a() -> getId() : 1회용 신생 UUID 반환
            AppSetIdInfo.a.implementation = function() {{
              return "{spoof_dadv}";
            }};
            
            // b() -> getScope() : 구글 계정 연동 최고 신뢰 등급인 1 (SCOPE_DEVELOPER) 강제 반환 (2=SCOPE_APP 방지)
            AppSetIdInfo.b.implementation = function() {{
              return 1;
            }};
            console.log("[+] Core Root Hooked: GMS AppSetIdInfo (AppSetId: {spoof_dadv}, Scope: 1 SCOPE_DEVELOPER)");
            send({{ type: "hook_verification", hook: "AppSetIdInfo", status: "OK", value: "{spoof_dadv}" }});
          }} catch(e) {{
            console.log("[-] AppSetIdInfo hook error: " + e);
            send({{ type: "hook_verification", hook: "AppSetIdInfo", status: "ERROR", error: String(e) }});
          }}
        """)

    # -------------------------------------------------------------------------
    # 3. [GMS Root] com.google.android.gms.ads.identifier.AdvertisingIdClient$Info (ADID)
    # -------------------------------------------------------------------------
    if spoof_dadd:
        js_parts.append(f"""
          // [핵심 뿌리 3] GMS AdvertisingIdClient$Info (ADID UUID 및 LAT=false 반환)
          try {{
            const Info = frida_java_bridge_default.use("com.google.android.gms.ads.identifier.AdvertisingIdClient$Info");
            
            // a() -> getId() : 1회용 신생 ADID UUID 반환
            Info.a.implementation = function() {{
              return "{spoof_dadd}";
            }};
            
            // b() -> isLimitAdTrackingEnabled() : false (광고 추적 차단 없는 정상 실사용자 상태)
            Info.b.implementation = function() {{
              return false;
            }};
            console.log("[+] Core Root Hooked: GMS AdvertisingIdClient (ADID: {spoof_dadd}, LAT: false)");
            send({{ type: "hook_verification", hook: "AdvertisingIdClient", status: "OK", value: "{spoof_dadd}" }});
          }} catch(e) {{
            console.log("[-] AdvertisingIdClient hook error: " + e);
            send({{ type: "hook_verification", hook: "AdvertisingIdClient", status: "ERROR", error: String(e) }});
          }}
        """)

    return "\n".join(js_parts)


__all__ = ["build_google_identity_hook"]
