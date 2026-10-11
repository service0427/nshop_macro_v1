#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/mitm/mitm_manager.py

Mitmproxy 디버깅 세션 생명주기 관리자
- --mitm 옵션 활성화 시 mitmdump 데몬 기동 및 단말기 http_proxy 자동 설정
- 작업 완료 후 반드시 http_proxy :0 초기화 및 프로세스 안전 종료
- 100% 읽기 전용 패킷 순번 덤프 보장
"""

import os
import sys
import time
import subprocess
import signal
from pathlib import Path
from typing import Optional

from config.settings import DEFAULT_DEVICE_ID, LOGS_DIR

MITM_ADDON_PATH = Path("/home/tech/nshop_macro_v1/src/client/mitm/dump_addon.py")

def ensure_ca_cert_installed(device_id: str = DEFAULT_DEVICE_ID):
    """단말기 시스템 인증서(/system/etc/security/cacerts/c8750f0d.0)와 mitmproxy CA 인증서 동기화 보장"""
    ca_cert = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.cer"
    if not ca_cert.exists():
        return
    try:
        with open(ca_cert, "r", encoding="utf-8") as f:
            local_cert = f.read().strip()
        chk = subprocess.run(["adb", "-s", device_id, "shell", "cat /system/etc/security/cacerts/c8750f0d.0 2>/dev/null"], capture_output=True, text=True)
        if local_cert not in chk.stdout:
            print(f"🔒 [인증서 동기화] 단말기({device_id})에 최신 mitmproxy CA 인증서 주입 및 마운트...")
            subprocess.run(["adb", "-s", device_id, "push", str(ca_cert), "/data/local/tmp/c8750f0d.0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            inject_cmd = (
                "cp /data/local/tmp/c8750f0d.0 /data/adb/modules/trustusercerts/system/etc/security/cacerts/c8750f0d.0; "
                "chmod 644 /data/adb/modules/trustusercerts/system/etc/security/cacerts/c8750f0d.0; "
                "mount --bind /data/adb/modules/trustusercerts/system/etc/security/cacerts/c8750f0d.0 /system/etc/security/cacerts/c8750f0d.0"
            )
            subprocess.run(["adb", "-s", device_id, "shell", f"su -c '{inject_cmd}'"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"⚠️ [인증서 점검 경고] {e}")

class MitmSessionManager:
    def __init__(self, device_id: str = DEFAULT_DEVICE_ID, port: int = 8888):
        self.device_id = device_id
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.session_dir: Optional[Path] = None

    def start(self, keyword: str = "", session_tag: Optional[str] = None) -> Path:
        """
        mitmdump를 백그라운드로 실행하고 단말기 프록시를 연결
        경로 형식: {His}_{device}_{검색어} (날짜는 상위 폴더)
        """
        his = time.strftime("%H%M%S")
        date_str = time.strftime("%Y%m%d")

        kw_part = keyword
        if not kw_part and session_tag:
            kw_part = session_tag.split("_")[-1] if "_" in session_tag else session_tag
        if not kw_part:
            kw_part = "task"

        folder_name = f"{his}_{self.device_id}_{kw_part}"
        self.session_dir = LOGS_DIR / "mitm_dumps" / date_str / folder_name
        self.session_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["MITM_DUMP_DIR"] = str(self.session_dir)

        # 0. 잔존 mitmdump 프로세스 정리 및 CA 인증서 동기화
        subprocess.run(["pkill", "-9", "-f", "mitmdump"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ensure_ca_cert_installed(self.device_id)

        # 1. 이전 잔여 프록시 정리
        subprocess.run(["adb", "-s", self.device_id, "shell", "settings delete global http_proxy; settings delete global global_http_proxy_host; settings delete global global_http_proxy_port"], check=False)

        # 2. mitmdump 실행 (포트 8888, SSL 검증 완화, 조용 모드)
        cmd = [
            "/home/tech/.local/bin/mitmdump",
            "-s", str(MITM_ADDON_PATH),
            "-p", str(self.port),
            "--set", "block_global=false",
            "--ssl-insecure",
            "--quiet"
        ]
        print(f"🚀 [MITM 기동] mitmdump 포트 {self.port} 가동 중...")
        self.process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )

        time.sleep(1.2)

        # 3. 단말기 리버스 포워딩 및 http_proxy 설정
        print(f"📱 [단말기 프록시 설정] {self.device_id} -> 127.0.0.1:{self.port}")
        subprocess.run(["adb", "-s", self.device_id, "reverse", f"tcp:{self.port}", f"tcp:{self.port}"], check=True)
        subprocess.run(["adb", "-s", self.device_id, "shell", f"settings put global http_proxy 127.0.0.1:{self.port}"], check=True)

        time.sleep(0.5)
        print(f"📁 [패킷 덤프 디렉토리] {self.session_dir}")
        return self.session_dir

    def stop(self):
        """
        프록시 설정을 즉시 해제하고 mitmdump 프로세스 종료
        """
        print("\n🛑 [MITM 종료] 단말기 프록시 해제 및 mitmdump 종료 중...")
        # 1. 단말기 프록시 즉시 해제
        try:
            subprocess.run(["adb", "-s", self.device_id, "shell", "settings delete global http_proxy; settings delete global global_http_proxy_host; settings delete global global_http_proxy_port"], check=False)
            subprocess.run(["adb", "-s", self.device_id, "reverse", "--remove", f"tcp:{self.port}"], check=False)
        except Exception:
            pass

        # 2. 프로세스 종료
        if self.process:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=2.0)
            except Exception:
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except Exception:
                    pass
            self.process = None

        # 3. 캡처 결과 요약
        if self.session_dir and self.session_dir.exists():
            dump_files = list(self.session_dir.glob("*.json"))
            summary_file = self.session_dir / "session_summary.json"
            print(f"📊 [MITM 패킷 캡처 완료] 총 {len(dump_files)}개 파일 기록됨")
            print(f" • 상세 파일 위치: {self.session_dir}")
            if summary_file.exists():
                print(f" • 세션 요약 파일: {summary_file}")
