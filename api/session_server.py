#!/usr/bin/env python3
# ==============================================================================
#  N-Shop Automation Master Device Profile & Session Affinity REST API Server
# ==============================================================================
#  Port: 5000 (default)
#  Storage: SQLite DB (/home/tech/nshop_macro_v1/api/profiles.db)
# ==============================================================================

import os
import sys
import json
import time
import sqlite3
import subprocess
from flask import Flask, request, jsonify

app = Flask(__name__)
DB_PATH = "/home/tech/nshop_macro_v1/api/profiles.db"

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS device_profiles (
            ip_address TEXT PRIMARY KEY,
            device_id TEXT,
            android_id TEXT,
            gaid TEXT,
            user_agent TEXT,
            cookies_json TEXT,
            ntracker_json TEXT,
            shared_prefs_json TEXT,
            created_at REAL,
            updated_at REAL,
            usage_count INTEGER DEFAULT 1
        );
    """)
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ------------------------------------------------------------------------------
# Health Check Endpoint
# ------------------------------------------------------------------------------
@app.route('/api/v1/health', methods=['GET'])
def health_check():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM device_profiles;")
    count = cursor.fetchone()[0]
    conn.close()
    return jsonify({
        "status": "online",
        "service": "N-Shop Device Profile & Session API",
        "registered_profiles": count,
        "db_path": DB_PATH,
        "timestamp": time.time()
    })

# ------------------------------------------------------------------------------
# List All Profiles
# ------------------------------------------------------------------------------
@app.route('/api/v1/profiles', methods=['GET'])
def list_profiles():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT ip_address, device_id, android_id, usage_count, updated_at FROM device_profiles ORDER BY updated_at DESC;")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify({
        "total": len(rows),
        "profiles": rows
    })

# ------------------------------------------------------------------------------
# Match Profile by IP or Device ID
# ------------------------------------------------------------------------------
@app.route('/api/v1/profiles/match', methods=['GET'])
def match_profile():
    ip = request.args.get('ip', '').strip()
    device_id = request.args.get('device_id', '').strip()

    if not ip and not device_id:
        return jsonify({"error": "Query parameter 'ip' or 'device_id' required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    if ip:
        cursor.execute("SELECT * FROM device_profiles WHERE ip_address = ?;", (ip,))
    else:
        cursor.execute("SELECT * FROM device_profiles WHERE device_id = ? ORDER BY updated_at DESC LIMIT 1;", (device_id,))
    
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"found": False, "message": f"No profile matching query (ip={ip}, device_id={device_id})"}), 404

    data = dict(row)
    # Increment usage count
    cursor.execute("UPDATE device_profiles SET usage_count = usage_count + 1, updated_at = ? WHERE ip_address = ?;", (time.time(), data['ip_address']))
    conn.commit()
    conn.close()

    return jsonify({
        "found": True,
        "profile": {
            "ip_address": data["ip_address"],
            "device_id": data["device_id"],
            "android_id": data["android_id"],
            "gaid": data["gaid"],
            "user_agent": data["user_agent"],
            "cookies": json.loads(data["cookies_json"]) if data["cookies_json"] else {},
            "ntracker_keys": json.loads(data["ntracker_json"]) if data["ntracker_json"] else {},
            "shared_prefs": json.loads(data["shared_prefs_json"]) if data["shared_prefs_json"] else {},
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
            "usage_count": data["usage_count"] + 1
        }
    })

# ------------------------------------------------------------------------------
# Register or Update Profile Payload
# ------------------------------------------------------------------------------
@app.route('/api/v1/profiles/register', methods=['POST'])
def register_profile():
    payload = request.get_json(force=True, silent=True)
    if not payload or 'ip_address' not in payload:
        return jsonify({"error": "Invalid payload. 'ip_address' is required"}), 400

    ip = payload['ip_address'].strip()
    device_id = payload.get('device_id', 'R3CRC0K2K7D')
    android_id = payload.get('android_id', '')
    gaid = payload.get('gaid', '')
    ua = payload.get('user_agent', '')
    cookies_json = json.dumps(payload.get('cookies', {}))
    ntracker_json = json.dumps(payload.get('ntracker_keys', {}))
    shared_prefs_json = json.dumps(payload.get('shared_prefs', {}))
    now = time.time()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO device_profiles (ip_address, device_id, android_id, gaid, user_agent, cookies_json, ntracker_json, shared_prefs_json, created_at, updated_at, usage_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(ip_address) DO UPDATE SET
            device_id = excluded.device_id,
            android_id = excluded.android_id,
            gaid = excluded.gaid,
            user_agent = excluded.user_agent,
            cookies_json = excluded.cookies_json,
            ntracker_json = excluded.ntracker_json,
            shared_prefs_json = excluded.shared_prefs_json,
            updated_at = excluded.updated_at;
    """, (ip, device_id, android_id, gaid, ua, cookies_json, ntracker_json, shared_prefs_json, now, now))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "ip_address": ip, "message": "Profile registered/updated successfully"})

