/* 
   Network Hook (V3 Refactored - Robust Universal SSL Pinning Bypass)
   - Exclusively handles Certificate Pinning & SSL Bypass across OkHttp3, TrustManager, Conscrypt, WebView, Cronet.
*/

console.log("[*] Network Hook Script Loaded (Universal SSL Pinning Bypass)");

// 모듈형 훅 임포트
try {
    require('./anti_detection.js');
} catch (e) {
    console.log("[-] Module anti_detection.js load error: " + e);
}
try {
    require('./native_anti_detect.js');
} catch (e) {
    console.log("[-] Module native_anti_detect.js load error: " + e);
}
try {
    require('./search_interceptor.js');
} catch (e) {
    console.log("[-] Module search_interceptor.js load error: " + e);
}

function hook_java_all() {
    console.log("[SSL Bypass 🛡️] Injecting Universal Java SSL Pinning Bypasses...");

    var X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
    var SSLContext = Java.use('javax.net.ssl.SSLContext');

    // 1. Universal TrustManager Bypasser
    try {
        var TrustManager = Java.registerClass({
            name: 'com.nhn.android.UniversalTrustManager',
            implements: [X509TrustManager],
            methods: {
                checkClientTrusted: function (chain, authType) {},
                checkServerTrusted: function (chain, authType) {},
                getAcceptedIssuers: function () { return []; }
            }
        });
        var TrustManagers = [TrustManager.$new()];
    } catch (e) {
        console.log("[-] Registering TrustManager failed: " + e);
    }

    // 2. SSLContext.init Bypass
    try {
        var SSLContext_init = SSLContext.init.overload(
            '[Ljavax.net.ssl.KeyManager;',
            '[Ljavax.net.ssl.TrustManager;',
            'java.security.SecureRandom'
        );
        SSLContext_init.implementation = function (keyManager, trustManager, secureRandom) {
            SSLContext_init.call(this, keyManager, TrustManagers, secureRandom);
        };
    } catch (e) {
        console.log("[-] SSLContext.init hook failed: " + e);
    }

    // 3. TrustManagerFactory Bypass
    try {
        var TrustManagerFactory = Java.use('javax.net.ssl.TrustManagerFactory');
        TrustManagerFactory.getTrustManagers.implementation = function() {
            return TrustManagers;
        };
    } catch (e) {}

    // 4. HttpsURLConnection HostnameVerifier & SSLSocketFactory Bypass
    try {
        var HttpsURLConnection = Java.use('javax.net.ssl.HttpsURLConnection');
        HttpsURLConnection.setDefaultHostnameVerifier.implementation = function(hostnameVerifier) {
            return;
        };
        HttpsURLConnection.setHostnameVerifier.implementation = function(hostnameVerifier) {
            return;
        };
    } catch (e) {}

    // 5. OkHttp3 CertificatePinner Bypasses
    try {
        var CertificatePinner = Java.use('okhttp3.CertificatePinner');
        CertificatePinner.check.overload('java.lang.String', 'java.util.List').implementation = function (str, list) {
            return;
        };
    } catch (e) {}

    try {
        var CertificatePinner2 = Java.use('okhttp3.CertificatePinner');
        CertificatePinner2.check.overload('java.lang.String', '[Ljava.security.cert.Certificate;').implementation = function (str, certs) {
            return;
        };
    } catch (e) {}

    // 6. Conscrypt TrustManagerImpl Bypasses (Android 7+)
    try {
        var TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
        TrustManagerImpl.verifyChain.implementation = function (untrustedChain, trustAnchorChain, host, clientAuth, ocspData, tlsSslData) {
            return untrustedChain;
        };
        TrustManagerImpl.checkTrustedRecursive.implementation = function (certs, host, clientAuth, untrustedChain, trustAnchorChain, tlsSslData) {
            return certs;
        };
    } catch (e) {}

    // 7. WebView SSL Error Bypass
    try {
        var WebViewClient = Java.use('android.webkit.WebViewClient');
        WebViewClient.onReceivedSslError.implementation = function (view, handler, error) {
            handler.proceed();
        };
    } catch (e) {}

    // 8. Run Anti Detection Hooks
    try {
        var initAnti = require('./anti_detection.js');
        if (typeof initAnti === 'function') {
            initAnti();
        }
    } catch (e) {
        console.log("[-] initAnti Error: " + e);
    }

    console.log("  🎉 [SUCCESS] Frida SSL Pinning Bypass Hooks Loaded Successfully!");
}

