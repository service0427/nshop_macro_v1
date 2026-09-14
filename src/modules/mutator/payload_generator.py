#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
[모듈명] 신원 및 설정 XML 페이로드 생성기 (PayloadGenerator)
========================================================================================
- 기능:
    1. settings_ssaid.xml XML 생성
    2. GMS adid_settings.xml XML 생성
    3. 네이버 앱 온보딩/튜토리얼 스킵 및 버전/설치일자 null.xml 생성
    4. tutorial_pref.xml 및 nlog_pref.xml 페이로드 생성

----------------------------------------------------------------------------------------
[수정 및 변경 이력 (Revision History)]
----------------------------------------------------------------------------------------
- 2026-09-05:
    * [코드 가독성 및 들여쓰기 정제] textwrap.dedent()를 전면 적용하여
      메서드 내부 들여쓰기 구조를 깔끔하게 통일하고 좌측 벽 붙이기(0-column) 제거.
========================================================================================
"""

import random
import struct
from textwrap import dedent
from typing import Tuple


class PayloadGenerator:
    """네이버 앱 및 안드로이드 시스템 식별자 XML 템플릿 빌더"""

    @staticmethod
    def generate_ssaid_payload(package_name: str, ssaid: str) -> str:
        """안드로이드 SSAID(Android ID) 시스템 XML 페이로드 생성"""
        return dedent(f"""\
            <?xml version='1.0' encoding='utf-8' standalone='yes' ?>
            <packages>
                <package name="{package_name}" value="{ssaid}" />
            </packages>
        """).strip()

    @staticmethod
    def generate_adid_payload(adid: str) -> str:
        """구글 GMS 광고 식별자(ADID) XML 페이로드 생성"""
        return dedent(f"""\
            <?xml version='1.0' encoding='utf-8' standalone='yes' ?>
            <map>
                <string name="adid_key">{adid}</string>
                <boolean name="enable_limit_ad_tracking" value="false" />
            </map>
        """).strip()

    @staticmethod
    def generate_ads_flags_payload(nas_user_id: str) -> str:
        """네이버 광고 시스템 식별자(NAS_USER_ID) com.naver.ads.flags.xml 페이로드 생성"""
        return dedent(f"""\
            <?xml version='1.0' encoding='utf-8' standalone='yes' ?>
            <map>
                <string name="com.naver.ads.NAS_USER_ID">{nas_user_id}</string>
            </map>
        """).strip()

    @staticmethod
    def generate_null_prefs_payload(
        install_ts: int,
        update_ts: int,
        app_version: str = "12.23.1",
        app_version_code: int = 12230102
    ) -> str:
        """네이버 앱 온보딩/권한 동의/튜토리얼 스킵 및 버전/설치일자 null.xml 생성"""
        return dedent(f"""\
            <?xml version='1.0' encoding='utf-8' standalone='yes' ?>
            <map>
                <boolean name="keyFirstRun" value="false" />
                <boolean name="keyUniverseTutorialComplete" value="true" />
                <boolean name="keyNextTutorialComplete" value="true" />
                <boolean name="keyTutorialLocProcessed" value="true" />
                <boolean name="keyDarkTutorialComplete" value="true" />
                <boolean name="keyNewmainTutorialComplete" value="true" />
                <boolean name="keyNotificationQuery" value="true" />
                <boolean name="keyLocationAgree" value="false" />
                <boolean name="keyLocationUserAgreementAccepted" value="false" />
                <boolean name="keyUniverseMigrationFinished" value="true" />
                <boolean name="keyMyTabMigrationFinished" value="true" />
                <boolean name="keyLocalSiteMigrated" value="true" />
                <boolean name="keyXWhaleMigrated" value="true" />
                <boolean name="keyMigrateInAppStrorage" value="true" />
                <boolean name="keyWebEngineBuiltInV10" value="true" />
                <boolean name="keySecureScreenShot" value="true" />
                <boolean name="keyActiveAppCheck" value="false" />
                <boolean name="keyBridgeLinkInAppToolbar" value="true" />
                <string name="KeyPrevNClicks">hct.locok2</string>
                <string name="KeyLastNClicks">hct.complete</string>
                <string name="keyNativeHomeAreaCode">home</string>
                <boolean name="keyShowNewMainTutorial" value="true" />
                <boolean name="keyDtsStandAlone" value="true" />
                <boolean name="keyShouldShowPayRedDotAtFirst" value="false" />
                <boolean name="keyNaverWebEngineV2" value="true" />
                <int name="keyRefreshInterval" value="600" />
                <long name="nlog_init_ts" value="{install_ts}" />
                <long name="keyInstallDate" value="{install_ts}" />
                <long name="keyUpdateDate" value="{update_ts}" />
                <string name="keyAppVersion">{app_version}</string>
                <int name="keyAppVersionCode" value="{app_version_code}" />
            </map>
        """).strip()

    @staticmethod
    def generate_tutorial_payload() -> str:
        """튜토리얼 스킵 tutorial_pref.xml 페이로드 생성"""
        return dedent("""\
            <?xml version='1.0' encoding='utf-8' standalone='yes' ?>
            <map>
                <boolean name="tutorial_shown" value="true" />
                <boolean name="is_first_launch" value="false" />
            </map>
        """).strip()

    @staticmethod
    def generate_nlog_pref_payload(install_ts: int, app_version: str = "12.23.1") -> str:
        """네이버 NLog 로그 초기화 타임스탬프 nlog_pref.xml 페이로드 생성"""
        return dedent(f"""\
            <?xml version='1.0' encoding='utf-8' standalone='yes' ?>
            <map>
                <long name="nlog_init_ts" value="{install_ts}" />
                <long name="nlog_install_ts" value="{install_ts}" />
                <string name="nlog_app_ver">{app_version}</string>
            </map>
        """).strip()

    @staticmethod
    def generate_ntracker_payload(
        install_ts: int,
        app_version: str = "12.23.1",
        os_version: str = "13"
    ) -> str:
        """네이버 NTracker의 Google Play Install Referrer 캐시 프리시딩 페이로드 생성"""
        install_time_sec = install_ts // 1000
        fetch_time_ms = install_ts + random.randint(1000, 5000)
        return dedent(f"""\
            <?xml version='1.0' encoding='utf-8' standalone='yes' ?>
            <map>
                <string name="NTracker_InstallReferrer_URL">utm_source=google-play&amp;utm_medium=organic</string>
                <string name="NTracker_Previous_OS_Version">{os_version}</string>
                <string name="NTracker_Previous_App_Version">{app_version}</string>
                <long name="NTracker_InstallReferrer_Click_Time" value="0" />
                <long name="NTracker_FirstOpenTime" value="{install_ts}" />
                <long name="NTracker_InstallReferrer_Install_Time" value="{install_time_sec}" />
                <long name="NTracker_InstallReferrer_FetchTime" value="{fetch_time_ms}" />
            </map>
        """).strip()

    @staticmethod
    def generate_profileinstaller_payloads(update_ts: int) -> Tuple[bytes, bytes]:
        """안드로이드 ART profileinstaller 바이너리 파일 페이로드 생성 (update_ts 기반)"""
        lut_data = struct.pack(">Q", update_ts)
        inst_data = struct.pack(">IIQQ", 1, 2, update_ts, 69469)
        return lut_data, inst_data
