// frida_inject_instagram_referrer.js
// Inject Instagram Referer (https://l.instagram.com/) into all Naver App Network Requests (WebView, OkHttp, Cronet H3)

Java.perform(function () {
    console.log("[+] Frida Pure-Native Instagram Referrer Hook Active!");

    var INSTA_REFERER = "https://l.instagram.com/";

    // 1. Hook Intent Extra Resolution (Android App Layer)
    try {
        var Intent = Java.use("android.content.Intent");
        Intent.getStringExtra.implementation = function (name) {
            var res = this.getStringExtra(name);
            if (name === "android.intent.extra.REFERRER" || name === "android.intent.extra.REFERRER_NAME") {
                console.log("[✓] [Frida Intent Hook] Spoofing Intent Extra '" + name + "' -> " + INSTA_REFERER);
                return INSTA_REFERER;
            }
            return res;
        };
    } catch (e) {
        console.log("[-] Intent extra hook error: " + e);
    }

    // 2. Hook Android System WebView loadUrl
    try {
        var WebView = Java.use("android.webkit.WebView");
        var HashMap = Java.use("java.util.HashMap");

        WebView.loadUrl.overload('java.lang.String').implementation = function (url) {
            var headers = HashMap.$new();
            headers.put("Referer", INSTA_REFERER);
            headers.put("sec-fetch-site", "cross-site");
            console.log("[✓] [Frida WebView Hook] Injected Referer -> " + url);
            return this.loadUrl(url, headers);
        };

        WebView.loadUrl.overload('java.lang.String', 'java.util.Map').implementation = function (url, headers) {
            if (headers == null) {
                headers = HashMap.$new();
            }
            headers.put("Referer", INSTA_REFERER);
            headers.put("sec-fetch-site", "cross-site");
            console.log("[✓] [Frida WebView Hook] Injected Referer with Headers -> " + url);
            return this.loadUrl(url, headers);
        };
    } catch (e) {
        console.log("[-] WebView hook error: " + e);
    }

    // 3. Hook OkHttp Network Requests
    try {
        var RequestBuilder = Java.use("okhttp3.Request$Builder");
        RequestBuilder.build.implementation = function () {
            this.header("Referer", INSTA_REFERER);
            this.header("sec-fetch-site", "cross-site");
            var req = this.build();
            var urlStr = req.url().toString();
            if (urlStr.indexOf("naver.com") !== -1) {
                console.log("[✓] [Frida OkHttp Hook] Injected Referer into " + urlStr);
            }
            return req;
        };
    } catch (e) {
        console.log("[-] OkHttp hook error: " + e);
    }

    // 4. Hook Chromium Cronet Native HTTP/3 Network Stack
    try {
        var CronetUrlRequest = Java.use("org.chromium.net.impl.CronetUrlRequest");
        CronetUrlRequest.addHeader.implementation = function (name, value) {
            if (name.toLowerCase() === "referer") {
                value = INSTA_REFERER;
                console.log("[✓] [Frida Cronet H3 Hook] Spoofed Native Referer -> " + INSTA_REFERER);
            }
            return this.addHeader(name, value);
        };
    } catch (e) {
        console.log("[-] Cronet H3 hook error: " + e);
    }
});
