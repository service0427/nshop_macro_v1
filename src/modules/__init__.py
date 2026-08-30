# -*- coding: utf-8 -*-
"""
========================================================================================
N-Shop Automation Macro Core Modules Package (v2.0 Zero-Reboot Architecture)
========================================================================================
1. ZeroRebootMutator  : 재부팅 없는 2초 신원 변조, 7종 권한 자동 승인, 14종 온보딩 스킵
2. TaskApiClient      : 중앙 관제 서버 작업 할당(GET) & 결과 반환(POST /release)
3. WireGuardManager   : 3초 초고속 WireGuard 터널링 주입 및 3단계 무결성 검증
4. SearchAction       : 네이버 앱 메인 렌더링 확인 및 키워드 다이렉트 검색
5. ProductClicker     : nvMid 기반 순수 XML 구조 타겟 포착, 순위 측정 및 클릭
========================================================================================
"""

from .macro_core import NaverMacroCore
from .zero_reboot_mutator import ZeroRebootMutator
from .wireguard_manager import WireGuardManager
from .task_api_client import TaskApiClient

__all__ = [
    "NaverMacroCore",
    "ZeroRebootMutator",
    "WireGuardManager",
    "TaskApiClient",
]
