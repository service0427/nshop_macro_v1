/* 
   Network Hook (V3 Refactored)
   - Exclusively handles Certificate Pinning & SSL Bypass.
   - Bypasses SSL Pinning (Native + OkHttp3 + TrustManager + SSLContext + Chromium).
*/

console.log("[*] Network Hook Script Loaded (Pure SSL Bypass)");

function hook_native_ssl() {
    Process.enumerateModules().forEach(function (m) {
        var name = m.name.toLowerCase();
        if (name.indexOf("ssl") !== -1 || name.indexOf("crypto") !== -1 || name.indexOf("cronet") !== -1 || name.indexOf("nmap") !== -1) {
            try {
                var exports = m.enumerateExports();
                exports.forEach(function (exp) {
                    var n = exp.name;
                    if (n.indexOf("SSL_CTX_set_custom_verify") !== -1 || n.indexOf("SSL_set_custom_verify") !== -1 || n.indexOf("SSL_set_verify") !== -1) {
                        try {
                            Interceptor.attach(exp.address, { onEnter: function (args) { args[1] = ptr(0); } });
                        } catch (e) { }
                    }
                    if (n === "SSL_get_verify_result") {
                        try {
                            Interceptor.attach(exp.address, {
                                onLeave: function (retval) {
                                    retval.replace(ptr(0));
                                }
                            });
                        } catch (e) { }
                    }
                });
            } catch (e) { }
        }
    });
}

function hook_java_all() {
    Java.perform(function () {
        try {
            var ActivityThread = Java.use('android.app.ActivityThread');
            var context = ActivityThread.currentApplication().getApplicationContext();
            Java.classFactory.cacheDir = context.getCacheDir().getAbsolutePath();
        } catch (e) {
            Java.classFactory.cacheDir = "/data/local/tmp";
        }

        // --- 1. TrustManager Implementation (The Core Bypass) ---
        var X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
        var SSLContext = Java.use('javax.net.ssl.SSLContext');

        var TrustManager = null;
        try {
            TrustManager = Java.registerClass({
                name: 'com.example.TrustManager',
                implements: [X509TrustManager],
                methods: {
                    checkClientTrusted: function (chain, authType) { },
                    checkServerTrusted: function (chain, authType) { },
                    getAcceptedIssuers: function () { return []; }
                }
            });
        } catch (e) {
            console.log("[-] Java.registerClass failed. Proceeding without custom TrustManager array.");
        }

        try {
            var TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
            var Arrays = Java.use("java.util.Arrays");
            try {
                TrustManagerImpl.verifyChain.implementation = function () {
                    return arguments[0];
                };
            } catch (e1) {}
            try {
                TrustManagerImpl.checkTrustedRecursive.implementation = function () {
                    return Arrays.asList(arguments[0]);
                };
            } catch (e2) {}
            try {
                TrustManagerImpl.checkServerTrusted.overload('[Ljava.security.cert.X509Certificate;', 'java.lang.String').implementation = function (certs, authType) {
                    return Arrays.asList(certs);
                };
            } catch(e3) {}
            try {
                TrustManagerImpl.checkServerTrusted.overload('[Ljava.security.cert.X509Certificate;', 'java.lang.String', 'java.lang.String').implementation = function (certs, authType, host) {
                    return Arrays.asList(certs);
                };
            } catch(e4) {}
        } catch (e) { }

        // --- 2. SSLContext Hook ---
        try {
            if (TrustManager) {
                var TrustManagers = [TrustManager.$new()];
                var SSLContext_init = SSLContext.init.overload('[Ljavax.net.ssl.KeyManager;', '[Ljavax.net.ssl.TrustManager;', 'java.security.SecureRandom');
                SSLContext_init.implementation = function (keyManager, trustManager, secureRandom) {
                    SSLContext_init.call(this, keyManager, TrustManagers, secureRandom);
                };
            }
        } catch (e) { }

        // --- 3. OkHttp3 CertificatePinner Bypass ---
        try {
            var CertificatePinner = Java.use("okhttp3.CertificatePinner");
            CertificatePinner.check.overload('java.lang.String', 'java.util.List').implementation = function (hostname, certs) {
                return;
            };
        } catch (e) { }

        // --- 4. Android WebView & Cronet (Chromium X509Util) SSL Bypass ---
        try {
            var X509Util = Java.use("org.chromium.net.X509Util");
            var emptyList = Java.use("java.util.Collections").emptyList();
            var AndroidCertVerifyResult = null;
            try { AndroidCertVerifyResult = Java.use("org.chromium.net.AndroidCertVerifyResult"); } catch(e) {}

            var methods = X509Util.class.getDeclaredMethods();
            for (var i = 0; i < methods.length; i++) {
                if (methods[i].getName() === "verifyServerCertificates") {
                    var paramTypes = methods[i].getParameterTypes();
                    var typeNames = [];
                    for (var j = 0; j < paramTypes.length; j++) {
                        typeNames.push(paramTypes[j].getName());
                    }
                    try {
                        X509Util.verifyServerCertificates.overload.apply(X509Util.verifyServerCertificates, typeNames).implementation = function() {
                            if (AndroidCertVerifyResult) {
                                try { return AndroidCertVerifyResult.$new(0); } catch(e) {}
                                try { return AndroidCertVerifyResult.$new(0, true, emptyList); } catch(e) {}
                            }
                            return emptyList;
                        };
                    } catch(err) {}
                }
            }
        } catch (e) { }

        try {
            var TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
            TrustManagerImpl.verifyChain.implementation = function (untrustedChain, trustAnchorChain, host, clientAuth, ocspData, tlsSctData) {
                return untrustedChain;
            };
        } catch (e) { }

        try {
            var SslErrorHandler = Java.use("android.webkit.SslErrorHandler");
            SslErrorHandler.cancel.implementation = function () {
                this.proceed();
            };
            var WebViewClient = Java.use("android.webkit.WebViewClient");
            WebViewClient.onReceivedSslError.implementation = function (view, handler, error) {
                handler.proceed();
            };
        } catch (e) { }
        
        console.log("[+] All Network SSL Bypasses applied");
    });
}

