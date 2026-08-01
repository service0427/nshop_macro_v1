#!/usr/bin/env python3
import sys
import subprocess
import xml.etree.ElementTree as ET
import time

def dump_ui(device_id):
    """지정된 기기의 현재 UI 계층을 덤프하고 읽어옵니다."""
    dump_path = "/sdcard/window_dump.xml"
    subprocess.run(["adb", "-s", device_id, "shell", "uiautomator", "dump", dump_path], 
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    
    xml_output = subprocess.check_output(["adb", "-s", device_id, "shell", "cat", dump_path]).decode('utf-8', errors='ignore')
    return xml_output

def find_bounds_by_target(xml_data, target):
    """XML 데이터에서 대상 텍스트, desc 또는 id가 일치하는 노드의 bounds를 찾습니다."""
    try:
        root = ET.fromstring(xml_data)
        for node in root.iter('node'):
            text = node.get('text', '')
            desc = node.get('content-desc', '')
            res_id = node.get('resource-id', '')
            
            if target.startswith("id:"):
                if target[3:] == res_id:
                    return node.get('bounds')
            elif target.startswith("desc:"):
                if target[5:] in desc:
                    return node.get('bounds')
            elif target.startswith("exact:"):
                if target[6:] == text:
                    return node.get('bounds')
            else:
                if target in text:
                    return node.get('bounds')
    except Exception as e:
        print(f"[-] XML 파싱 에러: {e}")
    return None

def parse_bounds(bounds_str):
    """'[x1,y1][x2,y2]' 형식의 문자열을 파싱하여 중앙 좌표를 반환합니다."""
    # "[192,357][914,406]" -> "192,357", "914,406]" -> x1=192, y1=357, x2=914, y2=406
    import re
    matches = re.findall(r'\[(\d+),(\d+)\]', bounds_str)
    if len(matches) == 2:
        x1, y1 = int(matches[0][0]), int(matches[0][1])
        x2, y2 = int(matches[1][0]), int(matches[1][1])
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        return center_x, center_y
    return None

def click_target(device_id, target):
    print(f"[*] [{device_id}] UI 덤프 및 요소 검색 중: {target}")
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            xml_data = dump_ui(device_id)
            bounds = find_bounds_by_target(xml_data, target)
            
            if bounds:
                center_coord = parse_bounds(bounds)
                if center_coord:
                    x, y = center_coord
                    print(f"[✓] [{device_id}] 주소 발견! 클릭 좌표: ({x}, {y})")
                    subprocess.run(["adb", "-s", device_id, "shell", "input", "tap", str(x), str(y)], check=True)
                    return True
            print(f"[-] [{device_id}] 주소를 찾을 수 없습니다. (시도 {attempt+1}/{max_retries})")
        except Exception as e:
            print(f"[-] [{device_id}] 에러 발생: {e}")
            
        time.sleep(1.5)
        
    print(f"[!] [{device_id}] 주소 검색 실패. 대상을 찾지 못했습니다.")
    return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: ./ui_clicker.py <DEVICE_ID> <TARGET_ADDRESS>")
        sys.exit(1)
        
    dev_id = sys.argv[1]
    target = sys.argv[2]
    
    success = click_target(dev_id, target)
    if not success:
        sys.exit(1)