function hook_anti_bot_fingerprinting() {
    try {
        var WebView = Java.use('android.webkit.WebView');
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
            loadUrl_2.call(this, url);
        };
    } catch (e) {
        console.log("[-] WebView.loadUrl hook failed: " + e);
    }
}

function hook_identity_mutation() {
    try {
        var SettingsSecure = Java.use("android.provider.Settings$Secure");
        var FileClass = Java.use("java.io.File");
        var FileInputStream = Java.use("java.io.FileInputStream");
        var BufferedReader = Java.use("java.io.BufferedReader");
        var InputStreamReader = Java.use("java.io.InputStreamReader");

        function get_dynamic_ssaid() {
            try {
                var file = FileClass.$new("/data/local/tmp/current_ssaid.txt");
                if (file.exists()) {
                    var fis = FileInputStream.$new(file);
                    var reader = BufferedReader.$new(InputStreamReader.$new(fis));
                    var line = reader.readLine();
                    reader.close();
                    if (line && line.trim().length === 16) {
                        return line.trim();
                    }
                }
            } catch (e) {}
            return null;
        }

        SettingsSecure.getString.overload('android.content.ContentResolver', 'java.lang.String').implementation = function(resolver, name) {
            if (name === "android_id") {
                var dynamic_ssaid = get_dynamic_ssaid();
                if (dynamic_ssaid !== null) {
                    console.log("[Identity 🎭] Intercepted Settings.Secure.getString(android_id) -> Returning: " + dynamic_ssaid);
                    return dynamic_ssaid;
                }
            }
            return this.getString(resolver, name);
        };
        console.log("[Identity 🎭] Dynamic SSAID Hook registered cleanly!");
    } catch (e) {
        console.log("[-] Settings.Secure.getString hook error: " + e);
    }
}

function hook_crypto_hash_tracer() {
    try {
        var StringClass = Java.use("java.lang.String");
        var MessageDigest = Java.use("java.security.MessageDigest");
        var Cipher = Java.use("javax.crypto.Cipher");

        function is_printable_telemetry(str) {
            if (!str || str.length < 4) return false;
            var low = str.toLowerCase();
            return low.indexOf("device") !== -1 || low.indexOf("napp") !== -1 ||
                   low.indexOf("ssaid") !== -1 || low.indexOf("android_id") !== -1 ||
                   low.indexOf("guid") !== -1 || low.indexOf("token") !== -1 ||
                   low.indexOf("nlog") !== -1 || low.indexOf("model") !== -1 ||
                   low.indexOf("carrier") !== -1 || low.indexOf("adid") !== -1 ||
                   low.indexOf("user-agent") !== -1 || low.indexOf("{") !== -1;
        }

        // 1. MessageDigest (MD5, SHA-1, SHA-256)
        try {
            MessageDigest.update.overload('[B').implementation = function (inputBytes) {
                try {
                    if (inputBytes !== null && inputBytes.length > 0) {
                        var plainText = StringClass.$new(inputBytes);
                        if (is_printable_telemetry(plainText)) {
                            var algo = this.getAlgorithm();
                            console.log("[Crypto 🔍 Hash] " + algo + " Input: " + plainText.substring(0, 300));
                        }
                    }
                } catch (err) {}
                return this.update(inputBytes);
            };
        } catch (e) {}

        // 2. Cipher (AES/RSA encryption)
        try {
            Cipher.doFinal.overload('[B').implementation = function (inputBytes) {
                try {
                    if (inputBytes !== null && inputBytes.length > 0) {
                        var plainText = StringClass.$new(inputBytes);
                        if (is_printable_telemetry(plainText)) {
                            var algo = this.getAlgorithm();
                            console.log("[Crypto 🔐 Cipher] " + algo + " Input: " + plainText.substring(0, 300));
                        }
                    }
                } catch (err) {}
                return this.doFinal(inputBytes);
            };
        } catch (e) {}

        console.log("[Crypto 🔍] MessageDigest & Cipher Telemetry Tracer Hook Registered!");
    } catch (e) {
        console.log("[-] hook_crypto_hash_tracer error: " + e);
    }
}

