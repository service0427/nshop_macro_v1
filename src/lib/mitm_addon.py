import json
import os
import datetime
import random
import threading
import base64
import re
import time
from mitmproxy import http

# [NEW] Protobuf Decoding Support
try:
    import blackboxprotobuf
    HAS_BLACKBOX = True
    print("[✓] blackboxprotobuf detected.")
except ImportError:
    HAS_BLACKBOX = False
    print("[!] blackboxprotobuf NOT FOUND. Protobuf washing limited.")

class ProxyCoreWash:
    def __init__(self):
        self.lock = threading.Lock()
        self.counter = 0
        self.trigger_fired = False
        
        self.base_log_dir = os.environ.get("CAPTURE_LOG_DIR")
        if not self.base_log_dir:
            self.base_log_dir = os.path.join("logs", datetime.datetime.now().strftime("%Y%m%d/%H%M%S"))
        os.makedirs(self.base_log_dir, exist_ok=True)
        print(f"[*] Core Proxy Logging to: {self.base_log_dir}")
        self.all_packets_path = os.path.join(self.base_log_dir, "all_packets.jsonl")
        self.start_time = time.time()

        # Telemetry Offsets
        self.session_storage_offset = random.randint(-1024 * 1024 * 500, 1024 * 1024 * 500)
        self.session_boot_offset_ms = random.randint(1000 * 60 * 5, 1000 * 60 * 60 * 24)
        self.session_install_offset_sec = random.randint(3600 * 24, 3600 * 24 * 7)

        self.NOISE_PATHS = ["/font/sdf/", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".woff", ".ttf", ".zip", ".mvt", ".wav", ".js"]
        self.NOISE_HOSTS = ["facebook.com", "tivan.naver.com", "pstatic.net", "gstatic.com", "veta.naver.com", "ad.naver.com", "clova.ai"]

    def request(self, flow: http.HTTPFlow):
        # 1. [CRITICAL] TTS ExoPlayer Block
        if "api/v1/synthesize" in flow.request.path:
            flow.response = http.Response.make(500, b"TTS Blocked to prevent MediaCodec SIGBUS", {"Content-Type": "text/plain"})
            print(f"[🛡️] TTS EXOPLAYER BLOCKED: {flow.request.path[:40]}")
            return

        # 2. [PROMOTION BANNER BLOCK] Block Linchpin and Braze In-App Promotion Popups
        if "linchpin-client/v2/popups" in flow.request.path or "inappv5" in flow.request.path:
            flow.response = http.Response.make(200, b"[]", {"Content-Type": "application/json"})
            print(f"[🛡️] PROMOTION POPUP BLOCKED: {flow.request.path[:50]}")
            return

        if os.environ.get("NMAP_NO_FILTER") == "true":
            return

        host = flow.request.pretty_host
        path = flow.request.path
        is_nlog = "nlog" in path or "nlog" in host
        is_nelo = "nelo" in host or "nelo" in path
        is_shopping = "smartstore.naver.com" in host or "shopping.naver.com" in host
        
        # Allow logging traffic or shopping traffic to proceed
        if not is_shopping and not is_nlog and not is_nelo and "heartbeat" not in path:
            return

        spoofed_adid = os.environ.get("NMAP_SPOOFED_ADID", "")
        is_random_mode = bool(spoofed_adid and spoofed_adid != "none" and os.environ.get("NMAP_NO_SPOOF") != "true")

        IDENTITY_MAP = {}
        if is_random_mode:
            IDENTITY_MAP = {
                os.environ.get("NMAP_ORIG_ADID", ""): spoofed_adid,
                os.environ.get("NMAP_ORIG_NI", ""): os.environ.get("NMAP_SPOOFED_NI", ""),
                os.environ.get("NMAP_ORIG_IDFV", ""): os.environ.get("NMAP_SPOOFED_IDFV", ""),
                os.environ.get("NMAP_ORIG_SSAID", ""): os.environ.get("NMAP_SPOOFED_SSAID", ""),
                os.environ.get("NMAP_ORIG_TOKEN", ""): os.environ.get("NMAP_SPOOFED_NLOG_TOKEN", "")
            }
            # Remove empty keys to avoid matching empty strings
            IDENTITY_MAP = {k: v for k, v in IDENTITY_MAP.items() if len(k) > 6}

        def smart_cleanse(obj, is_nlogapp=False):
            if isinstance(obj, dict):
                new_dict = {}
                for k, v in obj.items():
                    if k == "storage_size" and isinstance(v, int):
                        new_dict[k] = v + self.session_storage_offset
                    elif k == "last_boot_ts" and isinstance(v, int):
                        new_dict[k] = v - self.session_boot_offset_ms
                    elif k == "install_ts" and isinstance(v, int):
                        new_dict[k] = v - self.session_install_offset_sec
                    else:
                        new_dict[k] = smart_cleanse(v, is_nlogapp)
                return new_dict
            elif isinstance(obj, list): 
                return [smart_cleanse(i, is_nlogapp) for i in obj]
            elif isinstance(obj, str):
                for real, fake in IDENTITY_MAP.items():
                    if real in obj: obj = obj.replace(real, fake)
                return obj
            elif isinstance(obj, bytes):
                for real, fake in IDENTITY_MAP.items():
                    real_b = real.encode('utf-8')
                    fake_b = fake.encode('utf-8')
                    if real_b in obj: obj = obj.replace(real_b, fake_b)
                return obj
            return obj

        # URL and Headers Wash
        try:
            flow.request.url = smart_cleanse(flow.request.url)
            for k in flow.request.headers:
                if k.lower() == "user-agent": continue
                flow.request.headers[k] = smart_cleanse(flow.request.headers[k])
        except: pass

        # Body Wash
        if flow.request.content:
            path = flow.request.path
            host = flow.request.pretty_host
            is_nlogapp = "nlogapp" in path
            is_nelo = "nelo" in host or "nelo" in path

            try:
                content_type = flow.request.headers.get("Content-Type", "").lower()
                
                # Protobuf Deep Inspection
                if ("trafficjam" in path or "x-protobuf" in content_type) and HAS_BLACKBOX:
                    import gzip as _gzip
                    raw_data = flow.request.content
                    is_gzip = raw_data.startswith(b'\x1f\x8b')
                    if is_gzip: raw_data = _gzip.decompress(raw_data)
                    
                    decoded, msg_type = blackboxprotobuf.decode_message(raw_data)
                    if decoded:
                        washed_fields = 0
                        # [ATTACK & CLEANUP] Apply ONLY to trafficjam/location requests
                        if "trafficjam/location" in path:
                            def attack_recursive(o):
                                c = 0
                                if isinstance(o, dict):
                                    for k in list(o.keys()):
                                        # Fused(5) -> LTE(3) Provider mutation
                                        if str(k) == "1" and str(o[k]) == "5":
                                            o[k] = 3
                                            c += 1
                                        elif str(k) in ["5", "6", "7"]:
                                            if str(o[k]) in ["1065353216", "1.0", "0", "0.0"]:
                                                o[k] = int(random.randint(1080000000, 1150000000))
                                                c += 1
                                        elif isinstance(o[k], (dict, list)):
                                            c += attack_recursive(o[k])
                                elif isinstance(o, list):
                                    for i in o: c += attack_recursive(i)
                                return c
                            
                            washed_fields += attack_recursive(decoded)

                            # [CLEANUP] Blanking WiFi data array to prevent common location correlation
                            for w_key in ["4", 4]:
                                if w_key in decoded and isinstance(decoded[w_key], list):
                                    decoded[w_key] = []
                                    washed_fields += 1

                        decoded = smart_cleanse(decoded, is_nlogapp)
                        encoded_payload = blackboxprotobuf.encode_message(decoded, msg_type)
                        if is_gzip: encoded_payload = _gzip.compress(encoded_payload)
                        flow.request.content = bytes(encoded_payload)
                        if washed_fields > 0:
                            print(f"[✓] PROTO JITTER WASHED: {path[:35]}... ({washed_fields} fields randomized)")
                
                # JSON/NLogApp Inspection
                elif "json" in content_type or is_nlogapp or "heartbeat" in path or is_nelo:
                    try:
                        body_json = json.loads(flow.request.content.decode('utf-8', 'ignore'))
                        
                        # --- [NEW] Screenview MAIN / Custom Impression Auto-Close Trigger ---
                        if is_nlogapp or path.endswith("/n"):
                            print(f"[🔍] nlogapp request intercepted. NMAP_CLOSE_ON_MAIN={os.environ.get('NMAP_CLOSE_ON_MAIN')}")
                            evts = body_json.get("evts", [])
                            for evt in evts:
                                # Normal Main screen check
                                is_main_screen = (evt.get("type") == "screenview" and evt.get("screen_name") == "MAIN")
                                # Reset-run custom impression main check
                                is_main_impression = (evt.get("type") == "custom.impression" and evt.get("page_url") == "https://m.naver.com" and evt.get("page_sti") == "m_main_home_app")
                                
                                if is_main_screen or is_main_impression:
                                    send_ts = body_json.get("send_ts", 0)
                                    evt_ts = evt.get("evt_ts", 0)
                                    diff_ms = send_ts - evt_ts if (send_ts and evt_ts) else 0
                                    is_fresh = diff_ms < 5000
                                    
                                    if is_fresh:
                                        serial = os.environ.get("NMAP_SERIAL")
                                        is_reset = os.environ.get("NMAP_RESET_FLAG") == "--reset"
                                        delay = 1.8 if is_reset else 0.3
                                        
                                        def deferred_stop(s, d, log_dir, close_on_main):
                                            time.sleep(d)
                                            try:
                                                import subprocess
                                                import xml.etree.ElementTree as ET
                                                import re
                                                
                                                # Create screenshots subfolder
                                                screenshots_dir = os.path.join(log_dir, "screenshots")
                                                os.makedirs(screenshots_dir, exist_ok=True)
                                                
                                                # 1. Capture screen (Before Action)
                                                now_str_1 = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                                                screenshot_path_1 = os.path.join(screenshots_dir, f"{now_str_1}_before_ai.png")
                                                print(f"[📷] Capturing screen (Before Action) for {s} -> {screenshot_path_1}")
                                                subprocess.run(["adb", "-s", s, "shell", "screencap -p /sdcard/screencap.png"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                subprocess.run(["adb", "-s", s, "pull", "/sdcard/screencap.png", screenshot_path_1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                subprocess.run(["adb", "-s", s, "shell", "rm -f /sdcard/screencap.png"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                
                                                # 2. Dump XML layout hierarchy (Before Action)
                                                xml_path_1 = os.path.join(screenshots_dir, f"{now_str_1}_before_ai.xml")
                                                print(f"[📄] Dumping XML layout (Before Action) for {s} -> {xml_path_1}")
                                                subprocess.run(["adb", "-s", s, "shell", "uiautomator dump /sdcard/window_dump.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                subprocess.run(["adb", "-s", s, "pull", "/sdcard/window_dump.xml", xml_path_1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                subprocess.run(["adb", "-s", s, "shell", "rm -f /sdcard/window_dump.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                
                                                # Pretty-print XML layout for readability
                                                if os.path.exists(xml_path_1):
                                                    try:
                                                        import xml.dom.minidom
                                                        with open(xml_path_1, "r", encoding="utf-8") as f:
                                                            xml_content = f.read().strip()
                                                        if xml_content:
                                                            dom = xml.dom.minidom.parseString(xml_content)
                                                            pretty_xml = "\n".join([line for line in dom.toprettyxml(indent="  ").splitlines() if line.strip()])
                                                            with open(xml_path_1, "w", encoding="utf-8") as f:
                                                                f.write(pretty_xml)
                                                    except Exception as xml_err:
                                                        print(f"[⚠️] Failed to pretty-print XML: {xml_err}")
                                                
                                                # 3. Locate the AI search element and compute center coordinates
                                                target_id = "com.nhn.android.search:id/searchBarAiViewGroup"
                                                center_x, center_y = None, None
                                                if os.path.exists(xml_path_1):
                                                    try:
                                                        tree = ET.parse(xml_path_1)
                                                        root = tree.getroot()
                                                        for node in root.iter('node'):
                                                            if node.attrib.get('resource-id') == target_id:
                                                                bounds_str = node.attrib.get('bounds', '')
                                                                match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
                                                                if match:
                                                                    left, top, right, bottom = map(int, match.groups())
                                                                    center_x = (left + right) // 2
                                                                    center_y = (top + bottom) // 2
                                                                    print(f"[🎯] Found AI Search button at ({center_x}, {center_y}) based on bounds: {bounds_str}")
                                                                    break
                                                    except Exception as parse_err:
                                                        print(f"[⚠️] XML parse error locating AI Search: {parse_err}")
                                                
                                                # 4. Trigger Tap Action on AI search button
                                                if center_x is not None and center_y is not None:
                                                    print(f"[⚡] Tapping AI Search button at ({center_x}, {center_y})...")
                                                    subprocess.run(["adb", "-s", s, "shell", f"input tap {center_x} {center_y}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                    
                                                    # Wait 2.2 seconds for the AI search view to load
                                                    time.sleep(2.2)
                                                    
                                                    # Capture screen (After Action)
                                                    now_str_2 = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                                                    screenshot_path_2 = os.path.join(screenshots_dir, f"{now_str_2}_after_ai.png")
                                                    print(f"[📷] Capturing screen (After Action) for {s} -> {screenshot_path_2}")
                                                    subprocess.run(["adb", "-s", s, "shell", "screencap -p /sdcard/screencap.png"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                    subprocess.run(["adb", "-s", s, "pull", "/sdcard/screencap.png", screenshot_path_2], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                    subprocess.run(["adb", "-s", s, "shell", "rm -f /sdcard/screencap.png"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                    
                                                    # Dump XML layout hierarchy (After Action)
                                                    xml_path_2 = os.path.join(screenshots_dir, f"{now_str_2}_after_ai.xml")
                                                    print(f"[📄] Dumping XML layout (After Action) for {s} -> {xml_path_2}")
                                                    subprocess.run(["adb", "-s", s, "shell", "uiautomator dump /sdcard/window_dump.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                    subprocess.run(["adb", "-s", s, "pull", "/sdcard/window_dump.xml", xml_path_2], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                    subprocess.run(["adb", "-s", s, "shell", "rm -f /sdcard/window_dump.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                    
                                                    if os.path.exists(xml_path_2):
                                                        try:
                                                            with open(xml_path_2, "r", encoding="utf-8") as f:
                                                                xml_content_2 = f.read().strip()
                                                            if xml_content_2:
                                                                dom_2 = xml.dom.minidom.parseString(xml_content_2)
                                                                pretty_xml_2 = "\n".join([line for line in dom_2.toprettyxml(indent="  ").splitlines() if line.strip()])
                                                                with open(xml_path_2, "w", encoding="utf-8") as f:
                                                                    f.write(pretty_xml_2)
                                                        except Exception as xml_err2:
                                                            print(f"[⚠️] Failed to pretty-print XML (After): {xml_err2}")
                                                else:
                                                    print("[⚠️] AI Search button element not found in the XML hierarchy layout. Skipping tap.")
                                                    
                                            except Exception as capture_err:
                                                print(f"[⚠️] Failed to execute capture/macro workflow: {capture_err}")
                                            
                                            # 5. Force stop app (Only if close_on_main is enabled)
                                            if close_on_main:
                                                print(f"[🤖] Auto-Close enabled. Force-stopping app on {s}...")
                                                subprocess.run(["adb", "-s", s, "shell", "am", "force-stop", "com.nhn.android.nmap"])
                                            else:
                                                print(f"[🤖] Auto-Close disabled. Keeping app open on {s} for manual interaction.")
                                            
                                        if serial:
                                            with self.lock:
                                                if not self.trigger_fired:
                                                    self.trigger_fired = True
                                                    close_on_main = os.environ.get("NMAP_CLOSE_ON_MAIN") == "true"
                                                    print(f"[🤖] MAIN Load detected for device [{serial}]! Starting AI Search tap macro (Auto-Close: {close_on_main})...")
                                                    threading.Thread(target=deferred_stop, args=(serial, delay, self.base_log_dir, close_on_main)).start()

                        body_json = smart_cleanse(body_json, is_nlogapp)
                        flow.request.content = json.dumps(body_json).encode('utf-8')
                        if is_nelo: print(f"[🧼] NELO Washed: {path[:40]}")
                    except:
                        flow.request.content = smart_cleanse(flow.request.content, is_nlogapp)
            except Exception as e:
                pass

    def responseheaders(self, flow: http.HTTPFlow):
        # Prevent downloading heavy UI/noise assets internally to save RAM
        content_type = flow.response.headers.get("Content-Type", "").lower()
        if any(noise in content_type for noise in ["image", "font", "video"]):
            flow.response.stream = True
        elif any(nh in flow.request.pretty_host for nh in self.NOISE_HOSTS) and ("protobuf" in content_type or "octet-stream" in content_type):
            flow.response.stream = True

    def response(self, flow: http.HTTPFlow):
        if not flow.response:
            return

        host = flow.request.pretty_host
        path = flow.request.path
        
        # Noise checking
        is_noise = any(nh in host for nh in self.NOISE_HOSTS) or any(np in path for np in self.NOISE_PATHS)
        if is_noise:
            return

        with self.lock:
            self.counter += 1
            idx = self.counter

        # 1. Filename mapping
        m = flow.request.method
        clean_path = path.split('?')[0].replace('/', '_').strip('_')
        if not clean_path: clean_path = "root"
        if len(clean_path) > 100: clean_path = clean_path[:100] + "_trunc"
        
        if "nlogapp" in path or clean_path == "nlogapp":
            filename = f"{idx:03d}_{m}_nlogapp.json"
        elif "nlog" in host or "nlog" in path:
            filename = f"{idx:03d}_{m}_{clean_path}.json"
        else:
            filename = f"{idx:03d}_{m}_{clean_path}.json"
        
        def try_parse_content(content_bytes, ct, req_path=""):
            if not content_bytes: return ""
            ct = ct.lower()
            if "image" in ct or "font" in ct or "video" in ct: return f"<MEDIA_SKIPPED: {len(content_bytes)} bytes>"
            if "json" in ct:
                try: return json.loads(content_bytes.decode('utf-8'))
                except: pass
            if "protobuf" in ct or "octet-stream" in ct or "trafficjam" in req_path:
                return "base64:" + base64.b64encode(content_bytes).decode('ascii')
            try:
                text = content_bytes.decode('utf-8')
                try: return json.loads(text)
                except: return text
            except:
                return "base64:" + base64.b64encode(content_bytes).decode('ascii')

        req_body = try_parse_content(flow.request.content, flow.request.headers.get("Content-Type", ""), path)
        res_body = try_parse_content(flow.response.content, flow.response.headers.get("Content-Type", ""), path)
        
        full_packet = {
            "index": idx,
            "timestamp": datetime.datetime.now().isoformat(),
            "request": {
                "method": m,
                "url": flow.request.url,
                "headers": dict(flow.request.headers),
                "body": req_body
            },
            "response": {
                "status_code": flow.response.status_code,
                "headers": dict(flow.response.headers),
                "body": res_body
            }
        }

        # Protobuf Decoding for logging
        if HAS_BLACKBOX and flow.request.content and ("x-protobuf" in flow.request.headers.get("Content-Type", "").lower() or "trafficjam" in path):
            try:
                decoded, _ = blackboxprotobuf.decode_message(flow.request.content)
                def make_serializable(d):
                    if isinstance(d, dict): return {k: make_serializable(v) for k, v in d.items()}
                    elif isinstance(d, list): return [make_serializable(v) for v in d]
                    elif isinstance(d, bytes):
                        try: return d.decode('utf-8')
                        except: return f"hex:{d.hex()}"
                    return d
                full_packet["request"]["body_protobuf"] = make_serializable(decoded)
            except: pass

        # JSONL Log
        with open(self.all_packets_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(full_packet, ensure_ascii=False) + "\n")

        # Compact file log
        file_path = os.path.join(self.base_log_dir, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(full_packet, f, ensure_ascii=False, indent=2)

addons = [ProxyCoreWash()]
