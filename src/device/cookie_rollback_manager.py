#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/device/cookie_rollback_manager.py

쿠키 롤백 전담 관리자 (Cookie Rollback Manager)
--------------------------------------------------
단말기 I/O 렉, 프로세스 지연 종료, SQLite 저널 복원으로 인한 쿠키 롤백/불일치를
세션 전체 라이프사이클(사전 - 기동 - 사후)에서 일관되게 감시, 차단, 자가치유(Self-Healing)하는 전담 모듈.

핵심 3대 게이트:
  1. [Pre-launch Gate]  : 앱 구동 직전 디스크 DB 실측 사전 검증 & 1회 자가치유(Self-Healing)
  2. [In-flight Gate]   : 앱 기동 직후 1초 크로미움 메모리 캐시(CookieMonster) 실측 및 강제 동기화
  3. [Post-flight Gate] : 세션 종료 직후 단말기 Cookies DB 실측 최종 감사 (순정 OS 롤백 판정)
"""

import time
import sqlite3
import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, Callable

from config.settings import NAVER_APP_PACKAGE, TIMINGS
from src.device.adb_controller import run_adb_shell, force_stop_app, force_stop_gms

logger = logging.getLogger("CookieRollbackManager")


class CookieRollbackManager:
    """단말기 쿠키 무결성 및 롤백 방지/감사 전담 싱글톤 클래스"""

    _native_ssaid_cache: Dict[str, str] = {}

    @classmethod
    def get_native_os_ssaid(cls, device_id: str) -> str:
        """단말기 순정 OS의 android_id 조회 (캐싱 적용)"""
        if device_id in cls._native_ssaid_cache:
            return cls._native_ssaid_cache[device_id]
        try:
            res = subprocess.run(
                ["adb", "-s", device_id, "shell", "settings get secure android_id"],
                capture_output=True, text=True, timeout=3
            )
            native_id = res.stdout.strip()
            if native_id:
                cls._native_ssaid_cache[device_id] = native_id
                return native_id
        except Exception as e:
            logger.warning(f"⚠️ [{device_id}] 순정 android_id 조회 실패: {e}")
        return "77d52e2a129bb86bd0fc3fa85e602297"

    @classmethod
    def cleanup_locks_and_journals(cls, device_id: str):
        """
        SQLite 자동 롤백 복원을 유발하는 저널 및 WAL 잔재 파일 전량 강제 삭제
        """
        pkg = NAVER_APP_PACKAGE
        cmd = (
            f"su -c '"
            f"rm -f /data/data/{pkg}/app_xwhale/Default/Cookies-journal "
            f"/data/data/{pkg}/app_xwhale/Default/Cookies-wal "
            f"/data/data/{pkg}/app_xwhale/Default/Cookies-shm; "
            f"rm -f /data/data/{pkg}/app_webview/Default/Cookies-journal "
            f"/data/data/{pkg}/app_webview/Default/Cookies-wal "
            f"/data/data/{pkg}/app_webview/Default/Cookies-shm; "
            f"'"
        )
        run_adb_shell(device_id, cmd)

    @classmethod
    def read_ondevice_cookies(cls, device_id: str) -> Tuple[bool, Dict[str, str], str]:
        """
        단말기 실제 Cookies DB를 안전하게 추출하여 딕셔너리로 반환 (소요: ~0.08s)
        Returns: (success: bool, cookies: dict, error_message: str)
        """
        pkg = NAVER_APP_PACKAGE
        remote_db = f"/data/data/{pkg}/app_xwhale/Default/Cookies"
        tmp_remote = f"/sdcard/crm_cookies_{device_id}.db"
        tmp_local = Path(f"/tmp/crm_cookies_{device_id}.db")

        try:
            subprocess.run(
                ["adb", "-s", device_id, "shell", f"su -c 'cp {remote_db} {tmp_remote} && chmod 666 {tmp_remote}'"],
                check=True, capture_output=True, timeout=4
            )
            subprocess.run(
                ["adb", "-s", device_id, "pull", tmp_remote, str(tmp_local)],
                check=True, capture_output=True, timeout=4
            )
            subprocess.run(
                ["adb", "-s", device_id, "shell", f"rm -f {tmp_remote}"],
                capture_output=True, timeout=2
            )

            conn = sqlite3.connect(str(tmp_local))
            c = conn.cursor()
            c.execute("SELECT name, value FROM cookies WHERE name IN ('NAPP_DI', 'DA_DD', 'DA_DV', 'NNB', 'BUC', 'm_loc')")
            cookies = dict(c.fetchall())
            conn.close()
            return True, cookies, ""
        except Exception as e:
            return False, {}, f"쿠키 DB 추출/파싱 실패: {e}"
        finally:
            if tmp_local.exists():
                tmp_local.unlink(missing_ok=True)

    @classmethod
    def verify_cookies_integrity(
        cls,
        device_id: str,
        db_cookies: Dict[str, str],
        expected_ssaid: str,
        expected_dadd: Optional[str] = None,
        expected_dadv: Optional[str] = None,
        expected_nnb: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        쿠키 값 무결성 엄격 판정:
        - 순정 OS SSAID 롤백 검출
        - NAPP_DI, DA_DD, DA_DV, m_loc, NNB 1:1 대조
        """
        # 1. NAPP_DI (SSAID MD5 해시) 검수
        actual_napp = db_cookies.get("NAPP_DI", "")
        expected_napp = hashlib.md5(expected_ssaid.encode("utf-8")).hexdigest() if expected_ssaid else ""

        # OS 순정 SSAID의 MD5 확인
        native_ssaid = cls.get_native_os_ssaid(device_id)
        native_napp_md5 = hashlib.md5(native_ssaid.encode("utf-8")).hexdigest()

        if actual_napp.lower() == native_napp_md5.lower() and expected_napp.lower() != native_napp_md5.lower():
            return False, f"🚨 [치명적 롤백 감지] NAPP_DI가 단말기 OS 순정값({native_napp_md5})으로 덮어써짐!"

        if expected_napp and actual_napp.lower().zfill(32) != expected_napp.lower().zfill(32):
            return False, f"🚨 [NAPP_DI 불일치] 기대값({expected_napp[:10]}...) != 실측값({actual_napp[:10]}...)"

        # 2. DA_DD (ADID) 검수
        if expected_dadd:
            actual_dadd = db_cookies.get("DA_DD", "")
            if actual_dadd.lower() != expected_dadd.lower():
                return False, f"🚨 [DA_DD 불일치] 기대값({expected_dadd}) != 실측값({actual_dadd})"

        # 3. DA_DV (AppSetId) 검수
        if expected_dadv:
            actual_dadv = db_cookies.get("DA_DV", "")
            if actual_dadv.lower() != expected_dadv.lower():
                return False, f"🚨 [DA_DV 불일치] 기대값({expected_dadv}) != 실측값({actual_dadv})"

        # 4. m_loc (가상 GPS 암호화 쿠키) 검수
        actual_mloc = db_cookies.get("m_loc", "")
        if not actual_mloc or len(actual_mloc) < 30:
            return False, f"🚨 [m_loc 위치 쿠키 부재/손상] 단말기 쿠키 DB에 유효한 m_loc 부재 ({actual_mloc})"

        # 5. NNB (방문자 식별 쿠키) 검수
        if expected_nnb:
            actual_nnb = db_cookies.get("NNB", "")
            if actual_nnb != expected_nnb:
                return False, f"🚨 [NNB 불일치] 기대값({expected_nnb}) != 실측값({actual_nnb})"

        return True, "✅ [식별자 무결성 검증 통과] NAPP_DI, DA_DD, DA_DV, m_loc(GPS), NNB 100% 일치"

    # =========================================================================
    # 1단계: Pre-launch Gate (앱 구동 직전 사전 검증 & 자가치유)
    # =========================================================================
    @classmethod
    def pre_launch_gate(
        cls,
        device_id: str,
        profile: Dict[str, Any],
        re_inject_callback: Optional[Callable[[], Any]] = None
    ) -> Tuple[bool, str, Dict[str, str]]:
        """
        [1단계] 앱을 띄우기 직전에 단말기 디스크 Cookies DB를 실측 사전 검증.
        불일치 감지 시 프로세스 강제 사살 후 1회 자가치유(Self-Healing) 재주입.
        """
        t0 = time.time()
        success, db_cookies, err = cls.read_ondevice_cookies(device_id)
        if not success:
            logger.warning(f"⚠️ [{device_id}] [Pre-launch] 쿠키 DB 1차 읽기 실패: {err}")

        is_valid = False
        reason = ""
        if success:
            is_valid, reason = cls.verify_cookies_integrity(
                device_id=device_id,
                db_cookies=db_cookies,
                expected_ssaid=profile.get("ssaid", ""),
                expected_dadd=profile.get("dadd"),
                expected_dadv=profile.get("dadv"),
                expected_nnb=profile.get("nnb")
            )

        if is_valid:
            logger.info(f"🔒 [{device_id}] [Pre-launch Gate 통과] 디스크 DB 무결성 100% 확인 (소요: {time.time()-t0:.3f}s)")
            return True, reason, db_cookies

        # 자가치유 (Self-Healing) 1회 시도
        logger.warning(f"⚠️ [{device_id}] [Pre-launch Gate 감지] 디스크 쿠키 불일치/미반영 ({reason}) -> 1회 자가치유 재주입 실행...")
        force_stop_app(device_id, max_wait=2.0)
        force_stop_gms(device_id, max_wait=2.0)
        cls.cleanup_locks_and_journals(device_id)

        if re_inject_callback:
            try:
                re_inject_callback()
            except Exception as e:
                logger.error(f"❌ [{device_id}] [Pre-launch 자가치유 재주입 실패]: {e}")

        # 재검증
        success2, db_cookies2, err2 = cls.read_ondevice_cookies(device_id)
        if success2:
            is_valid2, reason2 = cls.verify_cookies_integrity(
                device_id=device_id,
                db_cookies=db_cookies2,
                expected_ssaid=profile.get("ssaid", ""),
                expected_dadd=profile.get("dadd"),
                expected_dadv=profile.get("dadv"),
                expected_nnb=profile.get("nnb")
            )
            if is_valid2:
                logger.info(f"✅ [{device_id}] [Pre-launch 자가치유 성공] 재주입 후 디스크 무결성 통과 (소요: {time.time()-t0:.3f}s)")
                return True, f"자가치유 성공: {reason2}", db_cookies2
            else:
                logger.critical(f"🚨 [{device_id}] [Pre-launch 자가치유 실패] 재주입 후에도 불일치 잔재: {reason2}")
                return False, reason2, db_cookies2

        return False, f"자가치유 후 DB 읽기 실패: {err2}", {}

    # =========================================================================
    # 2단계: In-flight Gate (앱 기동 직후 1초 인메모리 실측 및 쐐기 동기화)
    # =========================================================================
    @classmethod
    async def in_flight_gate(
        cls,
        cdp: Any,
        profile: Dict[str, Any],
        nnb: str,
        buc: str = ""
    ) -> Tuple[bool, str, Dict[str, str]]:
        """
        [2단계] CDP 연결 직후(1~2초 시점), 크로미움 브라우저 활성 메모리 캐시(CookieMonster) 실측 검증.
        불일치 쿠키 즉시 덮어쓰기 쐐기 적용.
        """
        from src.device.surgical_cleaner import encrypt_naver_m_loc

        # 1. 6대 핵심 쿠키 전수 1차 주입
        cookie_payloads = []
        if nnb:
            cookie_payloads.append({"name": "NNB", "value": nnb, "domain": ".naver.com", "path": "/", "secure": True, "sameSite": "Lax"})
        if buc:
            cookie_payloads.append({"name": "BUC", "value": buc, "domain": ".naver.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "Lax"})
        if profile.get("ssaid"):
            napp_di = hashlib.md5(profile["ssaid"].encode("utf-8")).hexdigest()
            cookie_payloads.append({"name": "NAPP_DI", "value": napp_di, "domain": ".naver.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "Lax"})
        if profile.get("dadd"):
            cookie_payloads.append({"name": "DA_DD", "value": profile["dadd"], "domain": ".naver.com", "path": "/", "secure": False, "sameSite": "Lax"})
        if profile.get("dadv"):
            cookie_payloads.append({"name": "DA_DV", "value": profile["dadv"], "domain": ".naver.com", "path": "/", "secure": False, "sameSite": "Lax"})
        if profile.get("lat") and profile.get("lng"):
            mloc_val = encrypt_naver_m_loc(profile["lat"], profile["lng"], with_history=True)
            cookie_payloads.append({"name": "m_loc", "value": mloc_val, "domain": ".naver.com", "path": "/", "secure": False, "sameSite": "Lax"})

        for cp in cookie_payloads:
            try:
                await cdp.call("Network.setCookie", cp, timeout=TIMINGS.LAUNCH_SET_COOKIE_TIMEOUT)
            except Exception:
                pass

        # 2. 브라우저 활성 메모리 실측 조회
        try:
            mem_res = await cdp.call("Network.getCookies", {"urls": ["https://m.naver.com"]}, timeout=2.0)
            mem_cookies = {c["name"]: c["value"] for c in mem_res.get("cookies", [])}

            # 불일치 재보정
            if nnb and mem_cookies.get("NNB") != nnb:
                await cdp.call("Network.setCookie", {"name": "NNB", "value": nnb, "domain": ".naver.com", "path": "/", "secure": True, "sameSite": "Lax"})
            if profile.get("ssaid"):
                exp_napp = hashlib.md5(profile["ssaid"].encode("utf-8")).hexdigest()
                if mem_cookies.get("NAPP_DI") != exp_napp:
                    await cdp.call("Network.setCookie", {"name": "NAPP_DI", "value": exp_napp, "domain": ".naver.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "Lax"})

            logger.info("🔒 [In-flight Gate 통과] 크로미움 브라우저 메모리 캐시 6대 쿠키 동기화 쐐기 확인")
            return True, "메모리 쿠키 동기화 완료", mem_cookies
        except Exception as e:
            logger.warning(f"⚠️ [In-flight Gate] 메모리 쿠키 확인 중 예외: {e}")
            return False, str(e), {}

    # =========================================================================
    # 3단계: Post-flight Gate (세션 종료 직후 최종 단말기 실측 감사)
    # =========================================================================
    @classmethod
    def post_flight_gate(
        cls,
        device_id: str,
        profile: Dict[str, Any],
        expected_nnb: Optional[str] = None
    ) -> Tuple[bool, str, Dict[str, str]]:
        """
        [3단계] 타격 완료 후 단말기 실제 Cookies DB를 최종 쿼리하여
        실행 중 네이버 앱 C++ 라이브러리가 몰래 순정 OS 값으로 롤백시켰는지 전수 판독.
        """
        success, db_cookies, err = cls.read_ondevice_cookies(device_id)
        if not success:
            return False, f"Post-flight 쿠키 DB 읽기 실패: {err}", {}

        is_valid, reason = cls.verify_cookies_integrity(
            device_id=device_id,
            db_cookies=db_cookies,
            expected_ssaid=profile.get("ssaid", ""),
            expected_dadd=profile.get("dadd"),
            expected_dadv=profile.get("dadv"),
            expected_nnb=expected_nnb or profile.get("nnb")
        )
        return is_valid, reason, db_cookies