function hook_safe_ssl_bypass() {
    if (!Java.available) return;
    Java.perform(function() {
        // 1. OkHttp CertificatePinner
        try {
            var CertificatePinner = Java.use("okhttp3.CertificatePinner");
            CertificatePinner.check.overload('java.lang.String', 'java.util.List').implementation = function (hostname, certs) { return; };
        } catch (e) { }

        // 2. Chromium X509Util (Old Cronet)
        try {
            var X509Util = Java.use("org.chromium.net.X509Util");
            var AndroidCertVerifyResult = Java.use("org.chromium.net.AndroidCertVerifyResult");
            var emptyList = Java.use("java.util.Collections").emptyList();
            var verifyMethod = X509Util.verifyServerCertificates.overload('[[B', 'java.lang.String', 'java.lang.String');
            var retType = "org.chromium.net.AndroidCertVerifyResult";
            try {
                if (verifyMethod.returnType && verifyMethod.returnType.className) {
                    retType = verifyMethod.returnType.className;
                }
            } catch (err) { }

            verifyMethod.implementation = function (chain, authType, host) {
                if (retType === "org.chromium.net.AndroidCertVerifyResult") {
                    try {
                        return AndroidCertVerifyResult.$new(0);
                    } catch (err) {
                        try {
                            return AndroidCertVerifyResult.$new(0, true, emptyList);
                        } catch (err2) {
                            return null;
                        }
                    }
                } else {
                    return emptyList;
                }
            };
        } catch (e) { }

        // 3. Android WebView Universal Bypass (Chrome Update Proof)
        try {
            var SslErrorHandler = Java.use("android.webkit.SslErrorHandler");
            SslErrorHandler.cancel.implementation = function () {
                this.proceed();
            };
            SslErrorHandler.proceed.implementation = function () {
                this.proceed();
            };
        } catch (e) { }

        // 4. TrustManagerImpl (Safe Hook, doesn't touch SSLContext to prevent ExoPlayer crash)
        try {
            var TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
            TrustManagerImpl.verifyChain.implementation = function (untrustedChain, trustAnchorChain, host, clientAuth, ocspData, tlsSctData) {
                return untrustedChain;
            };
            if (TrustManagerImpl.checkServerTrusted) {
                try {
                    TrustManagerImpl.checkServerTrusted.overload('[Ljava.security.cert.X509Certificate;', 'java.lang.String').implementation = function (chain, authType) {
                        return Java.use("java.util.ArrayList").$new();
                    };
                } catch(e) {}
                try {
                    TrustManagerImpl.checkServerTrusted.overload('[Ljava.security.cert.X509Certificate;', 'java.lang.String', 'java.lang.String').implementation = function (chain, authType, host) {
                        return Java.use("java.util.ArrayList").$new();
                    };
                } catch(e) {}
                try {
                    TrustManagerImpl.checkServerTrusted.overload('[Ljava.security.cert.X509Certificate;', 'java.lang.String', 'java.lang.String', 'java.lang.String').implementation = function (chain, authType, host, ocspData) {
                        return Java.use("java.util.ArrayList").$new();
                    };
                } catch(e) {}
            }
        } catch (e) { }

        console.log("[+] Safe SSL Bypasses applied to fix Validity & WebView issues");
    });
}

