import os
import subprocess
import time
import threading
import socket
import json
from flask import Flask, Response, render_template_string, request, jsonify

app = Flask(__name__)

# --- CONFIGURATION ---
PORT = 5000
REFRESH_INTERVAL = 0.12  # 약 8fps (모니터링 최적, ADB 부하 최소화)

# Find initial connected devices count to dynamically set MAX_SLOTS
def get_connected_devices_count():
    try:
        output = subprocess.check_output(["adb", "devices"], timeout=3).decode("utf-8")
        lines = output.strip().split("\n")[1:]
        count = sum(1 for line in lines if line.strip() and "device" in line)
        return max(10, count)
    except:
        return 10

MAX_SLOTS = get_connected_devices_count()

def load_global_config():
    conf = {}
    conf_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wifi_multi", "config.conf")
    if os.path.exists(conf_path):
        try:
            with open(conf_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        parts = line.split("=", 1)
                        k = parts[0].strip()
                        v = parts[1].strip().strip("\"").strip("\'")
                        conf[k] = v
        except:
            pass
    return conf

LOG_BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wifi_multi", "logs")
EXCLUDED_DEVICES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wifi_multi", "config", "excluded_devices.json")

def load_excluded_devices():
    if os.path.exists(EXCLUDED_DEVICES_PATH):
        try:
            with open(EXCLUDED_DEVICES_PATH, "r") as f:
                return json.load(f)
        except:
            pass
    return []

def save_excluded_devices(devices_list):
    try:
        os.makedirs(os.path.dirname(EXCLUDED_DEVICES_PATH), exist_ok=True)
        with open(EXCLUDED_DEVICES_PATH, "w") as f:
            json.dump(devices_list, f, indent=2)
    except:
        pass

USB_PORTS_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wifi_multi", "config", "usb_ports.json")

def load_usb_ports():
    if os.path.exists(USB_PORTS_FILE_PATH):
        try:
            with open(USB_PORTS_FILE_PATH, "r") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_usb_ports(mapping):
    try:
        os.makedirs(os.path.dirname(USB_PORTS_FILE_PATH), exist_ok=True)
        with open(USB_PORTS_FILE_PATH, "w") as f:
            json.dump(mapping, f, indent=2)
    except:
        pass


# 기기 위치 고정 및 진단 캐시
device_slots = [None] * MAX_SLOTS
diag_cache = {}

# --- HTML TEMPLATE ---
# HTML template path
TEMPLATE_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "monitor.html")

