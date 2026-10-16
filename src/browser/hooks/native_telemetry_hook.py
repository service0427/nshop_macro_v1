#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/browser/hooks/native_telemetry_hook.py

[Priority 7] 네이버 앱 네이티브 텔레메트리(nlogapp / OkHttp / HttpURLConnection) 인프로세스 스니퍼
- 프록시(mitmproxy) 없이 100% 순수 HTTP/3 (QUIC / UDP 443) 통신을 온전히 보존
- 네이티브 자바 단에서 발송되는 nlog.naver.com/nlogapp, /nlogapp/performance, /nlogapp/anonymous 요청 감지
"""

def build_native_telemetry_hook() -> str:
    return r"""
      // =========================================================================
      // [Priority 7] Native Telemetry Sniffer (nlog.naver.com / nlogapp)
      // =========================================================================
      try {
        // 1. Android Java HttpURLConnection Sniffing
        try {
          const HttpURLConnection = frida_java_bridge_default.use("java.net.HttpURLConnection");
          HttpURLConnection.getOutputStream.implementation = function() {
            try {
              const u = this.getURL().toString();
              if (u.indexOf("nlog.naver.com") !== -1 || u.indexOf("nlogapp") !== -1) {
                const method = this.getRequestMethod();
                send({
                  type: "native_telemetry",
                  url: u,
                  method: method,
                  headers: this.getRequestProperties().toString()
                });
              }
            } catch(e) {}
            return this.getOutputStream();
          };
        } catch(e) {}

        // 2. OkHttp RealCall Sniffing
        try {
          const RealCall = frida_java_bridge_default.use("okhttp3.RealCall");
          RealCall.execute.implementation = function() {
            try {
              const req = this.request();
              const u = req.url().toString();
              if (u.indexOf("nlog.naver.com") !== -1 || u.indexOf("nlogapp") !== -1) {
                send({
                  type: "native_telemetry",
                  url: u,
                  method: req.method()
                });
              }
            } catch(e) {}
            return this.execute();
          };
        } catch(e) {}
      } catch(e) {}
    """
