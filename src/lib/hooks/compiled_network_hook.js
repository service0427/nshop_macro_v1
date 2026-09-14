📦
22875 /src/lib/hooks/network_hook.js
11899 /src/lib/hooks/network_hook.js.map
✄
var __getOwnPropNames = Object.getOwnPropertyNames;
var __require = /* @__PURE__ */ ((x) => typeof require !== "undefined" ? require : typeof Proxy !== "undefined" ? new Proxy(x, {
  get: (a, b) => (typeof require !== "undefined" ? require : a)[b]
}) : x)(function(x) {
  if (typeof require !== "undefined") return require.apply(this, arguments);
  throw Error('Dynamic require of "' + x + '" is not supported');
});
var __esm = (fn, res) => function __init() {
  return fn && (res = (0, fn[__getOwnPropNames(fn)[0]])(fn = 0)), res;
};
var __commonJS = (cb, mod) => function __require2() {
  return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
};

// frida-builtins:/node-globals.js
var init_node_globals = __esm({
  "frida-builtins:/node-globals.js"() {
  }
});

// src/lib/hooks/search_interceptor.js
var require_search_interceptor = __commonJS({
  "src/lib/hooks/search_interceptor.js"() {
    init_node_globals();
    (function() {
      if (typeof Java === "undefined") return;
      Java.perform(function() {
        console.log("[SearchInterceptor \u26A1] Initializing 0.001s Search Response Hook...");
        try {
          var Response = Java.use("okhttp3.Response");
          Response.body.implementation = function() {
            var body = this.body();
            try {
              var request = this.request();
              var url = request ? request.url().toString() : "";
              if (url && (url.indexOf("m.search.naver.com/search.naver") !== -1 || url.indexOf("search.shopping.naver.com") !== -1)) {
                var source = body.source();
                if (source) {
                  source.request(Java.use("java.lang.Long").MAX_VALUE.value);
                  var buffer = source.getBuffer().clone();
                  var Charset = Java.use("java.nio.charset.Charset");
                  var utf8 = Charset.forName("UTF-8");
                  var responseText = buffer.readString(utf8);
                  if (responseText) {
                    var hasPriceComp = responseText.indexOf("\uB124\uC774\uBC84 \uAC00\uACA9\uBE44\uAD50") !== -1 || responseText.indexOf("\uAC00\uACA9\uBE44\uAD50") !== -1 || responseText.indexOf("\uB124\uC774\uBC84\uC1FC\uD551") !== -1;
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
                      url,
                      has_price_comp: hasPriceComp,
                      mids,
                      mids_count: mids.length
                    });
                    console.log("[SearchInterceptor \u{1F3AF}] Intercepted Naver Search Response! has_price_comp=" + hasPriceComp + ", total_mids=" + mids.length);
                  }
                }
              }
            } catch (e) {
            }
            return body;
          };
        } catch (e) {
          console.log("[-] OkHttp3 Response hook notice: " + e);
        }
      });
    })();
  }
});

