/* 
   Self-Triggering Macro Bot v10 (The Ultimate Solution)
   - Goal: ZERO delay, ZERO overhead, ZERO session conflict.
   - Strategy: Hook N-Log transmission directly to trigger actions.
*/

Java.perform(function() {
    console.log("[Frida 🤖] 자가 트리거 매크로 v10 활성화 (이벤트 실시간 반응 모드)");

    var taskCompleted = false;

    // --- 1. View Traverser (Find WebView more robustly than Java.choose) ---
    function findWebView(view) {
        if (view.getClass().getName().includes("WebView")) {
            return view;
        }
        if (view.instanceOf(Java.use("android.view.ViewGroup"))) {
            var group = Java.cast(view, Java.use("android.view.ViewGroup"));
            for (var i = 0; i < group.getChildCount(); i++) {
                var child = group.getChildAt(i);
                var found = findWebView(child);
                if (found) return found;
            }
        }
        return null;
    }

    // --- 2. Action Logic (Native Touch) ---
    function executeAgreement(wv, attempt) {
        if (!attempt) attempt = 1;
        if (attempt > 10) {
            console.log("[Frida 🤖] 약관 동의 조작 포기 (타임아웃)");
            return;
        }

        console.log("[Frida 🤖] 약관 동의 조작 시도 " + attempt + "/10 (네이티브 터치)");
        var location = Java.array('int', [0, 0]);
        wv.getLocationOnScreen(location);
        var wvX = location[0];
        var wvY = location[1];

        var jsPayload = "(function() { " +
            "  var results = []; " +
            "  document.querySelectorAll('input[type=checkbox]').forEach(i => { " +
            "    if(!i.checked) { " +
            "      var r = ((i.labels && i.labels.length > 0) ? i.labels[0] : i).getBoundingClientRect(); " +
            "      results.push({x: r.left, y: r.top, w: r.width, h: r.height}); " +
            "    } " +
            "  }); " +
            "  var btns = Array.from(document.querySelectorAll('button, a, div[role=button]')) " +
            "    .filter(function(b){ return b.innerText.includes('동의') && !b.innerText.includes('선택'); }); " +
            "  if (btns.length > 0) { " +
            "    var r = btns[0].getBoundingClientRect(); " +
            "    results.push({x: r.left, y: r.top, w: r.width, h: r.height}); " +
            "  } " +
            "  return JSON.stringify(results); " +
            "})();";

        wv.evaluateJavascript(jsPayload, Java.registerClass({
            name: "com.frida.WebCallbackV10_" + Math.floor(Math.random()*100000) + "_" + attempt,
            implements: [Java.use("android.webkit.ValueCallback")],
            methods: {
                onReceiveValue: function(value) {
                    if (!value || value === "null" || value === "[]") {
                        setTimeout(function() {
                            executeAgreement(wv, attempt + 1);
                        }, 1000);
                        return;
                    }
                    var coords = JSON.parse(value.replace(/^"|"$/g, '').replace(/\\"/g, '"'));
                    var MotionEvent = Java.use("android.view.MotionEvent");
                    var SystemClock = Java.use("android.os.SystemClock");

                    coords.forEach(function(item, index) {
                        setTimeout(function() {
                            var relX = item.x + (item.w / 2) + (Math.random() * 10 - 5);
                            var relY = item.y + (item.h / 2) + (Math.random() * 10 - 5);
                            var absX = wvX + relX;
                            var absY = wvY + relY;

                            console.log("[Frida 🤖] 클릭: (" + Math.round(absX) + ", " + Math.round(absY) + ")");
                            var now = SystemClock.uptimeMillis();
                            wv.dispatchTouchEvent(MotionEvent.obtain(now, now, 0, absX, absY, 0));
                            wv.dispatchTouchEvent(MotionEvent.obtain(now, now + 10, 1, absX, absY, 0));
                        }, index * 600);
                    });
                }
            }
        }).$new());
    }

    // --- 3. N-Log Interceptor (The Trigger) ---
    // 네이버 로그 전송 모듈을 훅킹하여 screen_start / /n 패킷을 실시간으로 잡습니다.
    function hookOkHttp() {
        try {
            var OkHttpClient = Java.use("okhttp3.OkHttpClient");
            OkHttpClient.newCall.implementation = function(request) {
                var url = request.url().toString();
                
                if (url.includes("nlogapp") || url.includes("/n")) {
                    console.log("[Frida 🤖] N-Log 신호 감지: " + url.split('?')[0]);
                    
                    Java.scheduleOnMainThread(function() {
                        Java.choose("android.webkit.WebView", {
                            onMatch: function(wv) {
                                executeAgreement(wv);
                            },
                            onComplete: function() {}
                        });
                    });
                }
                return this.newCall(request);
            };
            console.log("[Frida 🤖] OkHttp 훅 설치 완료");
        } catch(e) {
            console.log("[Frida 🤖] OkHttp 미로드, 3초 후 재시도... (" + e.message + ")");
            setTimeout(function() {
                Java.perform(function() { hookOkHttp(); });
            }, 3000);
        }
    }

    hookOkHttp();
});