function hook_sensor_virtualization() {
    try {
        var SensorEventQueue = Java.use("android.hardware.SystemSensorManager$SensorEventQueue");
        
        SensorEventQueue.dispatchSensorEvent.implementation = function(handle, values, inType, timestamp) {
            try {
                if (values !== null && values.length >= 3) {
                    var now = Date.now() / 1000.0;
                    // 10Hz 미세 생체 손떨림 (Human Micro-Tremor) 주파수 노이즈
                    var tremor_x = Math.sin(now * 20.0) * 0.12 + (Math.random() - 0.5) * 0.08;
                    var tremor_y = Math.cos(now * 18.0) * 0.12 + (Math.random() - 0.5) * 0.08;
                    var tremor_z = Math.sin(now * 15.0) * 0.15 + (Math.random() - 0.5) * 0.08;

                    // Sensor Type 1: TYPE_ACCELEROMETER (가속도 센서: m/s^2)
                    if (inType === 1) {
                        values[0] = 0.45 + tremor_x;   // X축 좌우 미세 기울기
                        values[1] = 6.85 + tremor_y;   // Y축 세로 45도 기울기 (중력 분력)
                        values[2] = 7.15 + tremor_z;   // Z축 화면 수직 분력
                    } 
                    // Sensor Type 4: TYPE_GYROSCOPE (자이로 각속도: rad/s)
                    else if (inType === 4) {
                        values[0] = tremor_x * 0.12;   // 피치 회전 각속도
                        values[1] = tremor_y * 0.12;   // 롤 회전 각속도
                        values[2] = tremor_z * 0.12;   // 요 회전 각속도
                    }
                    // Sensor Type 9: TYPE_GRAVITY (중력 센서)
                    else if (inType === 9) {
                        values[0] = 0.45 + tremor_x * 0.5;
                        values[1] = 6.85 + tremor_y * 0.5;
                        values[2] = 7.15 + tremor_z * 0.5;
                    }
                }
            } catch (err) {}
            return this.dispatchSensorEvent(handle, values, inType, timestamp);
        };
        console.log("[Sensor 🧭] Human Tremor (10Hz) & 45° Tilt Biometric Hook Registered!");
    } catch (e) {
        console.log("[-] hook_sensor_virtualization error: " + e);
    }
}

function hook_touch_biometrics() {
    try {
        var MotionEvent = Java.use("android.view.MotionEvent");

        // 1. Hook getPressure (개별 포인터 및 기본 압력 -> 사람 엄지손가락 0.58~0.78 가상화)
        try {
            MotionEvent.getPressure.overload().implementation = function() {
                return 0.68 + (Math.random() - 0.5) * 0.20;
            };
            MotionEvent.getPressure.overload('int').implementation = function(pointerIndex) {
                return 0.68 + (Math.random() - 0.5) * 0.20;
            };
        } catch(e) {}

        // 2. Hook getSize (손가락 터치 면적 -> 0.15~0.22 가상화, ADB의 0.0 기계적 상수 제거)
        try {
            MotionEvent.getSize.overload().implementation = function() {
                return 0.18 + (Math.random() - 0.5) * 0.07;
            };
            MotionEvent.getSize.overload('int').implementation = function(pointerIndex) {
                return 0.18 + (Math.random() - 0.5) * 0.07;
            };
        } catch(e) {}

        // 3. Hook getTouchMajor / getTouchMinor (생체 타원형 지문 접촉부 직경)
        try {
            MotionEvent.getTouchMajor.overload().implementation = function() {
                return 32.5 + (Math.random() - 0.5) * 9.0;
            };
            MotionEvent.getTouchMinor.overload().implementation = function() {
                return 22.0 + (Math.random() - 0.5) * 6.0;
            };
        } catch(e) {}

        console.log("[Biometrics 👆] Human Touch Pressure (0.68) & Size (0.18) Hook Registered!");
    } catch(e) {
        console.log("[-] hook_touch_biometrics error: " + e);
    }
}

