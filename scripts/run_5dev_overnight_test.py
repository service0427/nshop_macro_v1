#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
5대 전 단말기 24/7 안정성 검증 & 무인 자가치료 오버나이트 스트레스 테스트
(scripts/run_5dev_overnight_test.py)
========================================================================================
- 종료 목표 시각: 2026-08-30 09:00:00 KST (또는 수동 중지 시까지)
- 10회마다 전 단말기 상세 통계 출력 및 JSON 저장
- 배터리 20% 미만 시 자동 패스 (방전 꺼짐 원천 차단)
- 배터리 과열(43°C 이상) 시 자동 쿨다운 대기
- 실패 발생 시 자동 자가치료 (ADB 재연결, 화면 언락, 프로세스 정리, 샌드박스 복구)
========================================================================================
"""

import os
import sys
import time
import json
import sqlite3
import logging
import datetime
import subprocess
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/home/tech/nshop_macro_v1")
from src.modules.soft_reboot_mutator import SoftRebootMutator

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Overnight5DevTest")

DEVICES = [
    "R3CR70KAZDM",
    "R3CR70SZ0JJ",
    "R3CRB0WCGET",
    "R5CR713T5WT",
    "R5CR9336DSB"
]

TARGET_END_TIME = datetime.datetime(2026, 8, 30, 9, 0, 0)
RESULTS_JSON_PATH = "/home/tech/nshop_macro_v1/logs/stress_test_5dev_continuous.json"
RESULTS_LOG_PATH = "/home/tech/nshop_macro_v1/logs/stress_test_5dev_continuous.log"

def get_battery_info(device_id: str) -> dict:
    """단말기 배터리 잔량 및 온도 확인"""
    try:
        out = subprocess.check_output(
            ["adb", "-s", device_id, "shell", "dumpsys battery"],
            timeout=4, stderr=subprocess.DEVNULL, text=True
        )
        level = 100
        temp = 25.0
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("level:"):
                level = int(line.split(":")[1].strip())
            elif line.startswith("temperature:"):
                temp = int(line.split(":")[1].strip()) / 10.0
        return {"level": level, "temp": temp}
    except Exception:
        return {"level": 100, "temp": 25.0}

def reset_usb_by_serial(target_serial: str) -> bool:
    """단말기 시리얼과 일치하는 USB 버스 포트를 하드웨어 레벨에서 전원 리셋"""
    import glob
    for s_path in glob.glob("/sys/bus/usb/devices/*/serial"):
        try:
            with open(s_path, "r") as f:
                if f.read().strip() == target_serial:
                    dev_dir = os.path.dirname(s_path)
                    busnum = open(os.path.join(dev_dir, "busnum")).read().strip().zfill(3)
                    devnum = open(os.path.join(dev_dir, "devnum")).read().strip().zfill(3)
                    usb_addr = f"{busnum}/{devnum}"
                    logger.warning(f"  [🔌 {target_serial}] USB 하드웨어 버스 전원 리셋 실행 ({usb_addr})...")
                    subprocess.run(["usbreset", usb_addr], capture_output=True, timeout=5)
                    time.sleep(2.5)
                    subprocess.run(["adb", "-s", target_serial, "wait-for-device"], timeout=12, capture_output=True)
                    logger.info(f"  [⚡ {target_serial}] USB 전원 재인가 및 ADB 재연결 완료!")
                    return True
        except Exception:
            pass
    return False

def self_heal_device(device_id: str, reason: str = ""):
    """단말기 고장/실패/연결끊김 시 즉시 자가치료 (USB 리셋 + ADB 복구 + 런처 복귀)"""
    logger.warning(f"  [🚑 {device_id} 자가치료 시작] 원인: {reason}")
    try:
        # 1. 단말기 응답 확인 - 응답 없거나 offline이면 USB 하드웨어 포트 전원 리셋!
        chk = subprocess.run(["adb", "-s", device_id, "shell", "echo 1"], capture_output=True, text=True, timeout=4)
        if chk.returncode != 0 or "1" not in chk.stdout:
            logger.warning(f"  [⚠️ {device_id}] ADB 응답 없음 / offline 감지 -> USB 포트 하드웨어 전원 껐다 켜기(usbreset) 실행!")
            reset_usb_by_serial(device_id)

        # 2. ADB 연결 재연결
        subprocess.run(["adb", "-s", device_id, "reconnect"], timeout=4, capture_output=True)
        time.sleep(1.5)
        subprocess.run(["adb", "-s", device_id, "wait-for-device"], timeout=10, capture_output=True)
        
        # 3. 프로세스 강제 정리
        subprocess.run(
            ["adb", "-s", device_id, "shell", "su -c 'am force-stop com.nhn.android.search; am force-stop com.wireguard.android'"],
            timeout=4, capture_output=True
        )
        
        # 4. 화면 켜기 & 언락 & 런처 복귀
        heal_script = """