function hook_anti_bot_fingerprinting() {
    if (!Java.available) return;
    
    var noMitm = false;
    if (typeof NMAP_PROFILE !== 'undefined' && NMAP_PROFILE && NMAP_PROFILE.no_mitm === "true") {
        noMitm = true;
    }
    
    Java.perform(function() {
        // 1. Hook Cronet Engine to disable HTTP/3 (QUIC) and force fallback to HTTP/2/TCP (Only if proxy is active)
        if (!noMitm) {
            try {
                var CronetBuilder = Java.use("org.chromium.net.CronetEngine$Builder");
                
                // Hook enableQuic
                CronetBuilder.enableQuic.implementation = function(value) {
                    console.log("[Frida 🤖] Cronet: enableQuic called. Forcing FALSE to ensure HTTP/3 redirects through local proxy.");
                    return this.enableQuic(false);
                };
                
                // Hook build
                CronetBuilder.build.implementation = function() {
                    console.log("[Frida 🤖] Cronet: build called. Forcing QUIC disabled.");
                    this.enableQuic(false);
                    return this.build();
                };
            } catch (e) {
                console.log("[-] CronetBuilder enableQuic hook failed: " + e);
            }
        } else {
            console.log("[Frida 🤖] no_mitm mode detected. Keeping Cronet HTTP/3 (QUIC) enabled for natural network fingerprinting.");
        }

        // 2. Hook SystemProperties to spoof Build parameters and device serial
        try {
            var SystemProperties = Java.use("android.os.SystemProperties");
            
            var get_1 = SystemProperties.get.overload('java.lang.String');
            get_1.implementation = function(key) {
                if (typeof NMAP_PROFILE !== 'undefined' && NMAP_PROFILE) {
                    if (key === "ro.product.model" && NMAP_PROFILE.model) return NMAP_PROFILE.model;
                    if (key === "ro.product.brand" && NMAP_PROFILE.brand) return NMAP_PROFILE.brand;
                    if (key === "ro.product.name" && NMAP_PROFILE.product) return NMAP_PROFILE.product;
                    if (key === "ro.product.device" && NMAP_PROFILE.device) return NMAP_PROFILE.device;
                    if (key === "ro.product.board" && NMAP_PROFILE.device) return NMAP_PROFILE.device;
                    if (key === "ro.product.manufacturer" && NMAP_PROFILE.manufacturer) return NMAP_PROFILE.manufacturer;
                    if (key === "ro.hardware" && NMAP_PROFILE.hardware) return NMAP_PROFILE.hardware;
                    if (key === "ro.serialno") return (NMAP_PROFILE.ssaid || "1234567890abcdef").substring(0, 16);
                    if (key === "ro.debuggable") return "0";
                    if (key === "ro.secure") return "1";
                }
                return get_1.call(this, key);
            };
            
            var get_2 = SystemProperties.get.overload('java.lang.String', 'java.lang.String');
            get_2.implementation = function(key, def) {
                if (typeof NMAP_PROFILE !== 'undefined' && NMAP_PROFILE) {
                    if (key === "ro.product.model" && NMAP_PROFILE.model) return NMAP_PROFILE.model;
                    if (key === "ro.product.brand" && NMAP_PROFILE.brand) return NMAP_PROFILE.brand;
                    if (key === "ro.product.name" && NMAP_PROFILE.product) return NMAP_PROFILE.product;
                    if (key === "ro.product.device" && NMAP_PROFILE.device) return NMAP_PROFILE.device;
                    if (key === "ro.product.board" && NMAP_PROFILE.device) return NMAP_PROFILE.device;
                    if (key === "ro.product.manufacturer" && NMAP_PROFILE.manufacturer) return NMAP_PROFILE.manufacturer;
                    if (key === "ro.hardware" && NMAP_PROFILE.hardware) return NMAP_PROFILE.hardware;
                    if (key === "ro.serialno") return (NMAP_PROFILE.ssaid || "1234567890abcdef").substring(0, 16);
                    if (key === "ro.debuggable") return "0";
                    if (key === "ro.secure") return "1";
                }
                return get_2.call(this, key, def);
            };

            var getInt = SystemProperties.getInt.overload('java.lang.String', 'int');
            getInt.implementation = function(key, def) {
                if (key === "ro.debuggable") return 0;
                if (key === "ro.secure") return 1;
                return getInt.call(this, key, def);
            };
            
            var getBoolean = SystemProperties.getBoolean.overload('java.lang.String', 'boolean');
            getBoolean.implementation = function(key, def) {
                if (key === "ro.debuggable") return false;
                if (key === "ro.secure") return true;
                return getBoolean.call(this, key, def);
            };
        } catch (e) {
            console.log("[-] SystemProperties hooks failed: " + e);
        }

        // 3. Spoof static Build fields and Build.getSerial()
        try {
            var Build = Java.use("android.os.Build");
            if (typeof NMAP_PROFILE !== 'undefined' && NMAP_PROFILE) {
                if (NMAP_PROFILE.model) Build.MODEL.value = NMAP_PROFILE.model;
                if (NMAP_PROFILE.brand) Build.BRAND.value = NMAP_PROFILE.brand;
                if (NMAP_PROFILE.manufacturer) Build.MANUFACTURER.value = NMAP_PROFILE.manufacturer;
                if (NMAP_PROFILE.device) {
                    Build.DEVICE.value = NMAP_PROFILE.device;
                    Build.BOARD.value = NMAP_PROFILE.device;
                }
                if (NMAP_PROFILE.product) Build.PRODUCT.value = NMAP_PROFILE.product;
                if (NMAP_PROFILE.hardware) Build.HARDWARE.value = NMAP_PROFILE.hardware;
            }

            Build.getSerial.implementation = function() {
                if (typeof NMAP_PROFILE !== 'undefined' && NMAP_PROFILE) {
                    return (NMAP_PROFILE.ssaid || "1234567890abcdef").substring(0, 16);
                }
                return this.getSerial();
            };
        } catch (e) {
            console.log("[-] android.os.Build hooks failed: " + e);
        }

        // 4. Hook WiFi and Mac address leaks
        try {
            var WifiInfo = Java.use("android.net.wifi.WifiInfo");
            WifiInfo.getMacAddress.implementation = function() { return "02:00:00:00:00:00"; };
            WifiInfo.getSSID.implementation = function() { return "<unknown ssid>"; };
            WifiInfo.getBSSID.implementation = function() { return "00:00:00:00:00:00"; };
            
            var NetworkInterface = Java.use("java.net.NetworkInterface");
            NetworkInterface.getHardwareAddress.implementation = function() { return null; };
        } catch (e) {
            console.log("[-] WiFi/MAC leak hooks failed: " + e);
        }

        // 5. Hook WebView loadUrl to append dest_id (Target Place ID) for better Clova AI visibility
        try {
            var WebView = Java.use("android.webkit.WebView");
            
            var loadUrl_1 = WebView.loadUrl.overload('java.lang.String');
            loadUrl_1.implementation = function(url) {
                if (url && url.indexOf("ssc=tab.m_ait.all") !== -1 && url.indexOf("dest_id=") === -1) {
                    if (typeof NMAP_PROFILE !== 'undefined' && NMAP_PROFILE && NMAP_PROFILE.target_id) {
                        var delimiter = (url.indexOf("?") === -1) ? "?" : "&";
                        url = url + delimiter + "dest_id=" + NMAP_PROFILE.target_id;
                        console.log("[Frida 🤖] WebView.loadUrl(1) rewritten with dest_id: " + url);
                    }
                }
                loadUrl_1.call(this, url);
            };
            
            var loadUrl_2 = WebView.loadUrl.overload('java.lang.String', 'java.util.Map');
            loadUrl_2.implementation = function(url, headers) {
                if (url && url.indexOf("ssc=tab.m_ait.all") !== -1 && url.indexOf("dest_id=") === -1) {
                    if (typeof NMAP_PROFILE !== 'undefined' && NMAP_PROFILE && NMAP_PROFILE.target_id) {
                        var delimiter = (url.indexOf("?") === -1) ? "?" : "&";
                        url = url + delimiter + "dest_id=" + NMAP_PROFILE.target_id;
                        console.log("[Frida 🤖] WebView.loadUrl(2) rewritten with dest_id: " + url);
                    }
                }
                loadUrl_2.call(this, url, headers);
            };
        } catch (e) {
            console.log("[-] WebView.loadUrl hooks failed: " + e);
        }
    });
}

// Ensure execution is slightly delayed until after _core_survival.js finishes MTE patching
// [CRASH FIX] ARMv9 BTI (Snapdragon) 하드웨어 보안 충돌로 인해 libssl.so 네이티브 훅 시
// ExoPlayer 프로세스가 동작 중 죽으므로(SIGBUS), 기본적으로 끕니다.
// S22가 아닌 기기(MTE/BTI 하드웨어 보안 제한이 없는 기기)의 경우 안정적으로 native ssl 훅도 활성화합니다.
hook_native_ssl();
hook_java_all();
hook_anti_bot_fingerprinting();