// src/lib/hooks/network_hook.js
init_node_globals();
console.log("[*] Network Hook Script Loaded (Universal SSL Pinning Bypass)");
try {
  __require("./anti_detection.js");
} catch (e) {
  console.log("[-] Module anti_detection.js load error: " + e);
}
try {
  __require("./native_anti_detect.js");
} catch (e) {
  console.log("[-] Module native_anti_detect.js load error: " + e);
}
try {
  require_search_interceptor();
} catch (e) {
  console.log("[-] Module search_interceptor.js load error: " + e);
}
function hook_java_all() {
  console.log("[SSL Bypass \u{1F6E1}\uFE0F] Injecting Universal Java SSL Pinning Bypasses...");
  var X509TrustManager = Java.use("javax.net.ssl.X509TrustManager");
  var SSLContext = Java.use("javax.net.ssl.SSLContext");
  try {
    var TrustManager = Java.registerClass({
      name: "com.nhn.android.UniversalTrustManager",
      implements: [X509TrustManager],
      methods: {
        checkClientTrusted: function(chain, authType) {
        },
        checkServerTrusted: function(chain, authType) {
        },
        getAcceptedIssuers: function() {
          return [];
        }
      }
    });
    var TrustManagers = [TrustManager.$new()];
  } catch (e) {
    console.log("[-] Registering TrustManager failed: " + e);
  }
  try {
    var SSLContext_init = SSLContext.init.overload(
      "[Ljavax.net.ssl.KeyManager;",
      "[Ljavax.net.ssl.TrustManager;",
      "java.security.SecureRandom"
    );
    SSLContext_init.implementation = function(keyManager, trustManager, secureRandom) {
      SSLContext_init.call(this, keyManager, TrustManagers, secureRandom);
    };
  } catch (e) {
    console.log("[-] SSLContext.init hook failed: " + e);
  }
  try {
    var TrustManagerFactory = Java.use("javax.net.ssl.TrustManagerFactory");
    TrustManagerFactory.getTrustManagers.implementation = function() {
      return TrustManagers;
    };
  } catch (e) {
  }
  try {
    var HttpsURLConnection = Java.use("javax.net.ssl.HttpsURLConnection");
    HttpsURLConnection.setDefaultHostnameVerifier.implementation = function(hostnameVerifier) {
      return;
    };
    HttpsURLConnection.setHostnameVerifier.implementation = function(hostnameVerifier) {
      return;
    };
  } catch (e) {
  }
  try {
    var CertificatePinner = Java.use("okhttp3.CertificatePinner");
    CertificatePinner.check.overload("java.lang.String", "java.util.List").implementation = function(str, list) {
      return;
    };
  } catch (e) {
  }
  try {
    var CertificatePinner2 = Java.use("okhttp3.CertificatePinner");
    CertificatePinner2.check.overload("java.lang.String", "[Ljava.security.cert.Certificate;").implementation = function(str, certs) {
      return;
    };
  } catch (e) {
  }
  try {
    var TrustManagerImpl = Java.use("com.android.org.conscrypt.TrustManagerImpl");
    TrustManagerImpl.verifyChain.implementation = function(untrustedChain, trustAnchorChain, host, clientAuth, ocspData, tlsSslData) {
      return untrustedChain;
    };
    TrustManagerImpl.checkTrustedRecursive.implementation = function(certs, host, clientAuth, untrustedChain, trustAnchorChain, tlsSslData) {
      return certs;
    };
  } catch (e) {
  }
  try {
    var WebViewClient = Java.use("android.webkit.WebViewClient");
    WebViewClient.onReceivedSslError.implementation = function(view, handler, error) {
      handler.proceed();
    };
  } catch (e) {
  }
  try {
    var initAnti = __require("./anti_detection.js");
    if (typeof initAnti === "function") {
      initAnti();
    }
  } catch (e) {
    console.log("[-] initAnti Error: " + e);
  }
  console.log("  \u{1F389} [SUCCESS] Frida SSL Pinning Bypass Hooks Loaded Successfully!");
}
function hook_anti_bot_fingerprinting() {
  try {
    var WebView = Java.use("android.webkit.WebView");
    var loadUrl_1 = WebView.loadUrl.overload("java.lang.String");
    loadUrl_1.implementation = function(url) {
      if (url && url.indexOf("ssc=tab.m_ait.all") !== -1 && url.indexOf("dest_id=") === -1) {
        if (typeof NMAP_PROFILE !== "undefined" && NMAP_PROFILE && NMAP_PROFILE.target_id) {
          var delimiter = url.indexOf("?") === -1 ? "?" : "&";
          url = url + delimiter + "dest_id=" + NMAP_PROFILE.target_id;
          console.log("[Frida \u{1F916}] WebView.loadUrl(1) rewritten with dest_id: " + url);
        }
      }
      loadUrl_1.call(this, url);
    };
    var loadUrl_2 = WebView.loadUrl.overload("java.lang.String", "java.util.Map");
    loadUrl_2.implementation = function(url, headers) {
      if (url && url.indexOf("ssc=tab.m_ait.all") !== -1 && url.indexOf("dest_id=") === -1) {
        if (typeof NMAP_PROFILE !== "undefined" && NMAP_PROFILE && NMAP_PROFILE.target_id) {
          var delimiter = url.indexOf("?") === -1 ? "?" : "&";
          url = url + delimiter + "dest_id=" + NMAP_PROFILE.target_id;
          console.log("[Frida \u{1F916}] WebView.loadUrl(2) rewritten with dest_id: " + url);
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
    let get_dynamic_ssaid2 = function() {
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
      } catch (e) {
      }
      return null;
    };
    var get_dynamic_ssaid = get_dynamic_ssaid2;
    var SettingsSecure = Java.use("android.provider.Settings$Secure");
    var FileClass = Java.use("java.io.File");
    var FileInputStream = Java.use("java.io.FileInputStream");
    var BufferedReader = Java.use("java.io.BufferedReader");
    var InputStreamReader = Java.use("java.io.InputStreamReader");
    SettingsSecure.getString.overload("android.content.ContentResolver", "java.lang.String").implementation = function(resolver, name) {
      if (name === "android_id") {
        var dynamic_ssaid = get_dynamic_ssaid2();
        if (dynamic_ssaid !== null) {
          console.log("[Identity \u{1F3AD}] Intercepted Settings.Secure.getString(android_id) -> Returning: " + dynamic_ssaid);
          return dynamic_ssaid;
        }
      }
      return this.getString(resolver, name);
    };
    console.log("[Identity \u{1F3AD}] Dynamic SSAID Hook registered cleanly!");
  } catch (e) {
    console.log("[-] Settings.Secure.getString hook error: " + e);
  }
}
function hook_crypto_hash_tracer() {
  try {
    let is_printable_telemetry2 = function(str) {
      if (!str || str.length < 4) return false;
      var low = str.toLowerCase();
      return low.indexOf("device") !== -1 || low.indexOf("napp") !== -1 || low.indexOf("ssaid") !== -1 || low.indexOf("android_id") !== -1 || low.indexOf("guid") !== -1 || low.indexOf("token") !== -1 || low.indexOf("nlog") !== -1 || low.indexOf("model") !== -1 || low.indexOf("carrier") !== -1 || low.indexOf("adid") !== -1 || low.indexOf("user-agent") !== -1 || low.indexOf("{") !== -1;
    };
    var is_printable_telemetry = is_printable_telemetry2;
    var StringClass = Java.use("java.lang.String");
    var MessageDigest = Java.use("java.security.MessageDigest");
    var Cipher = Java.use("javax.crypto.Cipher");
    try {
      MessageDigest.update.overload("[B").implementation = function(inputBytes) {
        try {
          if (inputBytes !== null && inputBytes.length > 0) {
            var plainText = StringClass.$new(inputBytes);
            if (is_printable_telemetry2(plainText)) {
              var algo = this.getAlgorithm();
              console.log("[Crypto \u{1F50D} Hash] " + algo + " Input: " + plainText.substring(0, 300));
            }
          }
        } catch (err) {
        }
        return this.update(inputBytes);
      };
    } catch (e) {
    }
    try {
      Cipher.doFinal.overload("[B").implementation = function(inputBytes) {
        try {
          if (inputBytes !== null && inputBytes.length > 0) {
            var plainText = StringClass.$new(inputBytes);
            if (is_printable_telemetry2(plainText)) {
              var algo = this.getAlgorithm();
              console.log("[Crypto \u{1F510} Cipher] " + algo + " Input: " + plainText.substring(0, 300));
            }
          }
        } catch (err) {
        }
        return this.doFinal(inputBytes);
      };
    } catch (e) {
    }
    console.log("[Crypto \u{1F50D}] MessageDigest & Cipher Telemetry Tracer Hook Registered!");
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
          var now = Date.now() / 1e3;
          var tremor_x = Math.sin(now * 20) * 0.12 + (Math.random() - 0.5) * 0.08;
          var tremor_y = Math.cos(now * 18) * 0.12 + (Math.random() - 0.5) * 0.08;
          var tremor_z = Math.sin(now * 15) * 0.15 + (Math.random() - 0.5) * 0.08;
          if (inType === 1) {
            values[0] = 0.45 + tremor_x;
            values[1] = 6.85 + tremor_y;
            values[2] = 7.15 + tremor_z;
          } else if (inType === 4) {
            values[0] = tremor_x * 0.12;
            values[1] = tremor_y * 0.12;
            values[2] = tremor_z * 0.12;
          } else if (inType === 9) {
            values[0] = 0.45 + tremor_x * 0.5;
            values[1] = 6.85 + tremor_y * 0.5;
            values[2] = 7.15 + tremor_z * 0.5;
          }
        }
      } catch (err) {
      }
      return this.dispatchSensorEvent(handle, values, inType, timestamp);
    };
    console.log("[Sensor \u{1F9ED}] Human Tremor (10Hz) & 45\xB0 Tilt Biometric Hook Registered!");
  } catch (e) {
    console.log("[-] hook_sensor_virtualization error: " + e);
  }
}
function hook_touch_biometrics() {
  try {
    var MotionEvent = Java.use("android.view.MotionEvent");
    try {
      MotionEvent.getPressure.overload().implementation = function() {
        return 0.68 + (Math.random() - 0.5) * 0.2;
      };
      MotionEvent.getPressure.overload("int").implementation = function(pointerIndex) {
        return 0.68 + (Math.random() - 0.5) * 0.2;
      };
    } catch (e) {
    }
    try {
      MotionEvent.getSize.overload().implementation = function() {
        return 0.18 + (Math.random() - 0.5) * 0.07;
      };
      MotionEvent.getSize.overload("int").implementation = function(pointerIndex) {
        return 0.18 + (Math.random() - 0.5) * 0.07;
      };
    } catch (e) {
    }
    try {
      MotionEvent.getTouchMajor.overload().implementation = function() {
        return 32.5 + (Math.random() - 0.5) * 9;
      };
      MotionEvent.getTouchMinor.overload().implementation = function() {
        return 22 + (Math.random() - 0.5) * 6;
      };
    } catch (e) {
    }
    console.log("[Biometrics \u{1F446}] Human Touch Pressure (0.68) & Size (0.18) Hook Registered!");
  } catch (e) {
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

            // 1. Canvas toDataURL / getImageData \uBBF8\uC138 \uB178\uC774\uC988 \uC8FC\uC785 (1000% \uACE0\uC720 \uD574\uC2DC \uC0DD\uC131)
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

            // 2. WebGL \uB80C\uB354\uB7EC \uC815\uD488 \uC77C\uAD00\uC131 \uC720\uC9C0 + \uD30C\uB77C\uBBF8\uD130 \uBB34\uACB0\uC131
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

            // 4. navigator.webdriver \uC644\uC804 \uC740\uD3D0 (\uBBF8\uC5B4\uCEA3 webDriver: false \uCDA9\uC871)
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
        } catch (e) {
        }
        this.onPageStarted(view, url, favicon);
      };
    } catch (e) {
    }
    try {
      WebViewClient.onPageCommitVisible.implementation = function(view, url) {
        try {
          view.evaluateJavascript(farbling_js, null);
        } catch (e) {
        }
        this.onPageCommitVisible(view, url);
      };
    } catch (e) {
    }
    console.log("[Farbling \u{1F3A8}] WebView Canvas/WebGL/Audio Micro-Farbling Hook Registered!");
  } catch (e) {
    console.log("[-] hook_webview_canvas_webgl_farbling error: " + e);
  }
}
function hook_impression_beacon_tracer() {
  try {
    var WebViewClient = Java.use("android.webkit.WebViewClient");
    try {
      WebViewClient.shouldInterceptRequest.overload("android.webkit.WebView", "android.webkit.WebResourceRequest").implementation = function(view, request) {
        try {
          if (request !== null) {
            var uri = request.getUrl();
            if (uri !== null) {
              var urlStr = uri.toString();
              var lowUrl = urlStr.toLowerCase();
              if (lowUrl.indexOf("lcs.naver.com") !== -1 || lowUrl.indexOf("adcr.naver.com") !== -1 || lowUrl.indexOf("cr.naver.com") !== -1 || lowUrl.indexOf("siape.veta") !== -1 || lowUrl.indexOf("ad.search.naver.com") !== -1 || lowUrl.indexOf("nlog.navercorp.com") !== -1 || lowUrl.indexOf("wcs.naver.net") !== -1 || lowUrl.indexOf("wcs.naver.com") !== -1 || lowUrl.indexOf("smartstore.naver.com/main/products") !== -1 || lowUrl.indexOf("help_ip") !== -1 || lowUrl.indexOf("captcha") !== -1) {
                if (lowUrl.indexOf("help_ip") !== -1 || lowUrl.indexOf("captcha") !== -1) {
                  console.log("[\u{1F6A8} IP BLOCKED/CAPTCHA \u274C] " + urlStr);
                } else if (lowUrl.indexOf("wcs.naver") !== -1 || lowUrl.indexOf("smartstore.naver.com") !== -1) {
                  console.log("[\u{1F6D2} SmartStore Page/WCS \u{1F3AF}] " + urlStr.substring(0, 180));
                } else {
                  console.log("[\u{1F4E1} Impression/Beacon \u{1F6F0}\uFE0F] " + urlStr);
                }
              }
            }
          }
        } catch (e) {
        }
        return this.shouldInterceptRequest(view, request);
      };
    } catch (e) {
    }
    try {
      var RealCall = Java.use("okhttp3.RealCall");
      RealCall.execute.implementation = function() {
        try {
          var req = this.request();
          if (req !== null) {
            var urlStr = req.url().toString();
            var lowUrl = urlStr.toLowerCase();
            if (lowUrl.indexOf("lcs.naver.com") !== -1 || lowUrl.indexOf("adcr") !== -1 || lowUrl.indexOf("cr.naver.com") !== -1 || lowUrl.indexOf("nlog") !== -1) {
              console.log("[\u{1F4E1} Native Beacon \u{1F6F0}\uFE0F] " + urlStr);
            }
          }
        } catch (e) {
        }
        return this.execute();
      };
    } catch (e) {
    }
    try {
      let recordCurrentUrl2 = function(urlStr) {
        try {
          if (urlStr && (urlStr.indexOf("http://") === 0 || urlStr.indexOf("https://") === 0)) {
            var fos = FileOutputStream.$new("/data/local/tmp/naver_webview_url.txt", false);
            var bytes = StringClass.$new(urlStr).getBytes();
            fos.write(bytes);
            fos.flush();
            fos.close();
          }
        } catch (err) {
        }
      };
      var recordCurrentUrl = recordCurrentUrl2;
      var FileOutputStream = Java.use("java.io.FileOutputStream");
      var StringClass = Java.use("java.lang.String");
      var WebView = Java.use("android.webkit.WebView");
      try {
        WebView.loadUrl.overload("java.lang.String").implementation = function(url) {
          recordCurrentUrl2(url);
          return this.loadUrl(url);
        };
      } catch (e) {
      }
      try {
        WebViewClient.onPageStarted.overload("android.webkit.WebView", "java.lang.String", "android.graphics.Bitmap").implementation = function(view, url, favicon) {
          recordCurrentUrl2(url);
          return this.onPageStarted(view, url, favicon);
        };
      } catch (e) {
      }
      try {
        WebViewClient.onPageFinished.overload("android.webkit.WebView", "java.lang.String").implementation = function(view, url) {
          recordCurrentUrl2(url);
          return this.onPageFinished(view, url);
        };
      } catch (e) {
      }
    } catch (e) {
    }
    console.log("[Impression \u{1F6F0}\uFE0F] Real-time Impression & Page URL Tracker Hook Registered!");
  } catch (e) {
    console.log("[-] hook_impression_beacon_tracer error: " + e);
  }
}
if (typeof Java !== "undefined" && Java.available) {
  Java.perform(function() {
    console.log("[SSL Bypass \u{1F6E1}\uFE0F] Java.perform attached cleanly!");
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

✄
{
  "version": 3,
  "sources": ["frida-builtins:/node-globals.js", "src/lib/hooks/search_interceptor.js", "src/lib/hooks/network_hook.js"],
  "mappings": "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",
  "names": ["get_dynamic_ssaid", "is_printable_telemetry", "recordCurrentUrl"]
}
