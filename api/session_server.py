#!/usr/bin/env python3
# ==============================================================================
#  N-Shop Automation Master Device Profile & Session Affinity REST API Server
# ==============================================================================
#  Port: 5050 (default)
#  Primary Storage: MariaDB (nshop_api_v1 / nshop:Tech1324!)
#  Fallback Storage: SQLite (/home/tech/nshop_macro_v1/api/profiles.db)
# ==============================================================================

import os
import sys
import json
import time
import sqlite3
import subprocess
import pymysql
from pymysql.cursors import DictCursor
from flask import Flask, request, jsonify

app = Flask(__name__)

MARIADB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "nshop",
    "password": "Tech1324",
    "database": "nshop_api_v1",
    "charset": "utf8mb4",
    "autocommit": True
}
SQLITE_DB_PATH = "/home/tech/nshop_macro_v1/api/profiles.db"

def get_mariadb_conn():
    try:
        return pymysql.connect(**MARIADB_CONFIG, cursorclass=DictCursor)
    except Exception as e:
        print(f"[!] MariaDB connection failed: {e}. Using SQLite fallback.")
        return None

def init_db():
    # 1. MariaDB Table Init
    conn = get_mariadb_conn()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS device_profiles (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        device_id VARCHAR(64) NOT NULL COMMENT '단말기 고유 ID',
                        ssaid VARCHAR(64) NOT NULL COMMENT '안드로이드 ID',
                        adid VARCHAR(64) DEFAULT '' COMMENT '구글 광고 ID',
                        ip_address VARCHAR(45) DEFAULT '' COMMENT '할당 공인 IP',
                        nac_token TEXT COMMENT 'NAC 토큰',
                        cookies_json LONGTEXT COMMENT '세션 쿠키 JSON',
                        ntracker_json TEXT COMMENT 'NTracker 보안키 JSON',
                        shared_prefs_json TEXT COMMENT '추가 환경설정 JSON',
                        usage_count INT DEFAULT 1 COMMENT '사용 횟수',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        UNIQUE KEY uk_device_ssaid (device_id, ssaid),
                        INDEX idx_device_id (device_id),
                        INDEX idx_ssaid (ssaid),
                        INDEX idx_ip_address (ip_address)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                """)
            conn.close()
            print("[✓] MariaDB device_profiles table verified.")
        except Exception as ex:
            print(f"[!] MariaDB init warning: {ex}")

    # 2. SQLite Fallback Table Init
    os.makedirs(os.path.dirname(SQLITE_DB_PATH), exist_ok=True)
    s_conn = sqlite3.connect(SQLITE_DB_PATH)
    s_cur = s_conn.cursor()
    s_cur.execute("""
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
    s_conn.commit()
    s_conn.close()

init_db()

# ------------------------------------------------------------------------------
# Health Check Endpoint
# ------------------------------------------------------------------------------
@app.route('/api/v1/health', methods=['GET'])
def health_check():
    m_conn = get_mariadb_conn()
    count = 0
    db_type = "MariaDB (nshop_api_v1)"
    if m_conn:
        with m_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM device_profiles;")
            count = cur.fetchone()['cnt']
        m_conn.close()
    else:
        db_type = f"SQLite Fallback ({SQLITE_DB_PATH})"
        s_conn = sqlite3.connect(SQLITE_DB_PATH)
        s_cur = s_conn.cursor()
        s_cur.execute("SELECT COUNT(*) FROM device_profiles;")
        count = s_cur.fetchone()[0]
        s_conn.close()

    return jsonify({
        "status": "online",
        "service": "N-Shop Device Profile & Session API",
        "registered_profiles": count,
        "database": db_type,
        "timestamp": time.time()
    })

# ------------------------------------------------------------------------------
# List All Profiles (Filtered by device_id if provided)
# ------------------------------------------------------------------------------
@app.route('/api/v1/profiles', methods=['GET'])
def list_profiles():
    device_id = request.args.get('device_id', '').strip()
    m_conn = get_mariadb_conn()
    rows = []
    
    if m_conn:
        with m_conn.cursor() as cur:
            if device_id:
                cur.execute("SELECT device_id, ssaid, adid, ip_address, usage_count, updated_at FROM device_profiles WHERE device_id = %s ORDER BY updated_at DESC;", (device_id,))
            else:
                cur.execute("SELECT device_id, ssaid, adid, ip_address, usage_count, updated_at FROM device_profiles ORDER BY updated_at DESC;")
            rows = cur.fetchall()
            for r in rows:
                if 'updated_at' in r and r['updated_at']:
                    r['updated_at'] = str(r['updated_at'])
        m_conn.close()
    else:
        s_conn = sqlite3.connect(SQLITE_DB_PATH)
        s_conn.row_factory = sqlite3.Row
        s_cur = s_conn.cursor()
        if device_id:
            s_cur.execute("SELECT device_id, android_id AS ssaid, gaid AS adid, ip_address, usage_count, updated_at FROM device_profiles WHERE device_id = ? ORDER BY updated_at DESC;", (device_id,))
        else:
            s_cur.execute("SELECT device_id, android_id AS ssaid, gaid AS adid, ip_address, usage_count, updated_at FROM device_profiles ORDER BY updated_at DESC;")
        rows = [dict(r) for r in s_cur.fetchall()]
        s_conn.close()

    return jsonify({
        "total": len(rows),
        "device_id": device_id if device_id else "ALL",
        "profiles": rows
    })

# ------------------------------------------------------------------------------
# Match Profile by Device ID & SSAID / IP
# ------------------------------------------------------------------------------
@app.route('/api/v1/profiles/match', methods=['GET'])
def match_profile():
    device_id = request.args.get('device_id', '').strip()
    ssaid = request.args.get('ssaid', '').strip()
    ip = request.args.get('ip', '').strip()

    if not device_id and not ssaid and not ip:
        return jsonify({"error": "Query parameter 'device_id', 'ssaid', or 'ip' required"}), 400

    m_conn = get_mariadb_conn()
    row = None
    if m_conn:
        with m_conn.cursor() as cur:
            if device_id and ssaid:
                cur.execute("SELECT * FROM device_profiles WHERE device_id = %s AND ssaid = %s;", (device_id, ssaid))
            elif ssaid:
                cur.execute("SELECT * FROM device_profiles WHERE ssaid = %s;", (ssaid,))
            elif device_id:
                cur.execute("SELECT * FROM device_profiles WHERE device_id = %s ORDER BY updated_at DESC LIMIT 1;", (device_id,))
            else:
                cur.execute("SELECT * FROM device_profiles WHERE ip_address = %s;", (ip,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE device_profiles SET usage_count = usage_count + 1 WHERE id = %s;", (row['id'],))
        m_conn.close()

        if row:
            return jsonify({
                "found": True,
                "profile": {
                    "device_id": row["device_id"],
                    "ssaid": row["ssaid"],
                    "adid": row["adid"],
                    "ip_address": row["ip_address"],
                    "nac_token": row["nac_token"],
                    "cookies": json.loads(row["cookies_json"]) if row["cookies_json"] else {},
                    "ntracker_keys": json.loads(row["ntracker_json"]) if row["ntracker_json"] else {},
                    "usage_count": row["usage_count"] + 1,
                    "updated_at": str(row["updated_at"])
                }
            })
            
    # SQLite Fallback
    s_conn = sqlite3.connect(SQLITE_DB_PATH)
    s_conn.row_factory = sqlite3.Row
    s_cur = s_conn.cursor()
    if ssaid:
        s_cur.execute("SELECT * FROM device_profiles WHERE android_id = ?;", (ssaid,))
    elif device_id:
        s_cur.execute("SELECT * FROM device_profiles WHERE device_id = ? ORDER BY updated_at DESC LIMIT 1;", (device_id,))
    else:
        s_cur.execute("SELECT * FROM device_profiles WHERE ip_address = ?;", (ip,))
    s_row = s_cur.fetchone()
    s_conn.close()

    if not s_row:
        return jsonify({"found": False, "message": f"No profile matching query (device_id={device_id}, ssaid={ssaid})"}), 404

    s_data = dict(s_row)
    return jsonify({
        "found": True,
        "profile": {
            "device_id": s_data["device_id"],
            "ssaid": s_data["android_id"],
            "adid": s_data["gaid"],
            "ip_address": s_data["ip_address"],
            "cookies": json.loads(s_data["cookies_json"]) if s_data["cookies_json"] else {},
            "ntracker_keys": json.loads(s_data["ntracker_json"]) if s_data["ntracker_json"] else {},
            "usage_count": s_data["usage_count"]
        }
    })

# ------------------------------------------------------------------------------
# Live ADB Extraction & Backup to MariaDB + Local JSON
# ------------------------------------------------------------------------------
@app.route('/api/v1/profiles/backup', methods=['POST'])
def backup_live_session():
    payload = request.get_json(force=True, silent=True) or {}
    device_id = payload.get('device_id', 'R5CT20Y2XYE')
    target_ip = payload.get('ip_address', '211.234.12.34')
    pkg = "com.nhn.android.search"

    # 1. Fetch Android ID (SSAID)
    cmd_ssaid = f"adb -s {device_id} shell \"su -c 'settings get secure android_id'\""
    android_id = subprocess.run(cmd_ssaid, shell=True, capture_output=True, text=True).stdout.strip()
    
    # 2. Fetch ADID (GAID)
    cmd_adid = f"adb -s {device_id} shell \"su -c 'cat /data/data/{pkg}/shared_prefs/com.google.android.gms.appid.xml'\""
    adid_xml = subprocess.run(cmd_adid, shell=True, capture_output=True, text=True).stdout
    adid = ""
    if "adid_key" in adid_xml:
        import re
        m_adid = re.search(r'name="adid_key">([^<]+)<', adid_xml)
        if m_adid: adid = m_adid.group(1)

    # 3. Fetch NAC Token
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

    now = time.time()
    cookies_str = json.dumps(cookies, ensure_ascii=False)
    ntracker_str = json.dumps(ntracker_keys, ensure_ascii=False)

    # Save to MariaDB
    m_conn = get_mariadb_conn()
    if m_conn:
        try:
            with m_conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO device_profiles (device_id, ssaid, adid, ip_address, nac_token, cookies_json, ntracker_json, shared_prefs_json, usage_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, '{}', 1)
                    ON DUPLICATE KEY UPDATE
                        adid = VALUES(adid),
                        ip_address = VALUES(ip_address),
                        nac_token = VALUES(nac_token),
                        cookies_json = VALUES(cookies_json),
                        ntracker_json = VALUES(ntracker_json),
                        usage_count = usage_count + 1;
                """, (device_id, android_id, adid, target_ip, nac_token, cookies_str, ntracker_str))
            m_conn.close()
            print(f"[✓] MariaDB Saved profile: device_id={device_id}, ssaid={android_id}")
        except Exception as ex:
            print(f"[!] MariaDB insert error: {ex}")

    # Fallback/Dual Save to local JSON (/home/tech/nshop_macro_v1/profiles/<SSAID>.json)
    profiles_dir = "/home/tech/nshop_macro_v1/profiles"
    os.makedirs(profiles_dir, exist_ok=True)
    profile_key = android_id if android_id else target_ip.replace('.', '_')
    json_path = os.path.join(profiles_dir, f"{profile_key}.json")
    
    profile_dump = {
        "device_id": device_id,
        "ssaid": android_id,
        "adid": adid,
        "ip_address": target_ip,
        "nac_token": nac_token,
        "cookies": cookies,
        "ntracker_keys": ntracker_keys,
        "updated_at": now
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(profile_dump, f, indent=2, ensure_ascii=False)

    return jsonify({
        "status": "success",
        "device_id": device_id,
        "ssaid": android_id,
        "adid": adid,
        "ip_address": target_ip,
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
    device_id = payload.get('device_id', 'R5CT20Y2XYE')
    ssaid = payload.get('ssaid', '')
    target_ip = payload.get('ip_address', '')
    profile_data = payload.get('profile', None)

    profiles_dir = "/home/tech/nshop_macro_v1/profiles"
    
    # 1. Primary Lookup from MariaDB
    if not profile_data:
        m_conn = get_mariadb_conn()
        if m_conn:
            with m_conn.cursor() as cur:
                if device_id and ssaid:
                    cur.execute("SELECT * FROM device_profiles WHERE device_id = %s AND ssaid = %s;", (device_id, ssaid))
                elif ssaid:
                    cur.execute("SELECT * FROM device_profiles WHERE ssaid = %s;", (ssaid,))
                elif device_id:
                    cur.execute("SELECT * FROM device_profiles WHERE device_id = %s ORDER BY updated_at DESC LIMIT 1;", (device_id,))
                row = cur.fetchone()
                if row:
                    profile_data = {
                        "device_id": row["device_id"],
                        "ssaid": row["ssaid"],
                        "adid": row["adid"],
                        "nac_token": row["nac_token"],
                        "cookies": json.loads(row["cookies_json"]) if row["cookies_json"] else {},
                        "ntracker_keys": json.loads(row["ntracker_json"]) if row["ntracker_json"] else {}
                    }
            m_conn.close()

    # 2. Local File Fallback
    if not profile_data:
        if ssaid and os.path.exists(os.path.join(profiles_dir, f"{ssaid}.json")):
            with open(os.path.join(profiles_dir, f"{ssaid}.json"), "r", encoding="utf-8") as f:
                profile_data = json.load(f)

    if not profile_data:
        return jsonify({"error": f"No profile found for device_id='{device_id}', ssaid='{ssaid}'"}), 404

    pkg = "com.nhn.android.search"
    t0 = time.time()

    # 1. Inject Android ID (SSAID)
    android_id = profile_data.get('ssaid', '')
    if android_id:
        subprocess.run(f"adb -s {device_id} shell 'settings put secure android_id {android_id}'", shell=True, capture_output=True)

    # 2. Inject NAC Token if present
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

    # 3. Inject NTracker Keys
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
        if os.path.exists(tmp_xml): os.remove(tmp_xml)

    # 4. Inject Cookies into XWhale Cookies SQLite DB
    cookies = profile_data.get('cookies', {})
    if cookies:
        tmp_db = f"/tmp/restore_cookies_{device_id}.db"
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
        "message": "Device profile & session identity injected successfully from MariaDB"
    })

if __name__ == '__main__':
    print("==========================================================================")
    print(" Starting N-Shop Device Profile & Session Affinity REST API Server")
    print(" Listening on: http://0.0.0.0:5050")
    print(" Primary DB  : MariaDB (nshop_api_v1)")
    print(" Fallback DB : SQLite (" + SQLITE_DB_PATH + ")")
    print("==========================================================================")
    app.run(host='0.0.0.0', port=5050, debug=False)
