Java.perform(function () {
    console.log("[+] Frida In-Memory Dynamic Device Randomizer Active!");

    function generateRandomHex(len) {
        var charSet = '0123456789abcdef';
        var res = '';
        for (var i = 0; i < len; i++) res += charSet.charAt(Math.floor(Math.random() * 16));
        return res;
    }
    function generateRandomUUID() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    var freshAndroidId = generateRandomHex(16);
    var freshAdid = generateRandomUUID();
    var freshIdfv = generateRandomUUID();
    var freshSerial = "SM-F711N_" + generateRandomHex(8);

    globalThis.NMAP_PROFILE = {
        ssaid: freshAndroidId,
        adid: freshAdid,
        idfv: freshIdfv,
        serial: freshSerial
    };

    console.log("[+] Dynamic In-Memory Randomizer Generated Identifiers:");
    console.log("    - Android ID (SSAID): " + freshAndroidId);
    console.log("    - ADID (Google)    : " + freshAdid);
    console.log("    - IDFV             : " + freshIdfv);
    console.log("    - Build Serial     : " + freshSerial);

    // 1. Universal SSL Unpinning Hook
    try {
        var X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
        var SSLContext = Java.use('javax.net.ssl.SSLContext');

        var TrustManager = Java.registerClass({
            name: 'com.sensepost.test.TrustManager',
            implements: [X509TrustManager],
            methods: {
                checkClientTrusted: function (chain, authType) {},
                checkServerTrusted: function (chain, authType) {},
                getAcceptedIssuers: function () { return []; }
            }
        });

        var TrustManagers = [TrustManager.$new()];
        var SSLContext_init = SSLContext.init.overload('[Ljavax.net.ssl.KeyManager;', '[Ljavax.net.ssl.TrustManager;', 'java.security.SecureRandom');
        SSLContext_init.implementation = function (keyManager, trustManager, secureRandom) {
            SSLContext_init.call(this, keyManager, TrustManagers, secureRandom);
        };
        console.log("[+] SSL Unpinning Hook applied");
    } catch (err) {
        console.log("[-] SSL Unpinning Hook Error: " + err);
    }

    // 2. Settings.Secure (android_id -> ssaid)
    try {
        var SettingsSecure = Java.use("android.provider.Settings$Secure");
        SettingsSecure.getString.overload('android.content.ContentResolver', 'java.lang.String').implementation = function(cr, name) {
            var val = this.getString(cr, name);
            if (name === "android_id") {
                console.log("[🎲] Intercepted android_id -> " + freshAndroidId + " (Real: " + val + ")");
                return freshAndroidId;
            }
            return val;
        };

        try {
            SettingsSecure.getStringForUser.overload('android.content.ContentResolver', 'java.lang.String', 'int').implementation = function(cr, name, userHandle) {
                var val = this.getStringForUser(cr, name, userHandle);
                if (name === "android_id") {
                    console.log("[🎲] Intercepted android_id (forUser) -> " + freshAndroidId + " (Real: " + val + ")");
                    return freshAndroidId;
                }
                return val;
            };
        } catch(e2) {}
        console.log("[+] Settings.Secure (android_id) Hook applied");
    } catch (err) {
        console.log("[-] Settings.Secure Hook Error: " + err);
    }

    // 3. AppSetIdInfo (IDFV)
    try {
        var AppSetIdInfo = Java.use("com.google.android.gms.appset.AppSetIdInfo");
        var hookAppSetMethod = null;
        if (AppSetIdInfo.getId) hookAppSetMethod = "getId";
        else if (AppSetIdInfo.a) hookAppSetMethod = "a";

        if (hookAppSetMethod) {
            AppSetIdInfo[hookAppSetMethod].implementation = function() {
                console.log("[🎲] Intercepted AppSetIdInfo." + hookAppSetMethod + "() -> " + freshIdfv);
                return freshIdfv;
            };
            console.log("[+] AppSetIdInfo Hook applied");
        }
    } catch (err) {
        console.log("[-] AppSetIdInfo Hook Error: " + err);
    }

    // 4. AdvertisingIdClient (ADID / da-dd)
    try {
        var AdvertisingIdClient = Java.use("com.google.android.gms.ads.identifier.AdvertisingIdClient");
        AdvertisingIdClient.getAdvertisingIdInfo.implementation = function (context) {
            console.log("[🎲] Intercepted AdvertisingIdClient.getAdvertisingIdInfo() -> " + freshAdid);
            var Info = Java.use("com.google.android.gms.ads.identifier.AdvertisingIdClient$Info");
            return Info.$new(freshAdid, false);
        };
        console.log("[+] AdvertisingIdClient Hook applied");
    } catch (e) {
        console.log("[-] AdvertisingIdClient Hook Error: " + e);
    }

    try {
        var Info = Java.use("com.google.android.gms.ads.identifier.AdvertisingIdClient$Info");
        Info.getId.implementation = function () {
            console.log("[🎲] Intercepted AdvertisingIdClient.Info.getId() -> " + freshAdid);
            return freshAdid;
        };
    } catch (e) {}

    // 5. Build Serial
    try {
        var Build = Java.use("android.os.Build");
        Build.getSerial.implementation = function () {
            console.log("[🎲] Intercepted Build.getSerial() -> " + freshSerial);
            return freshSerial;
        };
        console.log("[+] Build.getSerial Hook applied");
    } catch (e) {
        console.log("[-] Build.getSerial Hook Error: " + e);
    }
});

// Native C++ String & Memory Interceptor for System/Binder Readback
Interceptor.attach(Module.findExportByName(null, "strstr"), {
    onEnter: function(args) {
        try {
            var haystack = args[0].readUtf8String();
            if (haystack && haystack.indexOf("3d5722eeb2399f19") !== -1) {
                console.log("[🎲 Native] Intercepted strstr matching old SSAID: 3d5722eeb2399f19!");
            }
        } catch(e) {}
    }
});
