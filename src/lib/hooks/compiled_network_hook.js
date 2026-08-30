📦
9765 /src/lib/hooks/network_hook.js
5406 /src/lib/hooks/network_hook.js.map
✄
var __getOwnPropNames = Object.getOwnPropertyNames;
var __esm = (fn, res) => function __init() {
  return fn && (res = (0, fn[__getOwnPropNames(fn)[0]])(fn = 0)), res;
};
var __commonJS = (cb, mod) => function __require() {
  return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
};

// frida-builtins:/node-globals.js
var init_node_globals = __esm({
  "frida-builtins:/node-globals.js"() {
  }
});

// src/lib/hooks/anti_detection.js
var require_anti_detection = __commonJS({
  "src/lib/hooks/anti_detection.js"(exports, module) {
    init_node_globals();
    console.log("[Anti-Detect \u{1F6E1}\uFE0F] anti_detection.js file loaded by Frida!");
    function init_anti_detection() {
      console.log("[Anti-Detect \u{1F6E1}\uFE0F] Executing anti_detection.js module...");
    }
    if (typeof module !== "undefined" && module.exports) {
      module.exports = init_anti_detection;
    }
  }
});

// src/lib/hooks/native_anti_detect.js
var require_native_anti_detect = __commonJS({
  "src/lib/hooks/native_anti_detect.js"() {
    init_node_globals();
    function init_native_hooks() {
      console.log("[Native C++] Initializing Native C/C++ Anti-Debug & Anti-Frida Interceptors...");
      try {
        var libc = Process.getModuleByName("libc.so");
        var strstr = libc.findExportByName("strstr");
        if (strstr) {
          Interceptor.attach(
            strstr,
            {
              onEnter: function(args) {
                try {
                  var needle = args[1] ? args[1].readUtf8String() : null;
                  if (needle && (needle.indexOf("frida") !== -1 || needle.indexOf("gum") !== -1 || needle.indexOf("gmain") !== -1 || needle.indexOf("linjector") !== -1)) {
                    this.is_frida_check = true;
                  }
                } catch (e) {
                }
              },
              onLeave: function(retval) {
                if (this.is_frida_check) {
                  console.log("[Native C++ \u{1F6E1}\uFE0F] Blocked Native Anti-Frida strstr scan!");
                  retval.replace(ptr(0));
                }
              }
            }
          );
          console.log("[+] Native strstr Anti-Frida Bypass Attached");
        }
      } catch (e) {
        console.log("[-] Native strstr Hook Error: " + e);
      }
      try {
        var libc = Process.getModuleByName("libc.so");
        var ptrace = libc.findExportByName("ptrace");
        if (ptrace) {
          Interceptor.attach(ptrace, {
            onEnter: function(args) {
              if (args[0].toInt32() === 0) {
                console.log("[Native C++ \u{1F6E1}\uFE0F] Intercepted ptrace(PTRACE_TRACEME) -> Returning 0");
              }
            },
            onLeave: function(retval) {
              retval.replace(ptr(0));
            }
          });
          console.log("[+] Native ptrace Hook Attached");
        }
      } catch (e) {
        console.log("[-] Native ptrace Hook Error: " + e);
      }
    }
    init_native_hooks();
  }
});

// src/lib/hooks/network_hook.js
init_node_globals();
console.log("[*] Network Hook Script Loaded (Universal SSL Pinning Bypass)");
try {
  require_anti_detection();
} catch (e) {
  console.log("[-] Module anti_detection.js load error: " + e);
}
try {
  require_native_anti_detect();
} catch (e) {
  console.log("[-] Module native_anti_detect.js load error: " + e);
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
    var initAnti = require_anti_detection();
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
if (typeof Java !== "undefined" && Java.available) {
  Java.perform(function() {
    console.log("[SSL Bypass \u{1F6E1}\uFE0F] Java.perform attached cleanly!");
    hook_identity_mutation();
    hook_anti_bot_fingerprinting();
    hook_java_all();
  });
}

✄
{
  "version": 3,
  "sources": ["frida-builtins:/node-globals.js", "src/lib/hooks/anti_detection.js", "src/lib/hooks/native_anti_detect.js", "src/lib/hooks/network_hook.js"],
  "mappings": "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",
  "names": ["get_dynamic_ssaid"]
}