function hook_webview_canvas_webgl_farbling() {
    try {
        var WebView = Java.use("android.webkit.WebView");
        var WebViewClient = Java.use("android.webkit.WebViewClient");

        var farbling_js = `
        (function() {
            if (window.__farbling_applied__) return;
            window.__farbling_applied__ = true;

            // 1. Canvas toDataURL / getImageData 미세 노이즈 주입 (1000% 고유 해시 생성)
            if (window.HTMLCanvasElement) {
                const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
                HTMLCanvasElement.prototype.toDataURL = function(...args) {
                    const ctx = this.getContext('2d');
                    if (ctx && this.width > 0 && this.height > 0) {
                        try {
                            const imgData = ctx.getImageData(0, 0, Math.min(this.width, 16), Math.min(this.height, 16));
                            for (let i = 0; i < imgData.data.length; i += 4) {
                                imgData.data[i] = (imgData.data[i] + (Math.random() > 0.5 ? 1 : -1) + 256) % 256;
                            }
                            ctx.putImageData(imgData, 0, 0);
                        } catch(e) {}
                    }
                    return origToDataURL.apply(this, args);
                };

                const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
                CanvasRenderingContext2D.prototype.getImageData = function(...args) {
                    const res = origGetImageData.apply(this, args);
                    if (res && res.data) {
                        for (let i = 0; i < Math.min(res.data.length, 64); i += 4) {
                            res.data[i] = (res.data[i] + (Math.random() > 0.5 ? 1 : 0)) % 256;
                        }
                    }
                    return res;
                };
            }

            // 2. WebGL 렌더러 정품 일관성 유지 + 파라미터 무결성
            const getGLParams = (proto) => {
                const origGetParam = proto.getParameter;
                proto.getParameter = function(param) {
                    if (param === 37446) return 'Qualcomm Adreno (TM) 660'; // UNMASKED_RENDERER_WEBGL
                    if (param === 37445) return 'Qualcomm'; // UNMASKED_VENDOR_WEBGL
                    return origGetParam.apply(this, arguments);
                };
            };
            if (window.WebGLRenderingContext) getGLParams(WebGLRenderingContext.prototype);
            if (window.WebGL2RenderingContext) getGLParams(WebGL2RenderingContext.prototype);

            // 4. navigator.webdriver 완전 은폐 (미어캣 webDriver: false 충족)
            try {
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                    configurable: true
                });
            } catch(e) {}
        })();
        `;

        try {
            WebViewClient.onPageStarted.implementation = function(view, url, favicon) {
                try {
                    view.evaluateJavascript(farbling_js, null);
                } catch(e) {}
                this.onPageStarted(view, url, favicon);
            };
        } catch(e) {}

        try {
            WebViewClient.onPageCommitVisible.implementation = function(view, url) {
                try {
                    view.evaluateJavascript(farbling_js, null);
                } catch(e) {}
                this.onPageCommitVisible(view, url);
            };
        } catch(e) {}

        console.log("[Farbling 🎨] WebView Canvas/WebGL/Audio Micro-Farbling Hook Registered!");
    } catch(e) {
        console.log("[-] hook_webview_canvas_webgl_farbling error: " + e);
    }
}

