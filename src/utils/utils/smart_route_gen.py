import requests
import hmac
import hashlib
import base64
import time
import urllib.parse
import random
import math
import json
import os
import sys

# [STABLE ORIGINAL v1.2 logic]
class NaverCrypto:
    @staticmethod
    def generate_drive_hmac(url, timestamp_ms=None):
        KEY_DRIVE_ENCRYPT = b"fvOvQAZ5fvDMvQqiQ6KTZYpPkGhr0oQp653TDil12acO5wnhvIQhl5veOvjoku0H"
        msgpad = str(timestamp_ms if timestamp_ms else int(time.time() * 1000))
        payload = (url[:255] + msgpad).encode('utf-8')
        h = hmac.new(KEY_DRIVE_ENCRYPT, payload, hashlib.sha1).digest()
        md = "v0:" + base64.b64encode(h).decode('utf-8')
        return msgpad, md

class RouteDecoder:
    @staticmethod
    def calculate_distance(coords):
        if not coords or len(coords) < 2: return 0.0
        total = 0.0
        for i in range(len(coords) - 1):
            lat1, lon1 = coords[i]; lat2, lon2 = coords[i+1]
            R = 6371.0
            dlat = math.radians(lat2 - lat1); dlon = math.radians(lon2 - lon1)
            a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            total += R * c
        return total

    @staticmethod
    def decode_json_path(coords_array):
        if not coords_array or len(coords_array) < 2: return []
        pts = []
        curr_x, curr_y = coords_array[0], coords_array[1]
        pts.append([float(curr_y) / 10000000.0, float(curr_x) / 10000000.0])
        for i in range(2, len(coords_array), 2):
            if i + 1 < len(coords_array):
                curr_x += coords_array[i]; curr_y += coords_array[i+1]
                pts.append([float(curr_y) / 10000000.0, float(curr_x) / 10000000.0])
        return pts

    @staticmethod
    def decode_pbf_path(resp_content: bytes):
        import gzip
        try:
            if resp_content[:2] == b'\x1f\x8b': resp_content = gzip.decompress(resp_content)
        except Exception: pass
        def decode_zigzag(n): return (n >> 1) ^ (-(n & 1))
        for i in range(len(resp_content) - 4):
            if resp_content[i] == 0x0a:
                try:
                    idx = i + 1; length = 0; shift = 0
                    while True:
                        b = resp_content[idx]; idx += 1
                        length |= (b & 0x7f) << shift
                        shift += 7
                        if not (b & 0x80): break
                    if 10 < length < 1000000 and idx + length <= len(resp_content):
                        arr = resp_content[idx:idx+length]; idx2 = 0; coords = []
                        while idx2 < len(arr):
                            val = 0; s2 = 0
                            while True:
                                b = arr[idx2]; idx2 += 1
                                val |= (b & 0x7f) << s2
                                s2 += 7
                                if not (b & 0x80): break
                            coords.append(decode_zigzag(val))
                        if len(coords) >= 2:
                            lng, lat = coords[0], coords[1]
                            if 1200000000 < lng < 1350000000 and 300000000 < lat < 450000000:
                                return RouteDecoder.decode_json_path(coords)
                except Exception: pass
        return []

def get_route_config():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(os.path.dirname(script_dir), "api", "route_config.json")
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"random_radius_km": 10.0, "saved_destinations": []}

def get_random_point(lat, lng, min_radius_km, max_radius_km):
    random.seed(time.time_ns())
    r_min = min_radius_km / 111.0
    r_max = max_radius_km / 111.0
    
    # Uniform disk distribution in the annulus (donut)
    u = random.random()
    v = random.random()
    
    w = math.sqrt(u * (r_max**2 - r_min**2) + r_min**2)
    t = 2 * math.pi * v
    return lat + w * math.sin(t), lng + (w * math.cos(t)) / math.cos(math.radians(lat))

