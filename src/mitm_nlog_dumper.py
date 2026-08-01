import json
import os
import time
from mitmproxy import http

class NLogDumper:
    def __init__(self):
        self.count = 0

    def response(self, flow: http.HTTPFlow):
        if "nlog.naver.com/nlogapp" in flow.request.pretty_url:
            self.count += 1
            log_dir = os.environ.get("LOG_SAVE_DIR", "/home/tech/nshop_macro_v1/logs")
            os.makedirs(log_dir, exist_ok=True)
            
            headers = dict(flow.request.headers)
            body_json = {}
            try:
                body_json = json.loads(flow.request.get_text())
            except Exception:
                body_json = flow.request.get_text()

            res_headers = dict(flow.response.headers) if flow.response else {}
            res_body = flow.response.get_text() if flow.response else ""

            data = {
                "index": self.count,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "request": {
                    "method": flow.request.method,
                    "url": flow.request.pretty_url,
                    "headers": headers,
                    "body": body_json
                },
                "response": {
                    "status_code": flow.response.status_code if flow.response else 0,
                    "headers": res_headers,
                    "body": res_body
                }
            }

            out_path = os.path.join(log_dir, f"nlogapp_{self.count:03d}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Always update nlogapp.json as the latest snapshot
            latest_path = os.path.join(log_dir, "nlogapp.json")
            with open(latest_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

addons = [NLogDumper()]
