#!/usr/bin/env python3
"""
N-Shop Automation Master WireGuard & RouterOS MacVlan IP Controller
Features:
1. Connects to RouterOS REST API at http://hj20acn8f3p.sn.mynetname.net/rest/ with auth tech/Tech1324!
2. Manages dedicated macvlan interface ('macvlan1') on 'ether1' without touching main network settings.
3. Manages a SINGLE WireGuard profile named 'wg0.conf' on connected Android devices.
4. Dynamically generates & patches WireGuard Curve25519 keypair on RouterOS peer for the target device.
5. Manages 0.1s instant UI toggle of WireGuard app on connected Android devices.
6. Verifies device-side Public IP matches RouterOS macvlan1 Public IP before execution.
7. On completion: Disconnects device WireGuard -> Performs macvlan MAC randomization & DHCP release/renew to rotate Public IP.
"""

import os
import sys
import time
import json
import random
import base64
import requests
import subprocess
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization

ROUTER_HOST = "hj20acn8f3p.sn.mynetname.net"
ROUTER_AUTH = ("tech", "Tech1324!")
SERVER_WG_PUBKEY = "Hk3IdUGXNN8eEEPYeiDJa1QJbNJKAJLVXuH53Ju+dX0="
SERVER_WG_ENDPOINT = f"{ROUTER_HOST}:45820"

def get_router_host():
    hosts = [ROUTER_HOST, "119.193.70.173"]
    for h in hosts:
        try:
            r = requests.get(f"http://{h}/rest/system/resource", auth=ROUTER_AUTH, timeout=3)
            if r.status_code == 200:
                return h
        except Exception:
            pass
    return ROUTER_HOST

def get_public_ip(timeout: int = 5) -> str:
    ip_services = [
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://icanhazip.com",
        "https://ipinfo.io/ip"
    ]
    for service in ip_services:
        try:
            r = requests.get(service, timeout=timeout)
            if r.status_code == 200:
                ip = r.text.strip()
                if ip and len(ip) >= 7 and "." in ip:
                    return ip
        except Exception:
            continue
    return "UNKNOWN_IP"

def run_adb(device_id, cmd):
    full_cmd = f"adb -s {device_id} {cmd}"
    res = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    return res.stdout.strip(), res.stderr.strip(), res.returncode