def append_destination_wandering(route_pts, radius_m=20, points=12):
    """
    Appends a circular wandering pattern at the end of the route 
    to simulate lingering/searching for parking at the destination.
    """
    if not route_pts:
        return route_pts
        
    last_lat, last_lng = route_pts[-1]
    radius_deg = radius_m / 111000.0
    
    wandering_pts = []
    # Create a small circular/looping wandering path (뱅글뱅글)
    for i in range(points):
        angle = (i / float(points)) * 2 * math.pi
        w_lat = last_lat + (radius_deg * math.sin(angle))
        w_lng = last_lng + (radius_deg * math.cos(angle)) / math.cos(math.radians(last_lat))
        wandering_pts.append([w_lat, w_lng])
        
    # Finally, slowly return to the exact center
    wandering_pts.append([last_lat, last_lng])
    
    return route_pts + wandering_pts

def generate_routes(target_id=None, filename=None):
    config = get_route_config()
    saved = config.get("saved_destinations", [])
    selected_dest = None
    for d in saved:
        if d["id"] == str(target_id): selected_dest = d; break
    if not selected_dest: return

    LIB_DIR = "/tmp/route_library"
    os.makedirs(LIB_DIR, exist_ok=True)
    if not filename: filename = "Target_Route_01.json"
    
    # Radius range requested: 3km to 15km
    min_radius = 3.0
    max_radius = 15.0
    
    best_route_pts = None
    best_dist = float('inf')
    
    for attempt in range(1, 4):
        start_lat, start_lng = get_random_point(selected_dest["lat"], selected_dest["lng"], min_radius, max_radius)
        params = {
            "mainoption": "traoptimal:tracomfort:traoptimal,avoidtoll:traoptdist:traoptimal,multiroute",
            "rptype": "4", "routesession": "1",
            "start": f"{start_lng},{start_lat}",
            "goal": f"{selected_dest['lng']},{selected_dest['lat']}",
            "startexcludefilter": "24", "goalexcludefilter": "0", "autochange": "1", "laneall": "1", "etatype": "0",
            "uuid": "85441208bbd688a8ca5a1bc0d2d230d",
            "caller": "mapmobileapps_Android_35_app6.4.0.7_fw2.12.6",
            "lang": "ko", "mileage": "11.9", "fueltype": "1", "cartype": "1",
            "vehicletype": "car", "crs": "EPSG:4326", "output": "pbf", "respversion": "9"
        }
        full_url = f"https://drive.io.naver.com/v3/global/driving?{urllib.parse.urlencode(params)}"
        msgpad, md = NaverCrypto.generate_drive_hmac(full_url)
        headers = {
            "device-id": "85441208bbd688a8ca5a1bc0d2d230d",
            "x-consumer-id": "mapmobileapps.mapmobileapps",
            "x-hmac-msgpad": msgpad, "x-hmac-md": md,
            "user-agent": "ktor-client", "referer": "client://NaverMap"
        }
        try:
            resp = requests.get(full_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                route_pts = RouteDecoder.decode_pbf_path(resp.content)
                if route_pts:
                    # [OPTIONAL] 주차장 찾기/목적지 배회 뱅글뱅글 기능 (약 30m 반경)
                    route_pts = append_destination_wandering(route_pts, radius_m=15, points=10)
                    
                    dist = RouteDecoder.calculate_distance(route_pts)
                    
                    if dist <= 25.0:
                        # Found a satisfying route
                        best_route_pts = route_pts
                        best_dist = dist
                        break
                    else:
                        # Keep track of the shortest route in case all 3 exceed 25km
                        if dist < best_dist:
                            best_route_pts = route_pts
                            best_dist = dist
        except Exception: pass
        time.sleep(0.5)
        
    if best_route_pts is not None:
        full_path = os.path.join(LIB_DIR, filename)
        with open(full_path, "w") as f: json.dump(best_route_pts, f)
        # [IMPORTANT OUTPUTS]
        print(f"ROUTE_FILE: {full_path}")
        print(f"TOTAL_DISTANCE: {best_dist:.2f}")
        print(f" [✓] Created: {filename}")

if __name__ == "__main__":
    generate_routes(sys.argv[1] if len(sys.argv) > 1 else None, sys.argv[2] if len(sys.argv) > 2 else None)
