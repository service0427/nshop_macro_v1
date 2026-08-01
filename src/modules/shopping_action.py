import os
import time
import subprocess
import xml.etree.ElementTree as ET

def run_adb(device_id: str, cmd_str: str) -> str:
    """Execute ADB shell command on target device."""
    full_cmd = ["adb", "-s", device_id, "shell", cmd_str]
    res = subprocess.run(full_cmd, capture_output=True, text=True)
    return res.stdout.strip()

def enable_accessibility(device_id: str):
    """Enable Accessibility settings so UI Automator can dump Chromium WebView DOM nodes."""
    run_adb(device_id, "settings put secure accessibility_enabled 1")

def dump_ui_tree(device_id: str) -> ET.Element:
    """Dump current UI hierarchy XML and parse into ElementTree."""
    enable_accessibility(device_id)
    sdcard_path = "/sdcard/dump_shopping_search.xml"
    tmp_path = f"/tmp/dump_shopping_search_{device_id}.xml"
    
    run_adb(device_id, f"uiautomator dump {sdcard_path}")
    subprocess.run(["adb", "-s", device_id, "pull", sdcard_path, tmp_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    tree = ET.parse(tmp_path)
    return tree.getroot()

def find_shopping_tab_bounds(root: ET.Element) -> tuple:
    """
    Search UI dump for the '쇼핑' (Shopping) category tab in top navigation area (Y < 600).
    Returns (center_x, center_y) or None.
    """
    candidates = []
    for elem in root.iter("node"):
        text = elem.attrib.get("text", "").strip()
        desc = elem.attrib.get("content-desc", "").strip()
        bounds = elem.attrib.get("bounds", "")
        
        if ("쇼핑" == text or "쇼핑" == desc or "쇼핑" in text) and bounds:
            b = bounds.replace("][", ",").replace("[", "").replace("]", "").split(",")
            if len(b) == 4:
                x1, y1, x2, y2 = map(int, b)
                # Ignore zero-width or hidden offscreen nodes
                if x2 > x1 and y2 > y1 and 100 <= y1 < 700:
                    cy = (y1 + y2) // 2
                    cx = (x1 + x2) // 2
                    candidates.append((cx, cy, bounds, text or desc))
                    
    if candidates:
        # Sort candidates by top-most Y coordinate
        candidates.sort(key=lambda c: c[1])
        best = candidates[0]
        print(f"  [✓] Found '쇼핑' Tab Node: '{best[3]}' | Bounds: {best[2]} | Center: ({best[0]}, {best[1]})")
        return best[0], best[1]
        
    return None

def click_shopping_tab(device_id: str, keyword: str = "") -> bool:
    """
    Dynamically locate and click the '쇼핑' category tab on the search result page.
    If tab node is not visible, fallback to direct Shopping Intent launch.
    """
    print(f"\n[*] [Shopping Action] Dynamically locating '쇼핑' Category Tab on [{device_id}]...")
    
    # Try up to 3 dumps/attempts
    for attempt in range(1, 4):
        try:
            root = dump_ui_tree(device_id)
            coords = find_shopping_tab_bounds(root)
            
            if coords:
                cx, cy = coords
                print(f"  [Step 1/1] Tapping '쇼핑' Category Tab at ({cx}, {cy})...")
                run_adb(device_id, f"input tap {cx} {cy}")
                time.sleep(3.5)
                print("  [✓] '쇼핑' Category Tab Clicked Successfully!")
                return True
            else:
                print(f"  [!] Attempt {attempt}: '쇼핑' tab node not visible yet. Waiting 1.5s...")
                time.sleep(1.5)
        except Exception as e:
            print(f"  [!] Dump error on attempt {attempt}: {e}")
            time.sleep(1.5)
            
    print("  [!] UI Tab node not found. Fallback: Navigating directly to Naver Shopping Intent...")
    if keyword:
        import urllib.parse
        encoded_q = urllib.parse.quote(keyword)
        shop_intent = f"naversearchapp://inappbrowser?url=https%3A%2F%2Fmsearch.shopping.naver.com%2Fsearch%2Fall%3Fquery%3D{encoded_q}"
        run_adb(device_id, f"am start -a android.intent.action.VIEW -d '{shop_intent}'")
        time.sleep(4)
        print("  [✓] Navigated directly to Naver Shopping page via Intent!")
        return True

    return False
