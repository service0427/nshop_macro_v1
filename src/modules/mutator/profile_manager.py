#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[모듈명] 프로필 저장소 및 세션 관리자 (ProfileStorageManager)
- 기능:
    1. 100개 단위 서브디렉토리(pf_1_100 등) 프로필 경로 산출 및 해결
    2. 동적 타겟(app_xwhale, app_webview, databases, shared_prefs, files) tar 스냅샷 저장
    3. 서버 DB 대조 100개 단위 서브폴더 자동 동기화 및 미등록/폐기 프로필 자동 Prune
    4. 쿠키 SQLite DB(app_xwhale/Default/Cookies)에서 NNB, NAPP_DI 식별자 추출
"""

import os
import re
import sqlite3
import tempfile
import logging
import subprocess
from textwrap import dedent
from typing import Dict, Any, Optional, Tuple

from src.config import PROFILE_STORAGE_DIR, PRIMARY_SERVER_URL
from src.modules.mutator.os_environment import OSEnvironmentController

logger = logging.getLogger("SoftRebootMutator")


class ProfileStorageManager:
    """단말기 내 숙성 프로필 저장소 및 쿠키 세션 수명주기 관리자"""

    def __init__(self, device_id: str, package_name: str = "com.nhn.android.search"):
        self.device_id = device_id
        self.package_name = package_name
        self.os_env = OSEnvironmentController(device_id, package_name)

    @staticmethod
    def get_profile_group_dir(profile_name_or_id: Any) -> str:
        """
        프로필 일련번호 기준 100개 단위 서브디렉토리 반환:
        예: pf_0000000014 (14) -> pf_1_100
            pf_0000000125 (125) -> pf_101_200
            pf_0000000201 (201) -> pf_201_300
        """
        seq = 0
        if isinstance(profile_name_or_id, int):
            seq = profile_name_or_id
        elif isinstance(profile_name_or_id, str):
            digits = re.findall(r"\d+", profile_name_or_id)
            if digits:
                seq = int(digits[-1])
        if seq <= 0:
            return "pf_1_100"
        group_start = ((seq - 1) // 100) * 100 + 1
        group_end = group_start + 99
        return f"pf_{group_start}_{group_end}"

    def get_profile_tar_path(self, profile_name_or_id: Any) -> str:
        """단말기 내 서브디렉토리(pf_1_100 등)가 적용된 정규 프로필 tar.gz 경로 반환"""
        p_name = str(profile_name_or_id).strip()
        if not p_name.endswith(".tar.gz"):
            p_name = f"{p_name}.tar.gz"
        grp = self.get_profile_group_dir(p_name)
        return f"{PROFILE_STORAGE_DIR}/{grp}/{p_name}"

    def profile_exists_on_device(self, profile_tar: str) -> bool:
        if not profile_tar:
            return False
        out = self.os_env.run_adb_su(f"test -f '{profile_tar}' && echo YES || echo NO")
        return "YES" in out.split()

    def resolve_profile_path(self, profile_name_or_id: Any) -> Optional[str]:
        """서브디렉토리 경로 우선 확인 후 레거시 루트 경로까지 fallback 검사하여 실제 존재하는 tar.gz 경로 반환"""
        if not profile_name_or_id:
            return None
        p_name = str(profile_name_or_id).strip()
        # [🕶️ 시크릿 1회성 모드] pf_0000000000은 영구 프로필이 아니므로 복원 경로 반환하지 않음
        if p_name.startswith("pf_0000000000") or p_name == "pf_0000000000.tar.gz":
            return None

        if not p_name.endswith(".tar.gz"):
            p_name = f"{p_name}.tar.gz"

        # 1. 서브디렉토리 경로 (pf_1_100/...)
        sub_path = self.get_profile_tar_path(p_name)
        if self.profile_exists_on_device(sub_path):
            return sub_path

        # 2. 레거시 루트 경로 (profile_storage/...)
        flat_path = f"{PROFILE_STORAGE_DIR}/{p_name}"
        if self.profile_exists_on_device(flat_path):
            return flat_path

        return sub_path

    def save_profile_snapshot(self, profile_name: str) -> Tuple[Optional[str], Optional[float]]:
        """네이버 앱 쿠키(app_xwhale 포함 5대 디렉토리) 전체 스냅샷을 100개 단위 서브디렉토리 및 히스토리 폴더에 저장"""
        if not profile_name:
            profile_name = "pf_0000000000"

        try:
            tar_filename = f"{profile_name}.tar.gz" if not profile_name.endswith(".tar.gz") else profile_name
            grp = self.get_profile_group_dir(tar_filename)
            dest_dir = f"{PROFILE_STORAGE_DIR}/{grp}"
            full_tar_path = f"{dest_dir}/{tar_filename}"

            # 히스토리 보관 (pf_0000000000 등 반복 작업 데이터 비교 분석용)
            from datetime import datetime
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            history_dir = f"{PROFILE_STORAGE_DIR}/backup_history"
            history_tar_path = f"{history_dir}/{profile_name}_{self.device_id}_{ts_str}.tar.gz"

            cmd = dedent(f"""\
                am force-stop {self.package_name} 2>/dev/null || true
                mkdir -p {dest_dir} {history_dir}
                cd /data/data/{self.package_name}
                TARGETS=""
                for d in app_xwhale app_webview databases shared_prefs files; do
                    [ -e "$d" ] && TARGETS="$TARGETS $d"
                done
                if [ -n "$TARGETS" ]; then
                    tar -czf {full_tar_path} $TARGETS 2>/dev/null || true
                    chmod 777 {full_tar_path} 2>/dev/null || true
                    cp {full_tar_path} {history_tar_path} 2>/dev/null || true
                    chmod 777 {history_tar_path} 2>/dev/null || true
                fi
            """).strip()
            self.os_env.run_adb_su(cmd)
            size_kb = self.os_env.get_file_size_kb(full_tar_path)
            logger.info(f"[{self.device_id}] [📸 프로필 스냅샷 저장 완료] -> {full_tar_path} (히스토리: {history_tar_path} | {size_kb} KB)")
            return full_tar_path, size_kb
        except Exception as e:
            logger.warning(f"[{self.device_id}] 프로필 스냅샷 저장 실패: {e}")
            return None, None

    def sync_profiles_with_server(self, server_host: str = PRIMARY_SERVER_URL) -> Dict[str, Any]:
        """
        [DB 우선 프로필 100회당 1회 동기화 및 100개 단위 서브폴더 자동 재정렬/정리]
        1. 서버 /api/v1/profiles 와 대조하여 미등록/폐기된 프로필을 모든 서브폴더에서 자동 삭제
        2. 루트 디렉토리나 타 폴더에 위치한 유효 프로필을 정규 100개 단위 서브폴더(pf_1_100 등)로 자동 이전
        3. 비어있는 빈 서브디렉토리 자동 정리
        """
        import requests
        cleaned_files = []
        migrated_files = []
        try:
            url = f"{server_host}/api/v1/profiles?device_id={self.device_id}&compact=1"
            res = requests.get(url, timeout=6).json()
            if res.get("status") == "success":
                valid_server_files = set()

                if "files" in res and isinstance(res["files"], list):
                    for item in res["files"]:
                        if isinstance(item, str):
                            fname = item if item.endswith(".tar.gz") else f"{item}.tar.gz"
                            valid_server_files.add(fname)

                if "profiles" in res and isinstance(res["profiles"], list):
                    for item in res["profiles"]:
                        if isinstance(item, dict):
                            if item.get("status", "READY") in ["READY", "AGING"]:
                                f = item.get("file") or item.get("name")
                                if f:
                                    fname = f if f.endswith(".tar.gz") else f"{f}.tar.gz"
                                    valid_server_files.add(fname)
                        elif isinstance(item, str):
                            fname = item if item.endswith(".tar.gz") else f"{item}.tar.gz"
                            valid_server_files.add(fname)

                # 1. 단말기 로컬 파일 목록 재귀 조회 (모든 서브폴더 포함)
                local_raw = self.os_env.run_adb_su(f"find {PROFILE_STORAGE_DIR} -name '*.tar.gz' 2>/dev/null")
                local_paths = [f.strip() for f in local_raw.splitlines() if f.strip().endswith(".tar.gz")]

                for fpath in local_paths:
                    fname = fpath.split("/")[-1]
                    if fname not in valid_server_files:
                        self.os_env.run_adb_su(f"rm -f {fpath}")
                        cleaned_files.append(fname)
                        logger.info(f"[{self.device_id}] 🧹 [DB 우선 프로필 정리] 서버 DB 미등록/폐기 파일 삭제: {fpath}")
                    else:
                        # 올바른 100개 단위 서브폴더(pf_1_100 등)로 자동 재배치
                        correct_path = self.get_profile_tar_path(fname)
                        if fpath != correct_path:
                            dest_dir = os.path.dirname(correct_path)
                            self.os_env.run_adb_su(f"mkdir -p {dest_dir} && mv {fpath} {correct_path} && chmod 777 {correct_path}")
                            migrated_files.append(fname)
                            logger.info(f"[{self.device_id}] 📂 [프로필 폴더 재배치] {fpath} ➔ {correct_path}")

                # 2. 빈 서브디렉토리 자동 정리
                self.os_env.run_adb_su(f"find {PROFILE_STORAGE_DIR} -mindepth 1 -type d -empty -delete 2>/dev/null || true")

                return {
                    "success": True,
                    "cleaned_count": len(cleaned_files),
                    "cleaned_files": cleaned_files,
                    "migrated_count": len(migrated_files),
                    "migrated_files": migrated_files
                }
        except Exception as e:
            logger.debug(f"[{self.device_id}] 프로필 DB 싱크 예외: {e}")
        return {"success": False, "cleaned_count": 0, "cleaned_files": [], "migrated_count": 0, "migrated_files": []}

    def extract_session_identifiers(self) -> Dict[str, Optional[str]]:
        """
        네이버 앱 세션 쿠키 DB(app_xwhale/Default/Cookies)에서 NNB, NAPP_DI 등 핵심 식별자 추출
        """
        tmp_dir = tempfile.mkdtemp()
        tmp_db = os.path.join(tmp_dir, f"Cookies_{self.device_id}")
        identifiers: Dict[str, Optional[str]] = {"nnb": None, "napp_di": None}
        try:
            cmd = f"cp /data/data/{self.package_name}/app_xwhale/Default/Cookies /data/local/tmp/Cookies_{self.device_id} && chmod 777 /data/local/tmp/Cookies_{self.device_id}"
            self.os_env.run_adb_su(cmd)
            subprocess.run(["adb", "-s", self.device_id, "pull", f"/data/local/tmp/Cookies_{self.device_id}", tmp_db],
                           timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.os_env.run_adb_su(f"rm -f /data/local/tmp/Cookies_{self.device_id}")

            if os.path.exists(tmp_db):
                conn = sqlite3.connect(tmp_db)
                c = conn.cursor()
                c.execute("SELECT name, value FROM cookies WHERE name IN ('NNB', 'NAPP_DI')")
                for name, val in c.fetchall():
                    if name == "NNB":
                        identifiers["nnb"] = val
                    elif name == "NAPP_DI":
                        identifiers["napp_di"] = val
                conn.close()
                logger.info(f"[{self.device_id}] [🍪 식별자 추출 완료] NNB: {identifiers.get('nnb')}, NAPP_DI: {identifiers.get('napp_di')}")
        except Exception as e:
            logger.warning(f"[{self.device_id}] 식별자 추출 중 예외: {e}")
        finally:
            if os.path.exists(tmp_db):
                os.remove(tmp_db)
            if os.path.exists(tmp_dir):
                os.rmdir(tmp_dir)
        return identifiers
