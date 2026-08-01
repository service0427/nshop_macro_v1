#!/usr/bin/env python3
import json
import random
import sys
import subprocess
import os

def run_macro_step(device_id, step_id, config_path="api/macro_config.json"):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        step = config["steps"].get(step_id)
        if not step:
            print(f"[-] Error: Step ID '{step_id}' not found in config.")
            return

        # [x1, y1, x2, y2]
        b = step["bounds"]
        p = step.get("padding", 5)
        
        # Calculate random coordinates within bounds with padding
        x = random.randint(b[0] + p, b[2] - p)
        y = random.randint(b[1] + p, b[3] - p)
        
        print(f"[*] Macro Execution [{step_id}]: {step['desc']}")
        print(f"[*] Calculated Tap: ({x}, {y}) on device {device_id}")
        
        # Execute ADB tap
        cmd = ["adb", "-s", device_id, "shell", "input", "tap", str(x), str(y)]
        subprocess.run(cmd, check=True)
        
    except Exception as e:
        print(f"[-] Macro Execution Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: ./macro_executor.py <DEVICE_ID> <STEP_ID>")
        sys.exit(1)
        
    dev_id = sys.argv[1]
    step_id = sys.argv[2]
    run_macro_step(dev_id, step_id)
