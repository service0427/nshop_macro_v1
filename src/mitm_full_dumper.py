import json
import os
import time
from urllib.parse import urlparse
from mitmproxy import http

class FullTrafficDumper:
    def __init__(self):
        self.count = 0

    def response(self, flow: http.HTTPFlow):
        try:
            self.count += 1
            log_dir = os.environ.get("LOG_SAVE_DIR", "/home/tech/nshop_macro_v1/logs")
            os.makedirs(log_dir, exist_ok=True)
            
            parsed = urlparse(flow.request.pretty_url)
            host = parsed.netloc.replace(":", "_")
            path_name = parsed.path.strip("/").replace("/", "_") or "root"
            if len(path_name) > 30:
                path_name = path_name[:30]
            
            filename = f"{self.count:03d}_{flow.request.method}_{host}_{path_name}.json"
            out_path = os.path.join(log_dir, filename)

            headers = dict(flow.request.headers)
            
            body_content = ""
            try:
                if flow.request.text:
                    try:
                        body_content = json.loads(flow.request.text)
                    except Exception:
                        body_content = flow.request.text[:5000]
            except Exception:
                body_content = "<binary content>"

            res_headers = dict(flow.response.headers) if flow.response else {}
            res_body = ""
            if flow.response:
                try:
                    if flow.response.text:
                        try:
                            res_body = json.loads(flow.response.text)
                        except Exception:
                            res_body = flow.response.text[:5000]
                except Exception:
                    res_body = "<binary content>"

            data = {
                "index": self.count,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "request": {
                    "method": flow.request.method,
                    "url": flow.request.pretty_url,
                    "headers": headers,
                    "body": body_content
                },
                "response": {
                    "status_code": flow.response.status_code if flow.response else 0,
                    "headers": res_headers,
                    "body": res_body
                }
            }

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            summary_log = os.path.join(log_dir, "all_requests.log")
            with open(summary_log, "a", encoding="utf-8") as f:
                cookie_str = headers.get("Cookie", headers.get("cookie", ""))
                f.write(f"[{data['timestamp']}] {flow.request.method} {flow.request.pretty_url} | Status: {data['response']['status_code']} | Cookie: {cookie_str[:80]}\n")
        except Exception as e:
            print(f"[FullTrafficDumper Error]: {e}", flush=True)

addons = [FullTrafficDumper()]