# ------------------------------------------------------------------------------
# Live ADB Backup: Extract current session identity from connected device
# ------------------------------------------------------------------------------
@app.route('/api/v1/profiles/backup', methods=['POST'])
def backup_live_session():
    payload = request.get_json(force=True, silent=True) or {}
    device_id = payload.get('device_id', 'R3CRC0K2K7D')
    target_ip = payload.get('ip_address', '127.0.0.1')

    pkg = "com.nhn.android.search"
    
    # 1. Fetch Android ID (SSAID)
    cmd_aid = f"adb -s {device_id} shell 'settings get secure android_id'"
    android_id = subprocess.run(cmd_aid, shell=True, capture_output=True, text=True).stdout.strip()

    # 2. Fetch ADID (GAID)
    cmd_adid = f"adb -s {device_id} shell \"su -c 'cat /data/data/com.google.android.gms/shared_prefs/adid_settings.xml'\""
    adid_xml = subprocess.run(cmd_adid, shell=True, capture_output=True, text=True).stdout
    adid = ""
    if "adid_key" in adid_xml:
        import re
        m_adid = re.search(r'name="adid_key">([^<]+)<', adid_xml)
        if m_adid: adid = m_adid.group(1)

    # 3. Fetch NAC Token from com.naver.gfpsdk.nac.xml
    cmd_nac = f"adb -s {device_id} shell \"su -c 'cat /data/data/{pkg}/shared_prefs/com.naver.gfpsdk.nac.xml'\""
    nac_xml = subprocess.run(cmd_nac, shell=True, capture_output=True, text=True).stdout
    nac_token = ""
    if "nac" in nac_xml:
        import re
        m_nac = re.search(r'name="nac">([^<]+)<', nac_xml)
        if m_nac: nac_token = m_nac.group(1)

    # 4. Extract NTracker Keys
    cmd_ntracker = f"adb -s {device_id} shell \"su -c 'cat /data/data/{pkg}/shared_prefs/NTracker_SharedPreference.xml'\""
    ntracker_xml = subprocess.run(cmd_ntracker, shell=True, capture_output=True, text=True).stdout
    
    ntracker_keys = {}
    if "|S||P|" in ntracker_xml:
        import re
        m_pub = re.search(r'name="\|S\|\|P\|">([^<]+)<', ntracker_xml)
        m_priv = re.search(r'name="\|S\|\|K\|">([^<]+)<', ntracker_xml)
        m_cre = re.search(r'name="\|S\|cre">([^<]+)<', ntracker_xml)
        if m_pub: ntracker_keys["public_key"] = m_pub.group(1)
        if m_priv: ntracker_keys["private_key"] = m_priv.group(1)
        if m_cre: ntracker_keys["created_at"] = m_cre.group(1)

    # 5. Extract XWhale Browser Cookies DB
    cookies = {}
    tmp_db = f"/tmp/Cookies_{device_id}.db"
    cmd_cp = f"adb -s {device_id} shell \"su -c 'cp /data/data/{pkg}/app_xwhale/Default/Cookies /sdcard/Cookies.db'\""
    subprocess.run(cmd_cp, shell=True, capture_output=True)
    subprocess.run(f"adb -s {device_id} pull /sdcard/Cookies.db {tmp_db}", shell=True, capture_output=True)
    
    if os.path.exists(tmp_db):
        try:
            c = sqlite3.connect(tmp_db)
            cur = c.cursor()
            cur.execute("SELECT name, value FROM cookies;")
            for r in cur.fetchall():
                cookies[r[0]] = r[1]
            c.close()
            os.remove(tmp_db)
        except Exception:
            pass

    # Save to SQLite DB
    now = time.time()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO device_profiles (ip_address, device_id, android_id, gaid, user_agent, cookies_json, ntracker_json, shared_prefs_json, created_at, updated_at, usage_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(ip_address) DO UPDATE SET
            device_id = excluded.device_id,
            android_id = excluded.android_id,
            gaid = excluded.gaid,
            cookies_json = excluded.cookies_json,
            ntracker_json = excluded.ntracker_json,
            updated_at = excluded.updated_at;
    """, (target_ip, device_id, android_id, adid, "", json.dumps(cookies), json.dumps(ntracker_keys), "{}", now, now))
    conn.commit()
    conn.close()

    # Save rich profile JSON named after SSAID in /home/tech/nshop_macro_v1/profiles/<SSAID>.json
    profiles_dir = "/home/tech/nshop_macro_v1/profiles"
    os.makedirs(profiles_dir, exist_ok=True)
    profile_key = android_id if android_id else target_ip.replace('.', '_')
    json_path = os.path.join(profiles_dir, f"{profile_key}.json")
    # Extract mac_address or adid if present in cookies or payload
    device_model = payload.get('model', 'Galaxy S21')
    mac_addr = payload.get('mac_address', '')
    user_agent = payload.get('user_agent', '')
    
    profile_dump = {
        "ssaid": android_id,
        "adid": adid,
        "mac_address": mac_addr,
        "device_model": device_model,
        "user_agent": user_agent,
        "nac_token": nac_token,
        "ip_address": target_ip,
        "device_id": device_id,
        "cookies": cookies,
        "ntracker_keys": ntracker_keys,
        "updated_at": now
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(profile_dump, f, indent=2, ensure_ascii=False)

    return jsonify({
        "status": "success",
        "ssaid": android_id,
        "adid": adid,
        "ip_address": target_ip,
        "device_id": device_id,
        "json_path": json_path,
        "extracted_cookies": list(cookies.keys()),
        "ntracker_keys_found": bool(ntracker_keys)
    })

# ------------------------------------------------------------------------------
# Live ADB Restore: Inject profile identity directly onto connected device (<0.2s)
# ------------------------------------------------------------------------------
@app.route('/api/v1/profiles/restore', methods=['POST'])
def restore_live_session():
    payload = request.get_json(force=True, silent=True) or {}
    device_id = payload.get('device_id', 'R3CRC0K2K7D')
    target_ip = payload.get('ip_address', '')
    ssaid = payload.get('ssaid', '')
    profile_data = payload.get('profile', None)

    profiles_dir = "/home/tech/nshop_macro_v1/profiles"
    if not profile_data:
        # Check by SSAID file
        if ssaid and os.path.exists(os.path.join(profiles_dir, f"{ssaid}.json")):
            with open(os.path.join(profiles_dir, f"{ssaid}.json"), "r", encoding="utf-8") as f:
                profile_data = json.load(f)
        # Check by IP file
        elif target_ip and os.path.exists(os.path.join(profiles_dir, f"{target_ip.replace('.', '_')}.json")):
            with open(os.path.join(profiles_dir, f"{target_ip.replace('.', '_')}.json"), "r", encoding="utf-8") as f:
                profile_data = json.load(f)
        # Fallback to DB
        elif target_ip:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM device_profiles WHERE ip_address = ?;", (target_ip,))
            row = cursor.fetchone()
            conn.close()
            if row:
                profile_data = {
                    "ssaid": row["android_id"],
                    "adid": row["gaid"],
                    "cookies": json.loads(row["cookies_json"]) if row["cookies_json"] else {},
                    "ntracker_keys": json.loads(row["ntracker_json"]) if row["ntracker_json"] else {}
                }

    if not profile_data:
        return jsonify({"error": f"No profile found for ssaid='{ssaid}' or ip='{target_ip}'"}), 400

    pkg = "com.nhn.android.search"
    t0 = time.time()

    # 1. Inject Android ID (SSAID)
    android_id = profile_data.get('ssaid', profile_data.get('android_id', ''))
    if android_id:
        subprocess.run(f"adb -s {device_id} shell 'settings put secure android_id {android_id}'", shell=True, capture_output=True)

    # 3. Inject NAC Token if present
    nac_token = profile_data.get('nac_token', '')
    if nac_token:
        nac_xml = f"""<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="nac">{nac_token}</string>
</map>"""
        tmp_nac = f"/tmp/nac_{device_id}.xml"
        with open(tmp_nac, "w") as f: f.write(nac_xml)
        subprocess.run(f"adb -s {device_id} push {tmp_nac} /data/local/tmp/nac.xml", shell=True, capture_output=True)
        subprocess.run(f"adb -s {device_id} shell \"su -c 'mkdir -p /data/data/{pkg}/shared_prefs && cp /data/local/tmp/nac.xml /data/data/{pkg}/shared_prefs/com.naver.gfpsdk.nac.xml && chmod 777 /data/data/{pkg}/shared_prefs/com.naver.gfpsdk.nac.xml'\"", shell=True, capture_output=True)
        os.remove(tmp_nac)

    # 4. Inject NTracker Keys
    ntracker_keys = profile_data.get('ntracker_keys', {})
    if ntracker_keys and "public_key" in ntracker_keys:
        xml_content = f"""<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="|S|cre">{ntracker_keys.get("created_at", "1785572107810")}</string>
    <string name="|S||P|">{ntracker_keys["public_key"]}</string>
    <string name="|S||K|">{ntracker_keys.get("private_key", "")}</string>
</map>
"""
        tmp_xml = f"/tmp/NTracker_{device_id}.xml"
        with open(tmp_xml, "w") as f:
            f.write(xml_content)
        
        subprocess.run(f"adb -s {device_id} push {tmp_xml} /data/local/tmp/NTracker.xml", shell=True, capture_output=True)
        subprocess.run(f"adb -s {device_id} shell \"su -c 'mkdir -p /data/data/{pkg}/shared_prefs && cp /data/local/tmp/NTracker.xml /data/data/{pkg}/shared_prefs/NTracker_SharedPreference.xml && chmod 777 /data/data/{pkg}/shared_prefs/NTracker_SharedPreference.xml'\"", shell=True, capture_output=True)
    # 5. Inject Cookies into XWhale Cookies SQLite DB
    cookies = profile_data.get('cookies', {})
    if cookies:
        tmp_db = f"/tmp/restore_cookies_{device_id}.db"
        # Pull current DB if exists or create clean table
        subprocess.run(f"adb -s {device_id} shell \"su -c 'mkdir -p /data/data/{pkg}/app_xwhale/Default'\"", shell=True, capture_output=True)
        conn_c = sqlite3.connect(tmp_db)
        cur_c = conn_c.cursor()
        cur_c.execute("CREATE TABLE IF NOT EXISTS cookies (creation_utc INTEGER NOT NULL, host_key TEXT NOT NULL, top_frame_site_key TEXT NOT NULL, name TEXT NOT NULL, value TEXT NOT NULL, encrypted_value BLOB NOT NULL, path TEXT NOT NULL, expires_utc INTEGER NOT NULL, is_secure INTEGER NOT NULL, is_httponly INTEGER NOT NULL, last_access_utc INTEGER NOT NULL, has_expires INTEGER NOT NULL, is_persistent INTEGER NOT NULL, priority INTEGER NOT NULL, samesite INTEGER NOT NULL, source_scheme INTEGER NOT NULL, source_port INTEGER NOT NULL, is_same_party INTEGER NOT NULL, last_update_utc INTEGER NOT NULL);")
        cur_c.execute("DELETE FROM cookies;")
        now_micro = int(time.time() * 1000000)
        for k, v in cookies.items():
            cur_c.execute("""
                INSERT INTO cookies (creation_utc, host_key, top_frame_site_key, name, value, encrypted_value, path, expires_utc, is_secure, is_httponly, last_access_utc, has_expires, is_persistent, priority, samesite, source_scheme, source_port, is_same_party, last_update_utc)
                VALUES (?, '.naver.com', '', ?, ?, X'', '/', ?, 1, 0, ?, 1, 1, 1, -1, 2, 443, 0, ?);
            """, (now_micro, k, v, now_micro + 31536000000000, now_micro, now_micro))
        conn_c.commit()
        conn_c.close()
        subprocess.run(f"adb -s {device_id} push {tmp_db} /data/local/tmp/Cookies.db", shell=True, capture_output=True)
        subprocess.run(f"adb -s {device_id} shell \"su -c 'cp /data/local/tmp/Cookies.db /data/data/{pkg}/app_xwhale/Default/Cookies && chmod 777 /data/data/{pkg}/app_xwhale/Default/Cookies'\"", shell=True, capture_output=True)
        if os.path.exists(tmp_db): os.remove(tmp_db)

    t_elapsed = time.time() - t0

    return jsonify({
        "status": "success",
        "device_id": device_id,
        "restored_android_id": android_id,
        "elapsed_seconds": round(t_elapsed, 3),
        "message": "Device profile & session identity injected successfully"
    })

if __name__ == '__main__':
    print("==========================================================================")
    print(" Starting N-Shop Device Profile & Session Affinity REST API Server")
    print(" Listening on: http://0.0.0.0:5050")
    print(" SQLite Database: " + DB_PATH)
    print("==========================================================================")
    app.run(host='0.0.0.0', port=5050, debug=False)
