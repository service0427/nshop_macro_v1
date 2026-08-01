import json
import glob
import os
import sys

# 현재 위치 분석
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.dirname(BASE_DIR)
PROJECT_ROOT = os.path.dirname(LIB_DIR)
ROUTE_DIR = os.path.join(PROJECT_ROOT, "route_library")

def build_xml(target_file=None, speed=60.0, dev_id="default"):
    output_path = f"/tmp/final_1_prefs_{dev_id}.xml"
    if target_file and os.path.exists(target_file):
        route_json = target_file
    else:
        json_files = sorted(glob.glob(os.path.join(ROUTE_DIR, "*.json")), key=os.path.getmtime, reverse=True)
        if not json_files: return
        route_json = json_files[0]

    display_name = os.path.splitext(os.path.basename(route_json))[0]
    
    # [FIX] 속도값을 인자로 받아 직접 주입
    entries = [
        '    <boolean name="noads" value="true" />',
        '    <boolean name="onettimeblock" value="true" />',
        '    <int name="pagbookmark" value="1" />',
        '    <int name="accion" value="0" />',
        f'    <float name="velocidad" value="{speed}" />'
    ]
    
    with open(route_json, "r") as f:
        coords = json.load(f)
    
    coord_str = ";".join([f"{lat},{lng}" for lat, lng in coords]) + ";"
    
    # ruta0 내부에도 속도 주입
    value = f"{display_name}+1+{speed}+0.0+{coord_str}"
    entries.append(f'    <string name="ruta0">{value}</string>')
    
    start_pt = f"{coords[0][0]},{coords[0][1]}"
    entries.append(f'    <string name="lastloc">Current_Start+{start_pt}+15.0</string>')

    xml_content = "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map>\n"
    xml_content += "\n".join(entries)
    xml_content += "\n</map>"
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_content)
    print(f"[✓] XML Built with Speed {speed} using {display_name}")

if __name__ == "__main__":
    # Usage: python3 rebuild_xml.py [file] [speed] [dev_id]
    arg_file = sys.argv[1] if len(sys.argv) > 1 else None
    arg_speed = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    arg_dev = sys.argv[3] if len(sys.argv) > 3 else "default"
    build_xml(arg_file, arg_speed, arg_dev)
