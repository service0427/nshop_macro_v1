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
