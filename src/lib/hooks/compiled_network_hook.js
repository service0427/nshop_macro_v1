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
    
/* --- Bundled: search_interceptor.js --- */
/* 
   Search Response Interceptor (Frida JS Hook)
   - Hooks OkHttp / WebView network responses for Naver Search (m.search.naver.com)
   - Instantly extracts Gate 1 ('네이버 가격비교') & Gate 2 (MID list) in 0.001s without scrolling
*/

(function() {
    if (typeof Java === 'undefined') return;

    Java.perform(function() {
        console.log("[SearchInterceptor ⚡] Initializing 0.001s Search Response Hook...");

        try {
            // Hook OkHttp3 RealResponseBody or ResponseBody
            var Response = Java.use("okhttp3.Response");

            Response.body.implementation = function() {
                var body = this.body();
                try {
                    var request = this.request();
                    var url = request ? request.url().toString() : "";

                    if (url && (url.indexOf("m.search.naver.com/search.naver") !== -1 || url.indexOf("search.shopping.naver.com") !== -1)) {
                        // Intercept search result response
                        var source = body.source();
                        if (source) {
                            source.request(Java.use("java.lang.Long").MAX_VALUE.value);
                            var buffer = source.getBuffer().clone();
                            var Charset = Java.use("java.nio.charset.Charset");
                            var utf8 = Charset.forName("UTF-8");
                            var responseText = buffer.readString(utf8);

                            if (responseText) {
                                var hasPriceComp = responseText.indexOf("네이버 가격비교") !== -1 || 
                                                   responseText.indexOf("가격비교") !== -1 ||
                                                   responseText.indexOf("네이버쇼핑") !== -1;

                                // Regex to extract MIDs
                                var midRegex = /(?:data-nv-mid|data-i|nvMid|mid=)["':](\d{7,15})/g;
                                var mids = [];
                                var match;
                                while ((match = midRegex.exec(responseText)) !== null) {
                                    if (mids.indexOf(match[1]) === -1) {
                                        mids.push(match[1]);
                                    }
                                }

                                send({
                                    type: "SEARCH_RESPONSE_INTERCEPTED",
                                    url: url,
                                    has_price_comp: hasPriceComp,
                                    mids: mids,
                                    mids_count: mids.length
                                });
                                console.log("[SearchInterceptor 🎯] Intercepted Naver Search Response! has_price_comp=" + hasPriceComp + ", total_mids=" + mids.length);
                            }
                        }
                    }
                } catch(e) {
                    // Non-blocking catch
                }
                return body;
            };
        } catch(e) {
            console.log("[-] OkHttp3 Response hook notice: " + e);
        }
    });
})();

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

// Immediate Frida Java.perform binding (No polling delays)
if (typeof Java !== 'undefined' && Java.available) {
    Java.perform(function () {
        console.log("[SSL Bypass 🛡️] Java.perform attached cleanly!");
        hook_identity_mutation();
        hook_anti_bot_fingerprinting();
        hook_java_all();
    });
}

