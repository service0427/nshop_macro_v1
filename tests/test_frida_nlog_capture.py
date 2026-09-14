#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 Direct Frida Hook to Intercept and Display All nlogapp / nelog / Telemetry Packets
Hooks:
  - okhttp3.RealCall (all URLs and Post Bodies)
  - java.net.HttpURLConnection (all URLs and Post Bodies)
  - android.content.pm.PackageInfo (to see when firstInstallTime is queried)
"""

import os
import sys
import time
import subprocess
import frida

DEVICE_ID = "R3CR70KAZDM"

print("=" * 80)
print(f"🚀 [Frida 텔레메트리 & nlogapp 실시간 패킷 캡처] 단말기: {DEVICE_ID}")
print("=" * 80)

# Ensure frida-server is running
subprocess.run(["adb", "-s", DEVICE_ID, "shell", "su 0 chmod 777 /data/local/tmp/frida-server; su 0 /data/local/tmp/frida-server -l 0.0.0.0:27042 >/dev/null 2>&1 &"], check=False)
time.sleep(1.0)
subprocess.run(["adb", "-s", DEVICE_ID, "forward", "tcp:27042", "tcp:27042"], check=False)

mgr = frida.get_device_manager()
device = mgr.add_remote_device("127.0.0.1:27042")

# Force-stop app before fresh spawn
subprocess.run(["adb", "-s", DEVICE_ID, "shell", "am force-stop com.nhn.android.search"])
time.sleep(1.0)

print("[*] Spawning com.nhn.android.search via Frida...")
pid = device.spawn(["com.nhn.android.search"])
session = device.attach(pid)

js_code = """
Java.perform(function() {
    console.log("[✓] Telemetry & nlogapp Frida Interceptor Active!");

    // 1. Hook PackageInfo queries
    try {
        var ApplicationPackageManager = Java.use("android.app.ApplicationPackageManager");
        ApplicationPackageManager.getPackageInfo.overload('java.lang.String', 'int').implementation = function(pkg, flags) {
            var info = this.getPackageInfo(pkg, flags);
            if (pkg === "com.nhn.android.search") {
                send({
                    type: "PACKAGE_INFO_READ",
                    pkg: pkg,
                    firstInstallTime: info.firstInstallTime.value,
                    lastUpdateTime: info.lastUpdateTime.value
                });
            }
            return info;
        };
    } catch(e) {
        console.log("[-] PackageManager hook err: " + e);
    }

    // 2. Hook OkHttp3 RealCall
    try {
        var RealCall = Java.use("okhttp3.RealCall");
        RealCall.execute.implementation = function() {
            var req = this.request();
            var url = req.url().toString();
            var method = req.method();
            var bodyStr = "";
            var reqBody = req.body();
            if (reqBody !== null) {
                try {
                    var Buffer = Java.use("okio.Buffer");
                    var buffer = Buffer.$new();
                    reqBody.writeTo(buffer);
                    bodyStr = buffer.readUtf8();
                } catch(err) {}
            }
            if (url.indexOf("nlog") !== -1 || url.indexOf("l.naver") !== -1 || url.indexOf("cc.naver") !== -1 || url.indexOf("nelo") !== -1 || url.indexOf("stat") !== -1 || url.indexOf("beacon") !== -1 || url.indexOf("install") !== -1) {
                send({
                    type: "TELEMETRY_PACKET",
                    method: method,
                    url: url,
                    body: bodyStr
                });
            }
            return this.execute();
        };
    } catch(e) {
        console.log("[-] OkHttp3 RealCall hook err: " + e);
    }

    // 3. Hook HttpURLConnection
    try {
        var URL = Java.use("java.net.URL");
        URL.openConnection.overload().implementation = function() {
            var urlStr = this.toString();
            if (urlStr.indexOf("nlog") !== -1 || urlStr.indexOf("l.naver") !== -1 || urlStr.indexOf("cc.naver") !== -1 || urlStr.indexOf("nelo") !== -1) {
                send({
                    type: "URL_CONNECTION",
                    url: urlStr
                });
            }
            return this.openConnection();
        };
    } catch(e) {}
});
"""

nlog_events = []
pkg_info_events = []

def on_message(message, data):
    if message['type'] == 'send':
        payload = message['payload']
        p_type = payload.get('type')
        if p_type == 'PACKAGE_INFO_READ':
            pkg_info_events.append(payload)
            print(f"\n[📦 PackageInfo Read] firstInstallTime: {payload['firstInstallTime']} | lastUpdateTime: {payload['lastUpdateTime']}")
        elif p_type == 'TELEMETRY_PACKET':
            nlog_events.append(payload)
            print(f"\n[🌐 Telemetry] {payload['method']} {payload['url'][:110]}...")
            if payload['body']:
                print(f"   ↳ Body: {payload['body'][:250]}")
        elif p_type == 'URL_CONNECTION':
            print(f"\n[🔗 Connection] {payload['url']}")
    else:
        print(f"[{message['type']}] {message}")

script = session.create_script(js_code)
script.on('message', on_message)
script.load()

device.resume(pid)
print("[*] Naver App resumed! Running search '노트북'...")

# Give time for app startup telemetry
time.sleep(3.0)

# Input search '노트북'
subprocess.run(["adb", "-s", DEVICE_ID, "shell", "input tap 540 540"])
time.sleep(1.2)
subprocess.run(["adb", "-s", DEVICE_ID, "shell", "am broadcast -a ADB_INPUT_TEXT --es msg \"노트북\" 2>/dev/null; input keyevent 66"])
time.sleep(4.0)

# Scroll to trigger view impressions
subprocess.run(["adb", "-s", DEVICE_ID, "shell", "input swipe 540 1600 540 900 300"])
time.sleep(2.0)
subprocess.run(["adb", "-s", DEVICE_ID, "shell", "input swipe 540 900 540 1600 300"])
time.sleep(6.0)

print("\n" + "=" * 80)
print(f"📊 [TELEMETRY 캡처 최종 요약] 총 수집된 텔레메트리: {len(nlog_events)}건 | PackageInfo 조회: {len(pkg_info_events)}건")
print("=" * 80)
for idx, ev in enumerate(nlog_events[:10], 1):
    print(f"[{idx}] {ev['method']} {ev['url']}")
    if ev['body']:
        print(f"    Body: {ev['body']}")
    print("-" * 60)

session.detach()
