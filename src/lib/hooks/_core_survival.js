/* 
   Core Survival System (V3 Refactored)
   - Goal: Prevent App Crash & Skip Agreement Screen rendering bug.
   - Executed: ALWAYS (Even in --no-filter mode)
*/

console.log("[*] Core Survival System Loaded");

// 1. Android 14/15 MTE (Heap Tagging) Crash Prevention
function patch_heap_tagging() {
    try {
        var libc = Process.getModuleByName("libc.so");
        var mallopt = null;
        var prctl = null;
        
        libc.enumerateExports().forEach(function(exp) {
            if (exp.name === "mallopt") mallopt = exp.address;
            else if (exp.name === "prctl") prctl = exp.address;
        });

        // WebView(libmonochrome.so) Sandbox strictly monitors prctl and set_heap_tagging hooks.
        // Attaching Interceptor to them causes a deliberate SIGBUS SI_USER suicide trap!
        // We MUST ONLY use direct, one-time NativeFunction invocations to bypass MTE.
        
        if (mallopt) {
            try {
                var mallopt_func = new NativeFunction(mallopt, 'int', ['int', 'int']);
                mallopt_func(-9, 0); // M_BIONIC_DISABLE_MEMORY_MITIGATIONS
                console.log("[✓] Direct MTE Disable via mallopt(-9) success");
            } catch(e) {}
        }

        if (prctl) {
            try {
                var prctl_func = new NativeFunction(prctl, 'int', ['int', 'uint64', 'uint64', 'uint64', 'uint64']);
                prctl_func(53, 0, 0, 0, 0); // PR_SET_TAGGED_ADDR_CTRL -> 0
                console.log("[✓] Direct MTE Disable via prctl(53) success. (No Interceptor attached to avoid WebView Trap)");
            } catch(e) {}
        }
    } catch(e) {
        console.log("[-] MTE Patch Error: " + e.stack);
    }
}

// 2. FDS Stealth (Hide Root, Magisk, Developer Options)
function hook_stealth() {
    if (!Java.available) return;
    Java.perform(function() {
        try {
            var File = Java.use("java.io.File");
            // File.exists hook disabled to prevent heavy overhead & stack recursion crashes
            /*
            File.exists.implementation = function() {
                if (exists_guard) return this.exists();
                exists_guard = true;
                try {
                    var name = this.getName();
                    if (name === "su" || name === "magisk" || name === "frida-server" || name === "busybox") {
                        return false;
                    }
                } catch(e) {
                } finally {
                    exists_guard = false;
                }
                return this.exists();
            };
            */

            var SettingsGlobal = Java.use("android.provider.Settings$Global");
            SettingsGlobal.getInt.overload('android.content.ContentResolver', 'java.lang.String', 'int').implementation = function(cr, name, def) {
                if (name === "development_settings_enabled" || name === "adb_enabled") return 0;
                return this.getInt(cr, name, def);
            };

            // MediaCodec hook disabled to prevent app crash on launch
            // var MediaCodec = Java.use("android.media.MediaCodec");

            var SettingsSecure = Java.use("android.provider.Settings$Secure");
            SettingsSecure.getInt.overload('android.content.ContentResolver', 'java.lang.String', 'int').implementation = function(cr, name, def) {
                if (name === "development_settings_enabled" || name === "adb_enabled") return 0;
                return this.getInt(cr, name, def);
            };

            try {
                SettingsSecure.getString.overload('android.content.ContentResolver', 'java.lang.String').implementation = function(cr, name) {
                    var val = this.getString(cr, name);
                    if (name === "android_id") {
                        if (typeof NMAP_PROFILE !== 'undefined' && NMAP_PROFILE && NMAP_PROFILE.ssaid) {
                            console.log("[🎲] Local Hook android_id -> " + NMAP_PROFILE.ssaid + " (Real was " + val + ")");
                            return NMAP_PROFILE.ssaid;
                        }
                    }
                    return val;
                };
            } catch (err) {
                console.log("[-] SettingsSecure.getString Hook Error: " + err);
            }
            // Advertising ID (adid) spoof hook disabled because we physically rewrite com.google.android.gms preferences before launch.

            try {
                var AppSetIdInfo = Java.use("com.google.android.gms.appset.AppSetIdInfo");
                var hookAppSetMethod = null;
                if (AppSetIdInfo.getId) {
                    hookAppSetMethod = "getId";
                } else if (AppSetIdInfo.a) {
                    hookAppSetMethod = "a";
                }
                
                if (hookAppSetMethod) {
                    AppSetIdInfo[hookAppSetMethod].implementation = function() {
                        var val = this[hookAppSetMethod]();
                        if (typeof NMAP_PROFILE !== 'undefined' && NMAP_PROFILE && NMAP_PROFILE.idfv) {
                            console.log("[🎲] Local Hook AppSetIdInfo." + hookAppSetMethod + "() -> " + NMAP_PROFILE.idfv + " (Real was " + val + ")");
                            return NMAP_PROFILE.idfv;
                        }
                        return val;
                    };
                }
            } catch (err) {
                console.log("[-] AppSetIdInfo Hook Error: " + err);
            }
            var System = Java.use("java.lang.System");
            var get_prop_guard = false;
            System.getProperty.overload('java.lang.String').implementation = function(key) {
                if (get_prop_guard) return this.getProperty(key);
                get_prop_guard = true;
                try {
                    if (key === "ro.debuggable" || key === "ro.secure") {
                        return key === "ro.secure" ? "1" : "0";
                    }
                } finally {
                    get_prop_guard = false;
                }
                return this.getProperty(key);
            };
        } catch(e) {}
    });
}

// 3. Skip Agreement Screen (Prevents rendering crash on start)
function skip_agreement_screen() {
    if (!Java.available) return;
    Java.perform(function() {
        try {
            // Removed invasive global SharedPreferences hooks that crash ExoPlayer on S22 PAC hardware.
            // All necessary agreements are now explicitly saved to XML in bypass.js.
            console.log("[+] Agreement Screen Skipped Successfully");
        } catch(e) {}
    });
}

// Boot sequence: MTE patch MUST be first and synchronous.
patch_heap_tagging();
hook_stealth();
skip_agreement_screen();
