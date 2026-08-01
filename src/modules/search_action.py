import subprocess
import time
import urllib.parse

DEFAULT_SAMSUNG_IME = "com.samsung.android.honeyboard/.service.HoneyBoardService"
ADB_IME = "com.android.adbkeyboard/.AdbIME"
NAVER_PKG = "com.nhn.android.search"

def run_adb(device_id: str, cmd_str: str) -> str:
    """Execute ADB shell command on target device."""
    full_cmd = ["adb", "-s", device_id, "shell", cmd_str]
    res = subprocess.run(full_cmd, capture_output=True, text=True)
    return res.stdout.strip()

def setup_adb_keyboard(device_id: str):
    """Enable and set ADBKeyboard IME for typing non-ASCII / Unicode Hangeul."""
    run_adb(device_id, f"ime enable {ADB_IME}")
    run_adb(device_id, f"ime set {ADB_IME}")

def restore_samsung_keyboard(device_id: str):
    """Restore default Samsung HoneyBoard IME."""
    run_adb(device_id, f"ime set {DEFAULT_SAMSUNG_IME}")

def unlock_screen_and_focus(device_id: str):
    """Collapse statusbar, dismiss keyguard, and ensure main screen ready."""
    run_adb(device_id, "am force-stop s.aa.cp 2>/dev/null || true")
    run_adb(device_id, "am force-stop com.samsung.android.mtp 2>/dev/null || true")
    run_adb(device_id, "cmd statusbar collapse; input keyevent 224; input keyevent 82; wm dismiss-keyguard")

def execute_keyboard_search(device_id: str, query: str) -> bool:
    """
    Macro Action Method A: ADB Keyboard & UI Tap Search.
    1. Focus SearchHomePage
    2. Tap Search Bar (540, 561)
    3. Type query via ADBKeyboard broadcast
    4. Submit Search via Search Button tap (960, 202)
    """
    print(f"\n[Macro Action - Method A (ADB Keyboard)] Target: {device_id} | Query: '{query}'")
    unlock_screen_and_focus(device_id)
    setup_adb_keyboard(device_id)
    time.sleep(0.5)
    
    # 1. Launch SearchHomePage Activity
    run_adb(device_id, f"am start -n {NAVER_PKG}/.ui.pages.SearchHomePage")
    time.sleep(2.5)
    
    # 2. Tap Search Bar to open SearchWindowSuggestListActivity
    print("  [Step 1/3] Tapping Search Bar at (540, 561)...")
    run_adb(device_id, "input tap 540 561")
    time.sleep(1.5)
    
    # 3. Broadcast typing text using ADBKeyboard
    print(f"  [Step 2/3] Typing query '{query}' via ADB Keyboard broadcast...")
    run_adb(device_id, f"am broadcast -a ADB_INPUT_TEXT --es msg '{query}'")
    time.sleep(1.0)
    
    # Send ENTER key in case search button tap is needed
    run_adb(device_id, "input keyevent 66")
    time.sleep(1.0)

    # 4. Tap Search Submit Button
    print("  [Step 3/3] Tapping Search Button at (960, 202)...")
    run_adb(device_id, "input tap 960 202")
    time.sleep(3.5)
    
    encoded_q = urllib.parse.quote(query)
    search_url = f"https://m.search.naver.com/search.naver?query={encoded_q}"
    print(f"\n[PAGE URL LOG] Naver Main Search Page Executed URL:")
    print(f"  🔗 {search_url}")
    print(f"--------------------------------------------------------------------------")
    print("  [✓] Method A (ADB Keyboard Search) Completed!")
    return True

def generate_naver_search_url(keyword: str) -> str:
    """
    Generate dynamic Naver search URL matching user specification:
    sm=mtp_sug.top&where=m&query={query}&ackey={ackey}&acq={acq}&acr={acr}&qdt=0
    """
    if not keyword:
        return "https://m.naver.com"
    import random
    import re
    clean_keyword = re.sub(r"\s+", " ", keyword.strip())
    encoded_query = urllib.parse.quote(clean_keyword)
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    ackey = "".join(random.choice(chars) for _ in range(8))
    acq_length = max(1, int(len(clean_keyword) * 0.6))
    acq = urllib.parse.quote(clean_keyword[:acq_length])
    acr = random.randint(1, 10)
    return f"https://m.search.naver.com/search.naver?sm=mtp_sug.top&where=m&query={encoded_query}&ackey={ackey}&acq={acq}&acr={acr}&qdt=0"

def execute_intent_search(device_id: str, query: str) -> bool:
    """
    Macro Action Method B: Direct 1-Step Dynamic Intent Search.
    Launches Naver App DIRECTLY with user-specified dynamic rolling Naver search URL.
    Bypasses main SearchHomePage completely.
    """
    print(f"\n[Macro Action - Method B (Direct 1-Step Intent)] Target: {device_id} | Query: '{query}'")
    unlock_screen_and_focus(device_id)
    
    # 1. Generate Dynamic Rolling Search URL
    dynamic_url = generate_naver_search_url(query)
    print(f"  [1-Step Direct Launch] Triggering Dynamic Rolling Search Intent URL:")
    print(f"     🔗 {dynamic_url}")
    
    # 2. Launch Naver App DIRECTLY with Intent URL in 1 step
    run_adb(device_id, f"am start -a android.intent.action.VIEW -d \"{dynamic_url}\" {NAVER_PKG}")
    time.sleep(2.5)
    
    # Auto-dismiss SSL Warning Dialog ("보안 인증서 오류 안내") if popped up during MITM proxying
    try:
        xml_res = run_adb(device_id, "uiautomator dump /sdcard/ssl_chk.xml >/dev/null 2>&1 && cat /sdcard/ssl_chk.xml 2>/dev/null || true")
        if "보안 인증서 오류 안내" in xml_res or "계속보기" in xml_res:
            print("  [*] SSL Warning Dialog detected! Auto-clicking [계속보기] (Proceed)...")
            run_adb(device_id, "input tap 655 1536")
            time.sleep(1.5)
    except Exception:
        pass
    
    print("  [✓] Method B (Direct 1-Step Intent Search) Executed Successfully!")
    return True
