import sys
import os
import json
import base64

# Add the current directory to sys.path to import RouteDecoder
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from smart_route_gen import RouteDecoder

def main():
    if len(sys.argv) < 2:
        print("[!] Missing device ID.")
        sys.exit(1)
        
    device_id = sys.argv[1]
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(script_dir)
    logs_dir = os.path.join(base_dir, "logs", device_id)
    
    if not os.path.exists(logs_dir):
        print(f"[!] No logs found for device {device_id} at {logs_dir}")
        sys.exit(1)
        
    date_dirs = sorted(os.listdir(logs_dir), reverse=True)
    if not date_dirs:
        print(f"[!] No date logs found for {device_id}")
        sys.exit(1)
        
    latest_date_dir = os.path.join(logs_dir, date_dirs[0])
    session_dirs = sorted(os.listdir(latest_date_dir), reverse=True)
    if not session_dirs:
        print(f"[!] No session logs found for {device_id} on {date_dirs[0]}")
        sys.exit(1)
        
    latest_session_dir = os.path.join(latest_date_dir, session_dirs[0])
    
    # Extract latest global driving log
    driving_logs = []
    for f in os.listdir(latest_session_dir):
        if "_GET_v3_global_routeend.json" in f:
            print(f"[!] Route already ended for {device_id}. Skipping.")
            sys.exit(1)
        if "_GET_v3_global_driving.json" in f:
            try:
                idx = int(f.split("_")[0])
                driving_logs.append((idx, f))
            except ValueError:
                pass
                
    if not driving_logs:
        print(f"[!] No driving logs found in session {latest_session_dir}")
        sys.exit(1)
        
    driving_logs.sort(key=lambda x: x[0], reverse=True)
    
    route_pts = None
    dist = 0.0
    
    for idx, log_filename in driving_logs:
        log_file_path = os.path.join(latest_session_dir, log_filename)
        
        with open(log_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        resp_body = data.get("response", {}).get("body", "")
        if not resp_body or not resp_body.startswith("base64:"):
            continue
            
        b64_data = resp_body.replace("base64:", "")
        try:
            pbf_content = base64.b64decode(b64_data)
            pts = RouteDecoder.decode_pbf_path(pbf_content)
        except Exception:
            continue
            
        if pts and len(pts) > 0:
            route_pts = pts
            dist = RouteDecoder.calculate_distance(route_pts)
            break
            
    if not route_pts:
        print("[!] Decoder could not extract route geometry from ANY of the recent logs.")
        sys.exit(1)
    
    lib_dir = "/tmp/route_library"
    os.makedirs(lib_dir, exist_ok=True)
    filename = f"reload_{device_id}.json"
    full_path = os.path.join(lib_dir, filename)
    with open(full_path, "w") as f:
        json.dump(route_pts, f)
        
    print(f"ROUTE_FILE: {full_path}")
    print(f"TOTAL_DISTANCE: {dist:.2f}")

if __name__ == "__main__":
    main()