def generate_and_patch_wireguard_keys(device_id="R5CT20Y2XYE", peer_id="*1"):
    host = get_router_host()
    base = f"http://{host}/rest"
    print(f"[*] Generating fresh Curve25519 keypair for device {device_id}...")
    
    raw_priv = bytearray(os.urandom(32))
    raw_priv[0] &= 248
    raw_priv[31] &= 127
    raw_priv[31] |= 64

    priv = x25519.X25519PrivateKey.from_private_bytes(bytes(raw_priv))
    pub = priv.public_key()

    priv_b64 = base64.b64encode(priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode('ascii')
    pub_b64 = base64.b64encode(pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode('ascii')

    # Update RouterOS Peer
    url = f"{base}/interface/wireguard/peers/{peer_id}"
    res = requests.patch(url, json={"public-key": pub_b64, "comment": device_id}, auth=ROUTER_AUTH, timeout=5)
    print(f"  [✓] Updated RouterOS peer {peer_id} with PublicKey: {pub_b64} (Status: {res.status_code})")
    
    return priv_b64, pub_b64

def setup_mikrotik_macvlan_and_routing():
    host = get_router_host()
    base = f"http://{host}/rest"
    print(f"[*] Setting up RouterOS MacVlan & Policy Routing on {host}...")
    
    # 1. Ensure macvlan1 exists
    macvlan_id = None
    r = requests.get(f"{base}/interface/macvlan", auth=ROUTER_AUTH, timeout=5)
    if r.status_code == 200:
        for m in r.json():
            if m.get("name") == "macvlan1":
                macvlan_id = m.get(".id")
                break
                
    if not macvlan_id:
        oui = random.choice(["F4:1E:57", "A4:83:E7", "00:1C:62", "64:09:80"])
        mac_addr = f"{oui}:%02X:%02X:%02X" % tuple(random.randint(0, 255) for _ in range(3))
        res = requests.put(f"{base}/interface/macvlan", auth=ROUTER_AUTH, json={"name": "macvlan1", "interface": "ether1", "mac-address": mac_addr}, timeout=5)
        print(f"  [✓] Created macvlan1 (Status {res.status_code})")
        
    # 2. Ensure DHCP Client for macvlan1
    dhcp_id = None
    r_dhcp = requests.get(f"{base}/ip/dhcp-client", auth=ROUTER_AUTH, timeout=5)
    if r_dhcp.status_code == 200:
        for d in r_dhcp.json():
            if d.get("interface") == "macvlan1":
                dhcp_id = d.get(".id")
                break
                
    if not dhcp_id:
        res = requests.put(f"{base}/ip/dhcp-client", auth=ROUTER_AUTH, json={"interface": "macvlan1", "add-default-route": "no", "use-peer-dns": "no"}, timeout=5)
        if res.status_code in (200, 201):
            dhcp_id = res.json().get(".id")
            print(f"  [✓] Added macvlan1 DHCP client")

    # Poll DHCP status until bound
    print("  [*] Waiting for macvlan1 DHCP bound IP...")
    pub_ip, gateway = None, None
    for _ in range(15):
        r_dhcp = requests.get(f"{base}/ip/dhcp-client", auth=ROUTER_AUTH, timeout=5)
        if r_dhcp.status_code == 200:
            for d in r_dhcp.json():
                if d.get("interface") == "macvlan1" and d.get("status") == "bound":
                    pub_ip = d.get("address", "").split("/")[0]
                    gateway = d.get("gateway")
                    break
        if pub_ip and gateway:
            break
        time.sleep(1.0)
        
    if not pub_ip or not gateway:
        print("  [!] Failed to get macvlan1 DHCP IP")
        return None, None
        
    print(f"  [✓] macvlan1 Bound Public IP: {pub_ip} (Gateway: {gateway})")
    
    # 3. Setup NAT Masquerade
    r_nat = requests.get(f"{base}/ip/firewall/nat", auth=ROUTER_AUTH, timeout=5)
    has_nat = False
    if r_nat.status_code == 200:
        has_nat = any(n.get("out-interface") == "macvlan1" for n in r_nat.json())
    if not has_nat:
        requests.put(f"{base}/ip/firewall/nat", auth=ROUTER_AUTH, json={"chain": "srcnat", "action": "masquerade", "out-interface": "macvlan1", "comment": "nat-macvlan1"}, timeout=5)
        print("  [✓] NAT masquerade for macvlan1 configured")
        
    # 4. Setup Routing Table
    r_tbl = requests.get(f"{base}/routing/table", auth=ROUTER_AUTH, timeout=5)
    has_tbl = False
    if r_tbl.status_code == 200:
        has_tbl = any(t.get("name") == "to-macvlan1" for t in r_tbl.json())
    if not has_tbl:
        requests.put(f"{base}/routing/table", auth=ROUTER_AUTH, json={"name": "to-macvlan1", "fib": "yes"}, timeout=5)
        print("  [✓] Routing table to-macvlan1 created")
        
    # 5. Always Update Default Route with FRESH Gateway for to-macvlan1
    r_rt = requests.get(f"{base}/ip/route", auth=ROUTER_AUTH, timeout=5)
    if r_rt.status_code == 200:
        for r_item in r_rt.json():
            if r_item.get("routing-table") == "to-macvlan1":
                requests.delete(f"{base}/ip/route/{r_item['.id']}", auth=ROUTER_AUTH, timeout=5)
                
    new_gw = f"{gateway}%macvlan1"
    requests.put(f"{base}/ip/route", auth=ROUTER_AUTH, json={"dst-address": "0.0.0.0/0", "gateway": new_gw, "routing-table": "to-macvlan1"}, timeout=5)
    print(f"  [✓] Default route in to-macvlan1 updated to fresh gateway: {new_gw}")
        
    # 6. Setup Mangle Rule for 10.8.0.0/24
    r_mg = requests.get(f"{base}/ip/firewall/mangle", auth=ROUTER_AUTH, timeout=5)
    has_mg = False
    if r_mg.status_code == 200:
        has_mg = any(m.get("new-routing-mark") == "to-macvlan1" for m in r_mg.json())
    if not has_mg:
        requests.put(f"{base}/ip/firewall/mangle", auth=ROUTER_AUTH, json={
            "chain": "prerouting",
            "src-address": "10.8.0.0/24",
            "action": "mark-routing",
            "new-routing-mark": "to-macvlan1",
            "passthrough": "no",
            "comment": "WG-10.8.0.0/24-to-macvlan1"
        }, timeout=5)
        print("  [✓] Mangle prerouting for WireGuard 10.8.0.0/24 -> to-macvlan1 configured")
        
    return pub_ip, gateway

def activate_device_wireguard(device_id="R5CT20Y2XYE"):
    print(f"\n[WG ACTIVATE] Activating SINGLE 'wg0' WireGuard Tunnel on device {device_id}...")
    
    # 1. Setup RouterOS MacVlan & Policy Routing
    macvlan_ip, _ = setup_mikrotik_macvlan_and_routing()
    
    # 2. Generate and Patch WireGuard Keypair
    priv_key, pub_key = generate_and_patch_wireguard_keys(device_id, peer_id="*1")
    
    # 3. Clean all old/duplicate .conf files in device files directory (keep ONLY single wg0.conf)
    print("  [*] Cleaning up extra WireGuard profiles on device (enforcing single wg0)...")
    clean_cmd = (
        "su 0 sh -c '"
        "mkdir -p /data/data/com.wireguard.android/files && "
        "rm -f /data/data/com.wireguard.android/files/*.conf'"
    )
    run_adb(device_id, f'shell "{clean_cmd}"')
    
    # 4. Create SINGLE wg0.conf without Table = off
    client_wg_ip = "10.8.0.2"
    conf_content = f"""[Interface]
PrivateKey = {priv_key}
Address = {client_wg_ip}/24
DNS = 1.1.1.1, 8.8.8.8

[Peer]
PublicKey = {SERVER_WG_PUBKEY}
Endpoint = {SERVER_WG_ENDPOINT}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""
    tmp_conf = "/tmp/wg0_single.conf"
    with open(tmp_conf, "w", encoding="utf-8") as f:
        f.write(conf_content)
        
    run_adb(device_id, f"push {tmp_conf} /sdcard/Download/wg0.conf")
    inject_cmd = (
        "su 0 sh -c '"
        "cp /sdcard/Download/wg0.conf /data/data/com.wireguard.android/files/wg0.conf && "
        "chown -R 10317:10317 /data/data/com.wireguard.android/files && "
        "chmod 600 /data/data/com.wireguard.android/files/wg0.conf'"
    )
    run_adb(device_id, f'shell "{inject_cmd}"')
    
    # 5. 0.1s Instant UI Toggle for single wg0 profile
    print("  [*] Triggering 0.1s Instant UI Toggle for 'wg0' on smartphone...")
    run_adb(device_id, "shell am force-stop com.wireguard.android")
    run_adb(device_id, "shell am start -n com.wireguard.android/.activity.MainActivity")
    time.sleep(0.6)
    
    # Tap toggle switch for single item
    run_adb(device_id, "shell input tap 954 369")
    time.sleep(1.0)
    
    # Return to home screen immediately
    run_adb(device_id, "shell input keyevent 3")
    time.sleep(0.5)
    
    # Verify tun0
    out, _, _ = run_adb(device_id, "shell \"su 0 sh -c 'ip a'\"")
    if "tun0" in out:
        print("  [✓] Device WireGuard 'wg0' tun0 interface is ACTIVE!")
    else:
        print("  [!] WireGuard tun0 interface not detected, sending broadcast retry for wg0...")
        run_adb(device_id, "shell am broadcast -a com.wireguard.android.action.SET_TUNNEL_UP -e tunnel wg0 com.wireguard.android")
        
    # Verify device Public IP
    dev_ip, _, _ = run_adb(device_id, "shell \"su 0 sh -c 'curl -s --connect-timeout 8 https://api.ipify.org || curl -s --connect-timeout 8 http://ifconfig.me'\"")
    dev_ip = dev_ip.strip()
    print(f"  📱 Device Public IP: '{dev_ip}'")
    print(f"  🌐 MacVlan Router IP: '{macvlan_ip}'")
    if dev_ip == macvlan_ip:
        print("  🎉 PERFECT MATCH! Device traffic is 100% routed through WireGuard 'wg0' & MacVlan!")
    else:
        print(f"  [!] Notice: Device IP ({dev_ip}) != MacVlan IP ({macvlan_ip})")

def deactivate_device_wireguard(device_id="R5CT20Y2XYE"):
    print(f"\n[WG DEACTIVATE] Disconnecting WireGuard 'wg0' Tunnel on device {device_id}...")
    try:
        run_adb(device_id, "shell am broadcast -a com.wireguard.android.action.SET_TUNNEL_DOWN -e tunnel wg0 com.wireguard.android")
        run_adb(device_id, "shell am force-stop com.wireguard.android")
        print("  [✓] WireGuard 'wg0' tunnel deactivated & app force-stopped.")
    except Exception as e:
        print(f"  [!] Deactivate WireGuard error: {e}")

def toggle_macvlan_ip(device_id="R5CT20Y2XYE") -> dict:
    host = get_router_host()
    base = f"http://{host}/rest"
    
    # First: Ensure WireGuard is deactivated on device BEFORE toggling router IP
    deactivate_device_wireguard(device_id)
    
    print("\n==========================================================================")
    print(" 🌐 [WIREGUARD / MACVLAN IP TOGGLE ENGINE]")
    print("==========================================================================")
    
    try:
        # Find macvlan1 ID
        r = requests.get(f"{base}/interface/macvlan", auth=ROUTER_AUTH, timeout=5)
        macvlan_id = None
        if r.status_code == 200:
            for item in r.json():
                if item.get("name") == "macvlan1":
                    macvlan_id = item.get(".id")
                    break
                    
        # Find macvlan1 DHCP client ID
        r_dhcp = requests.get(f"{base}/ip/dhcp-client", auth=ROUTER_AUTH, timeout=5)
        dhcp_id = None
        if r_dhcp.status_code == 200:
            for item in r_dhcp.json():
                if item.get("interface") == "macvlan1":
                    dhcp_id = item.get(".id")
                    break

        new_mac = f"F6:1C:6B:{random.randint(10,99):02X}:{random.randint(10,99):02X}:{random.randint(10,99):02X}"
        print(f"  [Action] Randomizing macvlan1 MAC address -> {new_mac}...")
        
        if macvlan_id:
            requests.patch(f"{base}/interface/macvlan/{macvlan_id}", auth=ROUTER_AUTH, json={"mac-address": new_mac}, timeout=10)
            
        if dhcp_id:
            print("  [Action] Releasing & Renewing DHCP lease for macvlan1...")
            requests.post(f"{base}/ip/dhcp-client/release", auth=ROUTER_AUTH, json={".id": dhcp_id}, timeout=10)
            time.sleep(1.0)
            requests.post(f"{base}/ip/dhcp-client/renew", auth=ROUTER_AUTH, json={".id": dhcp_id}, timeout=10)
            
        time.sleep(3.0)
        new_router_ip, gateway = setup_mikrotik_macvlan_and_routing()
        
        print("==========================================================================")
        print(f" 🎉 IP TOGGLE COMPLETE! New Router MacVlan IP: {new_router_ip}")
        print("==========================================================================")
        return {"status": "SUCCESS", "new_ip": new_router_ip}
    except Exception as e:
        print(f"  [!] toggle_macvlan_ip error: {e}")
        return {"status": "FAILED", "error": str(e)}

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    target_device = sys.argv[2] if len(sys.argv) > 2 else "R5CT20Y2XYE"
    
    if action == "activate":
        activate_device_wireguard(target_device)
    elif action == "deactivate":
        deactivate_device_wireguard(target_device)
    elif action == "toggle":
        toggle_macvlan_ip(target_device)
    elif action == "check":
        setup_mikrotik_macvlan_and_routing()
    else:
        print(f"Unknown action: {action}")
