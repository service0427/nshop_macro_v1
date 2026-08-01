import json
import os
import datetime
import threading
import base64
from mitmproxy import http

class PurePassiveLoggingProxy:
    def __init__(self):
        self.lock = threading.Lock()
        self.counter = 0
        self.base_log_dir = os.environ.get("CAPTURE_LOG_DIR")
        if not self.base_log_dir:
            self.base_log_dir = os.path.join("/home/tech/nshop_macro_v1/logs/mitm_pure", datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(self.base_log_dir, exist_ok=True)
        print(f"[*] Pure Passive MITM Logging initialized -> {self.base_log_dir}")
        self.all_packets_path = os.path.join(self.base_log_dir, "all_packets.jsonl")

    def request(self, flow: http.HTTPFlow):
        # Absolutely ZERO tampering / ZERO modification / 100% Pure Pass-through
        pass

    def response(self, flow: http.HTTPFlow):
        if not flow.response:
            return

        host = flow.request.pretty_host
        path = flow.request.path
        
        # Only filter heavy noise media assets for clean json logging
        content_type = flow.response.headers.get("Content-Type", "").lower()
        if any(noise in content_type for noise in ["image", "font", "video"]):
            return

        with self.lock:
            self.counter += 1
            idx = self.counter

        m = flow.request.method
        clean_path = path.split('?')[0].replace('/', '_').strip('_')
        if not clean_path: clean_path = "root"
        if len(clean_path) > 60: clean_path = clean_path[:60] + "_trunc"
        
        filename = f"{idx:03d}_{m}_{clean_path}.json"

        def parse_body(content_bytes, ct):
            if not content_bytes: return ""
            ct = ct.lower()
            if "json" in ct:
                try: return json.loads(content_bytes.decode('utf-8'))
                except: pass
            try:
                text = content_bytes.decode('utf-8')
                try: return json.loads(text)
                except: return text
            except:
                return "base64:" + base64.b64encode(content_bytes).decode('ascii')

        req_body = parse_body(flow.request.content, flow.request.headers.get("Content-Type", ""))
        res_body = parse_body(flow.response.content, flow.response.headers.get("Content-Type", ""))

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

        # Save individual JSON log
        file_path = os.path.join(self.base_log_dir, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(full_packet, f, ensure_ascii=False, indent=2)

addons = [PurePassiveLoggingProxy()]