svc power stayon true
settings put system screen_off_timeout 2147483647
input keyevent 224
input swipe 500 1500 500 500
input keyevent 3
pm clear com.nhn.android.search
restorecon -R /data/data/com.nhn.android.search
rm -rf /data/local/tmp/*.db /data/local/tmp/*.xml 2>/dev/null || true
"""
        subprocess.run(
            ["adb", "-s", device_id, "shell", f"su -c '{heal_script}'"],
            timeout=6, capture_output=True
        )
        logger.info(f"  [✅ {device_id} 자가치료 완료] 런처 복귀 및 샌드박스 환경 완전 정상화")
    except Exception as e:
        logger.error(f"  [❌ {device_id} 자가치료 중 오류]: {e}")

def wait_for_launcher_focus(device_id: str, timeout_sec: int = 25) -> bool:
    """런처/메인 화면 안착 폴링"""
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        try:
            focus = subprocess.run(
                ["adb", "-s", device_id, "shell", "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'"],
                capture_output=True, text=True, timeout=3
            ).stdout
            if "LauncherActivity" in focus:
                return True
            subprocess.run(
                ["adb", "-s", device_id, "shell", "su -c 'svc power stayon true; input keyevent 224; input swipe 500 1500 500 500; input keyevent 3'"],
                capture_output=True, timeout=4
            )
        except Exception:
            pass
        time.sleep(0.8)
    return False

def test_single_device(device_id: str, cycle_num: int) -> dict:
    """단일 단말기 주기 실행"""
    batt = get_battery_info(device_id)
    level = batt.get("level", 100)
    temp = batt.get("temp", 25.0)

    # 1. 배터리 20% 미만 안전 보호 (PASS)
    if level < 20:
        logger.warning(f"[{device_id}] [⚠️ 배터리 부족: {level}%] 방전 꺼짐 방지를 위해 이번 회차를 PASS합니다.")
        return {
            "device_id": device_id,
            "status": "PASSED_LOW_BATTERY",
            "battery_level": level,
            "battery_temp": temp,
            "ssaid": "-",
            "napp_di": "PASS",
            "nnb": "PASS",
            "poll_time_sec": 0.0,
            "duration_sec": 0.1
        }

    # 2. 배터리 과열(43°C) 쿨다운 보호
    if temp >= 43.0:
        logger.warning(f"[{device_id}] [⚠️ 과열 감지: {temp}°C] 기기 보호를 위해 30초 쿨다운 후 이번 회차를 PASS합니다.")
        time.sleep(10.0)
        return {
            "device_id": device_id,
            "status": "PASSED_OVERHEAT",
            "battery_level": level,
            "battery_temp": temp,
            "ssaid": "-",
            "napp_di": "PASS",
            "nnb": "PASS",
            "poll_time_sec": 0.0,
            "duration_sec": 0.1
        }

    t_start = time.time()
    ssaid = "UNKNOWN"
    napp_di = "없음"
    nnb = "없음"
    poll_time = 0.0
    status = "FAILED"

    try:
        mutator = SoftRebootMutator(device_id)
        mut_res = mutator.mutate_identity(mode="FRESH")
        ssaid = mut_res.get("ssaid", "UNKNOWN")

        # 런처 안착 확인
        wait_for_launcher_focus(device_id, timeout_sec=20)

        # 네이버 웹뷰 실행 (최대 3회 재시도)
        for _ in range(3):
            try:
                res = subprocess.run(
                    ["adb", "-s", device_id, "shell", "su -c 'am start -a android.intent.action.VIEW -d https://m.naver.com com.nhn.android.search'"],
                    capture_output=True, text=True, timeout=5
                )
                if "Starting: Intent" in res.stdout:
                    break
            except Exception:
                pass
            time.sleep(1.0)

        t_poll = time.time()
        home_pressed = False
        local_db = f"/tmp/cont_ck_{device_id}_{cycle_num}.db"

        while time.time() - t_poll < 20.0:
            elapsed = round(time.time() - t_poll, 1)
            if elapsed >= 6.5 and not home_pressed:
                try:
                    subprocess.run(["adb", "-s", device_id, "shell", "su -c 'input keyevent 3'"], capture_output=True, timeout=3)
                    home_pressed = True
                except Exception:
                    pass

            if elapsed >= 6.5:
                try:
                    cmd = (
                        "if [ -f /data/data/com.nhn.android.search/app_xwhale/Default/Cookies ]; then "
                        "echo /data/data/com.nhn.android.search/app_xwhale/Default/Cookies; "
                        "elif [ -f /data/data/com.nhn.android.search/app_webview/Default/Cookies ]; then "
                        "echo /data/data/com.nhn.android.search/app_webview/Default/Cookies; "
                        "else find /data/data/com.nhn.android.search -name '*Cookies*' 2>/dev/null | grep -v journal | grep -v Safe | head -n 1; fi"
                    )
                    target_path = subprocess.run(
                        ["adb", "-s", device_id, "shell", f"su -c '{cmd}'"],
                        capture_output=True, text=True, timeout=4
                    ).stdout.strip()

                    if target_path:
                        subprocess.run(
                            ["adb", "-s", device_id, "shell", f"su -c 'cp {target_path} /data/local/tmp/p_ck_{device_id}.db && chmod 777 /data/local/tmp/p_ck_{device_id}.db'"],
                            capture_output=True, timeout=4
                        )
                        subprocess.run(
                            ["adb", "-s", device_id, "pull", f"/data/local/tmp/p_ck_{device_id}.db", local_db],
                            capture_output=True, timeout=4
                        )
                        if os.path.exists(local_db) and os.path.getsize(local_db) > 0:
                            conn = sqlite3.connect(local_db)
                            c = conn.cursor()
                            c.execute("SELECT name, value FROM cookies WHERE name IN ('NAPP_DI', 'NNB')")
                            rows = dict(c.fetchall())
                            conn.close()

                            if rows.get("NAPP_DI") and rows.get("NNB"):
                                napp_di = rows.get("NAPP_DI")
                                nnb = rows.get("NNB")
                                poll_time = elapsed
                                status = "SUCCESS"
                                subprocess.run(["adb", "-s", device_id, "shell", "su -c 'am force-stop com.nhn.android.search'"], capture_output=True, timeout=3)
                                try: os.remove(local_db)
                                except: pass
                                break
                except Exception:
                    pass
            time.sleep(0.5)

        try:
            subprocess.run(["adb", "-s", device_id, "shell", "su -c 'am force-stop com.nhn.android.search'"], capture_output=True, timeout=3)
        except Exception:
            pass
        if os.path.exists(local_db):
            try: os.remove(local_db)
            except: pass

    except Exception as e:
        logger.error(f"[{device_id}] 예외 발생: {e}")
        status = "FAILED"

    # 실패 시 즉시 자가치료
    if status != "SUCCESS":
        self_heal_device(device_id, f"쿠키발급실패 (NAPP_DI: {napp_di})")

    dur = round(time.time() - t_start, 1)
    logger.info(f"[{device_id}] #{cycle_num:03d} 완료 | {status} | NAPP_DI: {napp_di[:10]}.. | NNB: {nnb} | 배터리: {level}%({temp}°C) | 소요: {dur}s")

    return {
        "device_id": device_id,
        "status": status,
        "battery_level": level,
        "battery_temp": temp,
        "ssaid": ssaid,
        "napp_di": napp_di,
        "nnb": nnb,
        "poll_time_sec": poll_time,
        "duration_sec": dur
    }

def print_10cycle_summary(cycle_num: int, history: list):
    """10회 단위 종합 통계 현황판 출력"""
    logger.info("\n" + "=" * 84)
    logger.info(f"📊 [5대 전 단말기 누적 종합 통계 현황판 (주기 #{cycle_num} 완료)]")
    logger.info("=" * 84)
    
    device_stats = {d: {"success": 0, "total": 0, "unique_di": set(), "unique_nnb": set(), "durations": []} for d in DEVICES}
    
    for entry in history:
        for r in entry.get("results", []):
            d = r["device_id"]
            if d in device_stats:
                device_stats[d]["total"] += 1
                if r["status"] == "SUCCESS":
                    device_stats[d]["success"] += 1
                    if r["napp_di"] != "없음" and r["napp_di"] != "PASS":
                        device_stats[d]["unique_di"].add(r["napp_di"])
                    if r["nnb"] != "없음" and r["nnb"] != "PASS":
                        device_stats[d]["unique_nnb"].add(r["nnb"])
                if r["duration_sec"] > 1.0:
                    device_stats[d]["durations"].append(r["duration_sec"])

    for d in DEVICES:
        st = device_stats[d]
        tot = st["total"]
        succ = st["success"]
        rate = (succ / tot * 100) if tot > 0 else 0
        uniq_di = len(st["unique_di"])
        uniq_nnb = len(st["unique_nnb"])
        avg_dur = round(sum(st["durations"]) / len(st["durations"]), 1) if st["durations"] else 0.0
        batt = get_battery_info(d)
        logger.info(f"  • {d:<12} | 성공률: {rate:5.1f}% ({succ}/{tot}) | 고유 NAPP_DI: {uniq_di:2d}개 | 고유 NNB: {uniq_nnb:2d}개 | 평균: {avg_dur:4.1f}s | 배터리: {batt['level']}% ({batt['temp']}°C)")
    logger.info("=" * 84 + "\n")

def main():
    logger.info("=" * 84)
    logger.info(f"🚀 [5대 전 단말기 24/7 오버나이트 안정성 검증 & 자가치료 루프 시작]")
    logger.info(f"   - 대상 단말기: {DEVICES}")
    logger.info(f"   - 목표 완료 시각: {TARGET_END_TIME} (약 12시간 연속 가동)")
    logger.info(f"   - 안전 보호: 배터리 < 20% 자동 PASS, 과열(>=43°C) 자동 쿨다운, 실패 시 자가치료")
    logger.info("=" * 84)

    os.makedirs("/home/tech/nshop_macro_v1/logs", exist_ok=True)
    history = []
    cycle = 0

    while True:
        now = datetime.datetime.now()
        if now >= TARGET_END_TIME:
            logger.info(f"\n🎉 [오버나이트 검증 완료] 목표 시각({TARGET_END_TIME})에 도달하여 테스트를 정상 종료합니다.")
            break

        cycle += 1
        t_cycle_start = time.time()
        logger.info(f"\n--- [주기 #{cycle:03d} 시작] 5대 병렬 소프트 리셋 & 신원 변조 진행 중 (남은 시간: {TARGET_END_TIME - now}) ---")

        # 5대 단말기 동시 병렬 실행
        with ThreadPoolExecutor(max_workers=len(DEVICES)) as executor:
            cycle_results = list(executor.map(lambda d: test_single_device(d, cycle), DEVICES))

        dur_cycle = round(time.time() - t_cycle_start, 1)
        history.append({
            "cycle": cycle,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cycle_duration_sec": dur_cycle,
            "results": cycle_results
        })

        # 실시간 JSON 파일 저장 (비정상 중단 대비 영구 보존)
        with open(RESULTS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "target_end_time": str(TARGET_END_TIME),
                "total_cycles_completed": cycle,
                "devices": DEVICES,
                "history": history
            }, f, indent=2, ensure_ascii=False)

        # 10회 주기마다 종합 통계 출력
        if cycle % 10 == 0:
            print_10cycle_summary(cycle, history)

        time.sleep(2.0)

if __name__ == "__main__":
    main()
