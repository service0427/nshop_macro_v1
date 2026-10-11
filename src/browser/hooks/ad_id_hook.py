#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/browser/hooks/ad_id_hook.py

[레거시 호환 래퍼 모듈] Google ADID / AppSetId 훅 브릿지
- 목적: 과거 ad_id_hook 단독 호출 레거시 코드와의 100% 하위 호환성(Backward Compatibility) 유지
- 실체: 모든 구글 계정 및 광고/앱 식별자 가로채기 로직은 `google_identity_hook.py`로 일원화 통합됨
- 우선순위: `__init__.py` 번들러에서 3순위로 기동 (AccountManager + AppSetId + ADID 동시 주입)
"""

from typing import Optional
from src.browser.hooks.google_identity_hook import build_google_identity_hook


def build_ad_id_hook(
    spoof_dadd: Optional[str] = None,
    spoof_dadv: Optional[str] = None,
    spoof_google_account: Optional[str] = None
) -> str:
    """
    하위 호환성을 유지하며 최신 pure GMS Core Root 모듈인 google_identity_hook으로 연결
    :param spoof_dadd: Google ADID (AdvertisingIdClient$Info / DA_DD)
    :param spoof_dadv: Google AppSetId (AppSetIdInfo / DA_DV / Scope 1)
    :param spoof_google_account: 가상 구글 계정 이메일 (AccountManager)
    :return: 결합된 Frida JS 훅 코드
    """
    return build_google_identity_hook(
        spoof_google_account=spoof_google_account,
        spoof_dadd=spoof_dadd,
        spoof_dadv=spoof_dadv
    )


__all__ = ["build_ad_id_hook"]