function hook_impression_beacon_tracer() {
    try {
        var WebViewClient = Java.use("android.webkit.WebViewClient");

        // 1. WebView HTTP/HTTPS Request Tracer (인앱 웹뷰 노출 및 클릭 비콘 전수 감지)
        try {
            WebViewClient.shouldInterceptRequest.overload('android.webkit.WebView', 'android.webkit.WebResourceRequest').implementation = function(view, request) {
                try {
                    if (request !== null) {
                        var uri = request.getUrl();
                        if (uri !== null) {
                            var urlStr = uri.toString();
                            var lowUrl = urlStr.toLowerCase();
                            if (lowUrl.indexOf("lcs.naver.com") !== -1 ||
                                lowUrl.indexOf("adcr.naver.com") !== -1 ||
                                lowUrl.indexOf("cr.naver.com") !== -1 ||
                                lowUrl.indexOf("siape.veta") !== -1 ||
                                lowUrl.indexOf("ad.search.naver.com") !== -1 ||
                                lowUrl.indexOf("nlog.navercorp.com") !== -1 ||
                                lowUrl.indexOf("wcs.naver.net") !== -1 ||
                                lowUrl.indexOf("wcs.naver.com") !== -1 ||
                                lowUrl.indexOf("smartstore.naver.com/main/products") !== -1 ||
                                lowUrl.indexOf("help_ip") !== -1 ||
                                lowUrl.indexOf("captcha") !== -1) {
                                
                                if (lowUrl.indexOf("help_ip") !== -1 || lowUrl.indexOf("captcha") !== -1) {
                                    console.log("[🚨 IP BLOCKED/CAPTCHA ❌] " + urlStr);
                                } else if (lowUrl.indexOf("wcs.naver") !== -1 || lowUrl.indexOf("smartstore.naver.com") !== -1) {
                                    console.log("[🛒 SmartStore Page/WCS 🎯] " + urlStr.substring(0, 180));
                                } else {
                                    console.log("[📡 Impression/Beacon 🛰️] " + urlStr);
                                }
                            }
                        }
                    }
                } catch(e) {}
                return this.shouldInterceptRequest(view, request);
            };
        } catch(e) {}

        // 2. OkHttp Native Request Tracer
        try {
            var RealCall = Java.use("okhttp3.RealCall");
            RealCall.execute.implementation = function() {
                try {
                    var req = this.request();
                    if (req !== null) {
                        var urlStr = req.url().toString();
                        var lowUrl = urlStr.toLowerCase();
                        if (lowUrl.indexOf("lcs.naver.com") !== -1 ||
                            lowUrl.indexOf("adcr") !== -1 ||
                            lowUrl.indexOf("cr.naver.com") !== -1 ||
                            lowUrl.indexOf("nlog") !== -1) {
                            console.log("[📡 Native Beacon 🛰️] " + urlStr);
                        }
                    }
                } catch(e) {}
                return this.execute();
            };
        } catch(e) {}

        // 3. WebView Page State & Active URL Tracker (실시간 페이지 종류 식별용)
        try {
            var FileOutputStream = Java.use("java.io.FileOutputStream");
            var StringClass = Java.use("java.lang.String");
            var WebView = Java.use("android.webkit.WebView");

            function recordCurrentUrl(urlStr) {
                try {
                    if (urlStr && (urlStr.indexOf("http://") === 0 || urlStr.indexOf("https://") === 0)) {
                        var fos = FileOutputStream.$new("/data/local/tmp/naver_webview_url.txt", false);
                        var bytes = StringClass.$new(urlStr).getBytes();
                        fos.write(bytes);
                        fos.flush();
                        fos.close();
                    }
                } catch(err) {}
            }

            try {
                WebView.loadUrl.overload('java.lang.String').implementation = function(url) {
                    recordCurrentUrl(url);
                    return this.loadUrl(url);
                };
            } catch(e) {}

            try {
                WebViewClient.onPageStarted.overload('android.webkit.WebView', 'java.lang.String', 'android.graphics.Bitmap').implementation = function(view, url, favicon) {
                    recordCurrentUrl(url);
                    return this.onPageStarted(view, url, favicon);
                };
            } catch(e) {}

            try {
                WebViewClient.onPageFinished.overload('android.webkit.WebView', 'java.lang.String').implementation = function(view, url) {
                    recordCurrentUrl(url);
                    return this.onPageFinished(view, url);
                };
            } catch(e) {}
        } catch(e) {}

        console.log("[Impression 🛰️] Real-time Impression & Page URL Tracker Hook Registered!");
    } catch(e) {
        console.log("[-] hook_impression_beacon_tracer error: " + e);
    }
}

// Immediate Frida Java.perform binding (No polling delays)
if (typeof Java !== 'undefined' && Java.available) {
    Java.perform(function () {
        console.log("[SSL Bypass 🛡️] Java.perform attached cleanly!");
        hook_identity_mutation();
        hook_anti_bot_fingerprinting();
        hook_crypto_hash_tracer();
        hook_sensor_virtualization();
        hook_touch_biometrics();
        hook_webview_canvas_webgl_farbling();
        hook_impression_beacon_tracer();
        hook_java_all();
    });
}

