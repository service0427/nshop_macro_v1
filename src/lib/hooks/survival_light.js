/* 
   Core Survival System (Lightweight for A-Series)
   - Goal: Prevent App Crash with minimal performance overhead.
*/

console.log("[*] Core Survival System Light Loaded");

function patch_mte_light() {
    try {
        var libc = Process.getModuleByName("libc.so");
        var prctl = null;
        libc.enumerateExports().forEach(function(exp) { if (exp.name === "prctl") prctl = exp.address; });
        if (prctl) {
            // Proactively disable MTE via direct call (No Interceptor attach to prevent ANR/SIGBUS)
            var prctl_func = new NativeFunction(prctl, 'int', ['int', 'uint64', 'uint64', 'uint64', 'uint64']);
            prctl_func(53, 0, 0, 0, 0); // PR_SET_TAGGED_ADDR_CTRL
            console.log("[✓] MTE Patch Active (Direct Call)");
        }
    } catch(e) {}
}

// Execute MTE patch synchronously before anything else
patch_mte_light();