def get_html_template():
    try:
        with open(TEMPLATE_FILE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error loading template: {e}"

def get_device_diagnostics(serial, excluded_list=None, usb_ports=None):
    info = {
        "status": "IDLE",
        "ip": "N/A",
        "temp": "??",
        "battery": "??",
        "latest_log": "-",
        "current_task": None,
        "disabled": False,
        "usb_path": "N/A"
    }
    
    # 1. Check Working Status (Lightweight)
    try:
        subprocess.check_output(["pgrep", "-f", f"lib/main.sh {serial}"])
        info["status"] = "WORKING"
    except:
        info["status"] = "IDLE"
        try:
            task_info_path = os.path.join(LOG_BASE_DIR, serial, "current_task.json")
            if os.path.exists(task_info_path):
                with open(task_info_path, 'r') as f:
                    cdata = json.load(f)
                    cstatus = cdata.get("status")
                    if cstatus in ["IP_COOLDOWN", "COOLDOWN", "PENALTY", "UNAUTHORIZED"]:
                        info["status"] = cstatus
        except:
            pass

    # 2. Get Battery & Temp (Cached)
    try:
        batt_raw = subprocess.check_output(["adb", "-s", serial, "shell", "dumpsys battery"], timeout=5).decode()
        for line in batt_raw.splitlines():
            if "level:" in line: info["battery"] = line.split(":")[1].strip()
            if "temperature:" in line: info["temp"] = int(line.split(":")[1].strip()) / 10
    except:
        pass

    # 3. Find Latest Task Details from execution.log & session files (Safety fallback / Contrast)
    task_data = {
        "dest_name": "Unknown",
        "dest_id": "",
        "start_ts": 0,
        "target_sec": 0,
        "total_dist_km": 0.0,
        "remaining_dist_km": 0.0,
        "avg_speed_kmh": 0.0,
        "status": "IDLE"
    }
    
    # 3-1. Try parsing logs directory structure
    latest_session_dir = None
    latest_date_str = None
    try:
        dev_log_dir = os.path.join(LOG_BASE_DIR, serial)
        if os.path.exists(dev_log_dir):
            dates = sorted([d for d in os.listdir(dev_log_dir) if d.isdigit()], reverse=True)
            if dates:
                latest_date_str = dates[0]
                date_dir = os.path.join(dev_log_dir, latest_date_str)
                sessions = sorted([s for s in os.listdir(date_dir) if "_" in s], reverse=True)
                if sessions:
                    latest_session_dir = os.path.join(date_dir, sessions[0])
                    # Revert latest_log to show the session directory name
                    info["latest_log"] = sessions[0]
                    parts = sessions[0].split("_")
                    if len(parts) >= 2:
                        task_data["dest_id"] = parts[1]
                        
                    time_str = parts[0]
                    try:
                        dt_str = f"{latest_date_str} {time_str}"
                        struct_time = time.strptime(dt_str, "%Y%m%d %H%M%S")
                        task_data["start_ts"] = int(time.mktime(struct_time))
                    except:
                        pass
    except Exception as e:
        print(f"Error resolving latest session dir: {e}", flush=True)

    # 3-2. Load values from session_summary.json (Primary metadata container)
    session_status = None
    if latest_session_dir and os.path.exists(latest_session_dir):
        summary_path = os.path.join(latest_session_dir, "session_summary.json")
        if os.path.exists(summary_path):
            try:
                with open(summary_path, 'r') as f:
                    sdata = json.load(f)
                    info["ip"] = sdata.get("real_ip", info["ip"])
                    session_status = sdata.get("status", None)
                    if sdata.get("total_distance_km"):
                        task_data["total_dist_km"] = sdata.get("total_distance_km")
            except:
                pass

    # 3-3. Load values from current_task.json if available as fallback
    try:
        task_info_path = os.path.join(LOG_BASE_DIR, serial, "current_task.json")
        if os.path.exists(task_info_path):
            with open(task_info_path, 'r') as f:
                cdata = json.load(f)
                for k, v in cdata.items():
                    if v is not None:
                        task_data[k] = v
                info["ip"] = cdata.get("real_ip", info["ip"])
    except:
        pass

    # 3-4. Parse execution.log for live progress
    if latest_session_dir and os.path.exists(latest_session_dir):
        exec_log_path = os.path.join(latest_session_dir, "execution.log")
        if os.path.exists(exec_log_path):
            try:
                with open(exec_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    log_lines = f.readlines()
                
                dest_name = None
                total_dist = None
                target_sec = None
                latest_progress = None
                
                task_id = None
                for line in log_lines:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    
                    if "TASK STARTED" in line_str and "LogID:" in line_str:
                        try:
                            task_id = line_str.split("LogID:")[-1].replace(")", "").strip()
                        except:
                            pass
                    
                    if "Destination:" in line_str:
                        d_part = line_str.split("Destination:")[-1].strip()
                        if " (ID:" in d_part:
                            dest_name = d_part.split(" (ID:")[0].strip()
                        else:
                            dest_name = d_part
                    
                    if "Initial Path Loaded:" in line_str:
                        try:
                            dist_str = line_str.split("Initial Path Loaded:")[-1].replace("km", "").strip()
                            total_dist = float(dist_str)
                        except:
                            pass
                            
                    if "Exact Server Arrival Time:" in line_str:
                        try:
                            sec_str = line_str.split("Exact Server Arrival Time:")[-1].replace("s", "").strip()
                            target_sec = int(sec_str)
                        except:
                            pass
                    elif "Session Goal :" in line_str:
                        try:
                            sec_str = line_str.split("Session Goal :")[-1].split("s")[0].strip()
                            target_sec = int(sec_str)
                        except:
                            pass

                    if "Progress:" in line_str and "remaining" in line_str:
                        latest_progress = line_str

                if dest_name:
                    task_data["dest_name"] = dest_name
                if total_dist:
                    task_data["total_dist_km"] = total_dist
                if target_sec:
                    task_data["target_sec"] = target_sec
                if task_id and info["latest_log"] == sessions[0]:
                    info["latest_log"] = f"{sessions[0]} (Task:{task_id})"
                
                if latest_progress:
                    try:
                        p_part = latest_progress.split("Progress:")[-1].strip()
                        rem_str = p_part.split("km remaining")[0].strip()
                        task_data["remaining_dist_km"] = float(rem_str)
                        
                        if "Time:" in p_part:
                            t_part = p_part.split("Time:")[-1].strip()
                            parts = t_part.split("/")
                            elapsed_sec = int(parts[0].replace("s", "").strip())
                            total_sec = int(parts[1].replace("s", "").strip())
                            task_data["start_ts"] = int(time.time()) - elapsed_sec
                            task_data["target_sec"] = total_sec
                    except:
                        pass
            except:
                pass
                
    # Determine the task final status based on whether main.sh is running and log messages
    is_working = (info["status"] == "WORKING")
    log_has_success = False
    
    # Double check log for SUCCESS or SUCCESSFUL message
    if latest_session_dir and os.path.exists(latest_session_dir):
        exec_log_path = os.path.join(latest_session_dir, "execution.log")
        if os.path.exists(exec_log_path):
            try:
                with open(exec_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()[-20:]
                for line in lines:
                    if "SUCCESS" in line or "SUCCESSFUL" in line:
                        log_has_success = True
                        break
            except:
                pass

    if is_working:
        # Resolve detailed status from task_data (enriched by current_task.json / session_summary)
        detailed_status = task_data.get("status", "DRIVING")
        if detailed_status in ["IDLE", "SUCCESS", "ARRIVED", "Unknown", ""]:
            detailed_status = "DRIVING"
            
        info["status"] = detailed_status
        task_data["status"] = detailed_status
        info["current_task"] = task_data
    else:
        # If not running, but session_summary states ARRIVED or logs suggest success, mark as SUCCESS
        if session_status == "ARRIVED" or log_has_success:
            info["status"] = "SUCCESS"
            task_data["status"] = "SUCCESS"
            info["current_task"] = task_data
        else:
            info["status"] = "IDLE"
            info["current_task"] = None

    # 3-5. Local cooldown status override and exclude_until tracking removed as requested.
    # Server manages all allocation blocking, so client monitor does not lock status.
    info["cooldown_info"] = None
            
    if usb_ports and serial in usb_ports:
        info["usb_path"] = usb_ports[serial]

    if excluded_list and serial in excluded_list:
        info["disabled"] = True
        if info["status"] not in ["WORKING", "DRIVING"]:
            info["status"] = "DISABLED"
            
    return info

ORDER_FILE_PATH = "/home/tech/nmap_multi_v1/wifi_multi/config/device_order.json"

def refresh_device_slots():
    global device_slots, MAX_SLOTS
    try:
        output = subprocess.check_output(["adb", "devices", "-l"], timeout=5).decode("utf-8")
        lines = output.strip().split("\n")[1:]
        current_connected = {}
        usb_mapping_updates = {}
        for line in lines:
            if not line.strip() or "device" not in line: continue
            parts = line.split()
            serial = parts[0]
            model = "Unknown"
            usb_path = "N/A"
            for p in parts:
                if p.startswith("model:"): model = p.split(":")[1]
                if p.startswith("usb:"): usb_path = p
            current_connected[serial] = model
            if usb_path != "N/A":
                usb_mapping_updates[serial] = usb_path

        # Check if custom order config exists
        order_list = []
        if os.path.exists(ORDER_FILE_PATH):
            try:
                with open(ORDER_FILE_PATH, 'r') as f:
                    order_list = json.load(f)
            except:
                pass

        # Load excluded devices list once
        excluded = load_excluded_devices()

        # Load and update USB ports mapping
        usb_ports = load_usb_ports()
        usb_changed = False
        for serial, usb_path in usb_mapping_updates.items():
            if usb_ports.get(serial) != usb_path:
                usb_ports[serial] = usb_path
                usb_changed = True
        if usb_changed:
            save_usb_ports(usb_ports)

        # Merge any newly connected devices and automatically sort alphabetically
        needs_save = False
        if not order_list:
            order_list = sorted(list(current_connected.keys()))
            needs_save = True
        else:
            # Append new devices
            for serial in current_connected.keys():
                if serial not in order_list:
                    order_list.append(serial)
                    needs_save = True
            # Always ensure alphabetical sorting order to prevent messy dynamic layout
            sorted_order = sorted(order_list)
            if sorted_order != order_list:
                order_list = sorted_order
                needs_save = True
        
        if needs_save:
            try:
                os.makedirs(os.path.dirname(ORDER_FILE_PATH), exist_ok=True)
                with open(ORDER_FILE_PATH, 'w') as f:
                    json.dump(order_list, f, indent=2)
            except Exception as ex:
                print(f"Error saving device order: {ex}", flush=True)

        MAX_SLOTS = len(order_list)
        while len(device_slots) < MAX_SLOTS:
            device_slots.append(None)
        if len(device_slots) > MAX_SLOTS:
            device_slots = device_slots[:MAX_SLOTS]

        for i, serial in enumerate(order_list):
            if serial in current_connected:
                diag = get_device_diagnostics(serial, excluded, usb_ports)
                device_slots[i] = {
                    "id": serial,
                    "model": current_connected[serial],
                    "offline": False,
                    **diag
                }
            else:
                # Device is offline but slot position is strictly preserved
                old_slot = device_slots[i]
                old_model = old_slot.get("model", "Unknown") if old_slot else "Unknown"
                
                # Check if offline device is disabled
                is_disabled = (serial in excluded)
                usb_path = usb_ports.get(serial, "N/A")
                
                device_slots[i] = {
                    "id": serial,
                    "model": old_model,
                    "offline": True,
                    "status": "DISABLED" if is_disabled else "OFFLINE",
                    "ip": "N/A",
                    "temp": "??",
                    "battery": "??",
                    "latest_log": "-",
                    "current_task": None,
                    "disabled": is_disabled,
                    "usb_path": usb_path
                }
    except:
        pass

def diag_background_thread():
    while True:
        refresh_device_slots()
        time.sleep(10) # 10초마다 무거운 진단 갱신

# 초기 1회 실행 후 스레드 시작
refresh_device_slots()
threading.Thread(target=diag_background_thread, daemon=True).start()

@app.route('/')
def index():
    device_id = request.args.get('device_id', '').strip()
    hostname = socket.gethostname()
    return render_template_string(get_html_template(), slots=device_slots, MAX_SLOTS=MAX_SLOTS, hostname=hostname, target_device_id=device_id)

@app.route('/status')
def status():
    # Return the current parsed device states for seamless AJAX updates
    return jsonify({"slots": device_slots})

@app.route('/api/toggle_device', methods=['POST'])
def toggle_device():
    try:
        data = request.get_json() or {}
        serial = data.get("device_id")
        if not serial:
            return jsonify({"status": "error", "message": "Missing device_id"}), 400
        
        excluded = load_excluded_devices()
        if serial in excluded:
            excluded.remove(serial)
            state = "ENABLED"
        else:
            excluded.append(serial)
            state = "DISABLED"
        
        save_excluded_devices(excluded)
        
        # 즉시 로컬 진단 갱신하여 화면 업데이트 반영
        refresh_device_slots()
        
        return jsonify({"status": "success", "state": state, "excluded": excluded})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/reset_device_penalty', methods=['POST'])
def reset_device_penalty():
    try:
        data = request.get_json() or {}
        serial = data.get("serial")
        if not serial:
            return jsonify({"status": "error", "message": "Missing serial"}), 400
            
        # 1. External API 호출 (리턴을 전혀 기다리지 않고 스레드로 백그라운드 격발!)
        def trigger_external_reset(dev_id):
            try:
                import requests
                config = load_global_config()
                admin_server = config.get("ADMIN_API_SERVER", "114.207.112.245:8001")
                requests.get(f"http://{admin_server}/api/v1/admin/device/reset_penalty?device_id={dev_id}", timeout=5)
            except Exception as ex:
                print(f"Async external reset error: {ex}", flush=True)

        threading.Thread(target=trigger_external_reset, args=(serial,), daemon=True).start()
            
        # 2. Local Reset (current_task.json 갱신 또는 삭제)
        task_info_path = os.path.join(LOG_BASE_DIR, serial, "current_task.json")
        if os.path.exists(task_info_path):
            try:
                with open(task_info_path, 'r') as f:
                    cdata = json.load(f)
                cdata["status"] = "IDLE"
                with open(task_info_path, 'w') as f:
                    json.dump(cdata, f, indent=4)
            except:
                try:
                    os.remove(task_info_path)
                except:
                    pass
        
        # 3. 로컬 메모리 상태 즉시 갱신 (반응성 극대화)
        refresh_device_slots()
                   
        return jsonify({"status": "success", "message": "Reset triggered successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/click/<dev_id>')
def click(dev_id):
    x_pct = float(request.args.get('x_pct', 0))
    y_pct = float(request.args.get('y_pct', 0))
    try:
        out = subprocess.check_output(["adb", "-s", dev_id, "shell", "wm size"], timeout=5).decode("utf-8")
        size = out.split(":")[-1].strip().split("x")
        w, h = int(size[0]), int(size[1])
        tx, ty = int(w * x_pct), int(h * y_pct)
        subprocess.Popen(["adb", "-s", dev_id, "shell", "input", "tap", str(tx), str(ty)])
    except: pass
    return "OK"

@app.route('/swipe/<dev_id>')
def swipe(dev_id):
    x1_pct = float(request.args.get('x1_pct', 0))
    y1_pct = float(request.args.get('y1_pct', 0))
    x2_pct = float(request.args.get('x2_pct', 0))
    y2_pct = float(request.args.get('y2_pct', 0))
    try:
        out = subprocess.check_output(["adb", "-s", dev_id, "shell", "wm size"], timeout=5).decode("utf-8")
        size = out.split(":")[-1].strip().split("x")
        w, h = int(size[0]), int(size[1])
        tx1, ty1 = int(w * x1_pct), int(h * y1_pct)
        tx2, ty2 = int(w * x2_pct), int(h * y2_pct)
        subprocess.Popen(["adb", "-s", dev_id, "shell", "input", "swipe", str(tx1), str(ty1), str(tx2), str(ty2), "300"])
    except: pass
    return "OK"

@app.route('/key/<dev_id>')
def key(dev_id):
    code = request.args.get('code')
    try:
        subprocess.Popen(["adb", "-s", dev_id, "shell", "input", "keyevent", str(code)])
    except Exception as e:
        print(f"Key error: {e}", flush=True)
    return "OK"

@app.route('/unlock/<dev_id>')
def unlock(dev_id):
    subprocess.Popen(["adb", "-s", dev_id, "shell", "input", "keyevent", "224"])
    subprocess.Popen(["adb", "-s", dev_id, "shell", "wm", "dismiss-keyguard"])
    subprocess.Popen(["adb", "-s", dev_id, "shell", "input", "swipe", "500", "1500", "500", "200", "300"])
    return "OK"

@app.route('/sleep/<dev_id>')
def sleep(dev_id):
    subprocess.Popen(["adb", "-s", dev_id, "shell", "input", "keyevent", "223"])
    return "OK"

@app.route('/reboot/<dev_id>')
def reboot(dev_id):
    subprocess.Popen(["adb", "-s", dev_id, "reboot"])
    return "OK"

@app.route('/set_theme_all/<mode>')
def set_theme_all(mode):
    try:
        res = subprocess.check_output(["adb", "devices"]).decode()
        devices = []
        for line in res.strip().split("\n")[1:]:
            line = line.strip()
            if line and not line.startswith("*"):
                parts = line.split()
                if parts and parts[1] == "device":
                    devices.append(parts[0])
        
        night_val = "yes" if mode == "dark" else "no"
        for dev_id in devices:
            subprocess.Popen(["adb", "-s", dev_id, "shell", "cmd", "uimode", "night", night_val])
    except Exception as e:
        return str(e), 500
    return "OK"

def gen_frames(dev_id):
    empty_count = 0
    try:
        while True:
            try:
                cmd = ["adb", "-s", dev_id, "exec-out", "screencap", "-p"]
                frame = subprocess.check_output(cmd, timeout=5)
                idx = frame.find(b"\x89PNG")
                if idx != -1:
                    empty_count = 0
                    frame = frame[idx:]
                    yield (b'--frame\r\n'
                           b'Content-Type: image/png\r\n\r\n' + frame + b'\r\n')
                else:
                    empty_count += 1
                    # If screencap produces no image for 3+ consecutive attempts (locked/bouncer or rebooting)
                    if empty_count % 10 == 0:
                        # Auto-trigger keyguard dismiss in background to wake screen from bouncer state
                        subprocess.Popen(["adb", "-s", dev_id, "shell", "input keyevent 224; wm dismiss-keyguard; input swipe 500 1500 500 500 200"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(0.5)
            except subprocess.SubprocessError:
                empty_count += 1
                time.sleep(1)
            except Exception as e:
                empty_count += 1
                time.sleep(1)
            else:
                time.sleep(REFRESH_INTERVAL)
    except GeneratorExit:
        # 클라이언트가 연결을 끊은 경우
        pass

@app.route('/stream/<dev_id>')
def stream(dev_id):
    return Response(gen_frames(dev_id),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=PORT, threaded=True)
