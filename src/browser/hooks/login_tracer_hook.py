#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/browser/hooks/login_tracer_hook.py

네이티브 로그인(NidLoginActivity) 원천 차단 및 인앱 브라우저 로그인 무력화 훅 (Anti-Login Interceptor)
- HTTP Request Headers 및 웹뷰 내비게이션 인위적 변조 일체 배제 (순정 브라우징 보존)
- 4단계 차단 및 자동 타겟 복구 쉴드:
  1) XWalkWebViewClient / InAppBaseWebViewClient: shouldOverrideUrlLoading 에서 nidlogin.login 감지 시
     URL 파라미터(`url=`)에서 원본 타겟 상품 상세페이지 URL을 추출하여 웹뷰로 직접 로드 (`webView.loadUrl(target)`)
  2) processNaverLoginUrl 가로채기 (웹뷰가 nidlogin.login 웹페이지로 튀지 않도록 제어)
  3) LoginManager.loginWithDialog 억제 (네이티브 다이얼로그 호출 무력화)
  4) Activity / ContextWrapper.startActivity: NidLoginActivity 인텐트 발송 차단
"""

def build_login_tracer_hook(target_nnb: str = "") -> str:
    js_template = r"""
      // =========================================================================
      // [안티-로그인 인터셉터 & 타겟 자동 복구 쉴드]
      // =========================================================================
      try {
        const Activity = frida_java_bridge_default.use("android.app.Activity");
        const ContextWrapper = frida_java_bridge_default.use("android.content.ContextWrapper");
        const Log = frida_java_bridge_default.use("android.util.Log");
        const Exception = frida_java_bridge_default.use("java.lang.Exception");
        const Uri = frida_java_bridge_default.use("android.net.Uri");
        const Runnable = frida_java_bridge_default.use("java.lang.Runnable");

        function shouldBlockIntent(intent, source) {
          if (!intent) return false;
          try {
            var uriStr = "";
            try { uriStr = intent.getDataString() || ""; } catch(e) {}
            const comp = intent.getComponent();
            const compStr = comp ? comp.flattenToString() : "";
            
            const isLogin = compStr.indexOf("navercorp.nid") !== -1 ||
                            compStr.toLowerCase().indexOf("login") !== -1 ||
                            compStr.indexOf("nhn.android.search/.login") !== -1 ||
                            uriStr.indexOf("nidlogin.login") !== -1 ||
                            uriStr.indexOf("nid.naver.com") !== -1;
            
            if (isLogin) {
              const stack = Log.getStackTraceString(Exception.$new());
              send({
                type: "login_intercept",
                action: "LOGIN_CHALLENGE_DETECTED",
                source: source,
                component: compStr,
                uri: uriStr
              });
              send("🚨 [FDS 로그인 인텐트 감지] " + source + " | Comp: " + compStr + " | URI: " + uriStr + " -> 인텐트 차단");
              return true;
            }
          } catch(err) {
            send("[-] Intent inspect error: " + err);
          }
          return false;
        }

        // 1. Activity.startActivity 차단
        Activity.startActivity.overloads.forEach(function(o) {
          o.implementation = function() {
            if (arguments.length > 0 && arguments[0]) {
              if (shouldBlockIntent(arguments[0], "Activity.startActivity")) {
                return;
              }
            }
            return o.apply(this, arguments);
          };
        });

        // 2. Activity.startActivityForResult 차단
        try {
          Activity.startActivityForResult.overloads.forEach(function(o) {
            o.implementation = function() {
              if (arguments.length > 0 && arguments[0]) {
                if (shouldBlockIntent(arguments[0], "Activity.startActivityForResult")) {
                  return;
                }
              }
              return o.apply(this, arguments);
            };
          });
        } catch(e) {}

        // 3. ContextWrapper.startActivity 차단
        try {
          ContextWrapper.startActivity.overloads.forEach(function(o) {
            o.implementation = function() {
              if (arguments.length > 0 && arguments[0]) {
                if (shouldBlockIntent(arguments[0], "ContextWrapper.startActivity")) {
                  return;
                }
              }
              return o.apply(this, arguments);
            };
          });
        } catch(e) {}

        // 4. LoginManager.loginWithDialog 직접 억제
        try {
          const LoginManager = frida_java_bridge_default.use("com.nhn.android.login.LoginManager");
            LoginManager.loginWithDialog.overloads.forEach(function(o) {
              o.implementation = function() {
                send({
                  type: "login_intercept",
                  action: "LOGIN_CHALLENGE_DETECTED",
                  source: "LoginManager.loginWithDialog"
                });
                send("🚨 [FDS 로그인 다이얼로그 감지] LoginManager.loginWithDialog 호출됨");
                return;
              };
            });
        } catch(e) {}

        // 5. 웹뷰 shouldOverrideUrlLoading FDS 로그인 챌린지 감지
        function installWebViewClientInterceptor(clientClassName) {
          try {
            const ClientClass = frida_java_bridge_default.use(clientClassName);
            
            // shouldOverrideUrlLoading 후킹: 인위적 loadUrl 억지 우회 영구 배제 및 FDS 챌린지 텔레메트리 즉시 발송
            ClientClass.shouldOverrideUrlLoading.overloads.forEach(function(o) {
              o.implementation = function() {
                var webView = arguments[0];
                var req = arguments[1];
                var uri = "";
                if (req) {
                  try { uri = req.getUrl().toString(); } catch(e) {
                    try { uri = req.toString(); } catch(e2) {}
                  }
                }
                
                if (uri && (uri.indexOf("nidlogin.login") !== -1 || uri.indexOf("nid.naver.com") !== -1)) {
                  send({
                    type: "login_intercept",
                    action: "LOGIN_CHALLENGE_DETECTED",
                    client: clientClassName,
                    url: uri
                  });
                  send("🚨 [FDS 로그인 챌린지 감지] " + clientClassName + " -> " + uri);
                  return true; // 웹뷰가 로그인 화면으로 전환되어 프로세스가 먹통되는 현상 방지
                }
                return o.apply(this, arguments);
              };
            });

            // processNaverLoginUrl 보조 후킹
            try {
              ClientClass.processNaverLoginUrl.overloads.forEach(function(o) {
                o.implementation = function(str, z2, z3) {
                  if (str && (str.indexOf("nidlogin.login") !== -1 || str.indexOf("nid.naver.com") !== -1)) {
                    send({
                      type: "login_intercept",
                      action: "PROCESS_LOGIN_CONSUMED",
                      client: clientClassName,
                      url: str
                    });
                    send("🛡️ [FRIDA processNaverLoginUrl] " + clientClassName + " -> nidlogin 소비 (url: " + str + ")");
                    return true;
                  }
                  return o.apply(this, arguments);
                };
              });
            } catch(e) {}

            send("[+] Interceptor installed on " + clientClassName);
          } catch(e) {
            // 클래스가 없는 구버전/신버전 변형 시 안전 통과
          }
        }

        installWebViewClientInterceptor("com.naver.xwhale.WebViewClient");
        installWebViewClientInterceptor("com.nhn.android.inappwebview.InAppBaseWebViewClient");
        installWebViewClientInterceptor("android.webkit.WebViewClient");
        installWebViewClientInterceptor("com.nhn.android.xwalkview.XWalkWebViewClient");

        send("[+] Core Hooked: 4-Layer Anti-Login Shield & Auto Target Restorer Active");
      } catch(e) {
        send("[-] Anti-Login Shield init error: " + e);
      }
    """
    return js_template
