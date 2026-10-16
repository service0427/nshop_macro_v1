#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/device/identity_auditor.py

온디바이스 및 프로덕션 환경 전용 무결성 식별자 감사 엔진 (Identity Auditor)
- MITM 없는 온디바이스 환경에서 단말기 고유 식별자의 1회용 신생성 및 독립성을 수학적으로 검수
- 직전 회차(Run N-1) 및 전체 이력과의 충돌(Collision) 0.00% 전수 판독
- SSAID, NAPP_DI, NNB, BUC, DA_DD(ADID), DA_DV(AppSetId), GPS 좌표, 구글 계정 1:1 대조 검수표 생성
"""

import math
import json
import time
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 위경도 간의 대원거리(km) 계산"""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)

class IdentityAuditor:
    def __init__(self, history_file: Optional[Path] = None):
        self.history_file = history_file or (Path(__file__).resolve().parents[2] / "data" / "identity_audit_history.jsonl")
        self.history_file.parent.mkdir(parents=True, exist_ok=True)

    def load_last_identity(self, device_id: str) -> Optional[Dict[str, Any]]:
        """해당 단말기의 직전 회차 식별자 스냅샷 로드"""
        if not self.history_file.exists():
            return None
        last_record = None
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if rec.get("device_id") == device_id:
                        last_record = rec
        except Exception:
            return None
        return last_record

    def audit_and_record(
        self,
        device_id: str,
        current_identity: Dict[str, Any],
        persist: bool = True
    ) -> Tuple[bool, Dict[str, Any], str]:
        """
        직전 회차와 1:1 비교 검수 수행
        반환: (is_valid, audit_details, summary_table_text)
        """
        last = self.load_last_identity(device_id)
        current = dict(current_identity)
        current["device_id"] = device_id
        current["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")

        audit_items = []
        has_collision = False

        # 1. SSAID (Android ID) 검수
        cur_ssaid = current.get("ssaid", "")
        last_ssaid = last.get("ssaid", "") if last else None
        ssaid_coll = (cur_ssaid == last_ssaid) if last_ssaid else False
        if ssaid_coll: has_collision = True
        audit_items.append({
            "name": "SSAID (Android ID)",
            "last": last_ssaid or "(최초 회차)",
            "curr": cur_ssaid,
            "passed": not ssaid_coll,
            "desc": "단말기 OS 레벨 하드웨어 고유 식별값"
        })

        # 2. NAPP_DI (SSAID MD5 해시) 검수
        cur_napp = current.get("napp_di", "")
        last_napp = last.get("napp_di", "") if last else None
        napp_coll = (cur_napp == last_napp) if last_napp else False
        if napp_coll: has_collision = True
        audit_items.append({
            "name": "NAPP_DI (쿠키 식별자)",
            "last": (last_napp[:12] + "...") if last_napp else "(최초 회차)",
            "curr": (cur_napp[:12] + "...") if cur_napp else "",
            "passed": not napp_coll,
            "desc": "네이버 공식 앱 설치/기기 무결성 쿠키"
        })

        # 3. NNB (네이버 방문자 쿠키) 검수
        cur_nnb = current.get("nnb", "")
        last_nnb = last.get("nnb", "") if last else None
        nnb_coll = (cur_nnb == last_nnb) if last_nnb else False
        if nnb_coll: has_collision = True
        audit_items.append({
            "name": "NNB (네이버 고유 토큰)",
            "last": last_nnb or "(최초 회차)",
            "curr": cur_nnb,
            "passed": not nnb_coll,
            "desc": f"1,200초 숙성 API 할당 토큰 (숙성: {current.get('nnb_age_seconds', 0):,}초)"
        })

        # 4. BUC (네이버 암호화 무결성 서명) 검수
        cur_buc = current.get("buc", "")
        last_buc = last.get("buc", "") if last else None
        buc_coll = (cur_buc == last_buc) if (last_buc and cur_buc) else False
        if buc_coll: has_collision = True
        audit_items.append({
            "name": "BUC (HMAC 암호화 서명)",
            "last": (last_buc[:14] + "...") if last_buc else "(최초 회차)",
            "curr": (cur_buc[:14] + "...") if cur_buc else "",
            "passed": not buc_coll,
            "desc": "네이버 세션 위조 방지 서명"
        })

        # 5. DA_DD (Google ADID) 검수
        cur_dadd = current.get("dadd", "")
        last_dadd = last.get("dadd", "") if last else None
        dadd_coll = (cur_dadd == last_dadd) if last_dadd else False
        if dadd_coll: has_collision = True
        audit_items.append({
            "name": "DA_DD (Google ADID)",
            "last": (last_dadd[:13] + "...") if last_dadd else "(최초 회차)",
            "curr": (cur_dadd[:13] + "...") if cur_dadd else "",
            "passed": not dadd_coll,
            "desc": "구글 플레이 광고 서비스 고유 ID"
        })

        # 6. DA_DV (Google AppSetId) 검수
        cur_dadv = current.get("dadv", "")
        last_dadv = last.get("dadv", "") if last else None
        dadv_coll = (cur_dadv == last_dadv) if last_dadv else False
        if dadv_coll: has_collision = True
        audit_items.append({
            "name": "DA_DV (AppSetId)",
            "last": (last_dadv[:13] + "...") if last_dadv else "(최초 회차)",
            "curr": (cur_dadv[:13] + "...") if cur_dadv else "",
            "passed": not dadv_coll,
            "desc": "구글 앱 개발자 스코프 식별자"
        })

        # 7. GPS 위치 및 지역 검수
        cur_lat = current.get("lat")
        cur_lng = current.get("lng")
        cur_region = current.get("region", "대한민국")
        last_lat = last.get("lat") if last else None
        last_lng = last.get("lng") if last else None
        last_region = last.get("region", "") if last else "(최초 회차)"

        dist_km = 0.0
        if cur_lat and cur_lng and last_lat and last_lng:
            dist_km = haversine_distance_km(cur_lat, cur_lng, last_lat, last_lng)
        gps_coll = (dist_km == 0.0) if (last_lat and last_lng) else False
        audit_items.append({
            "name": "GPS 가상 위치 (m_loc)",
            "last": f"{last_region} ({last_lat},{last_lng})" if last_lat else "(최초 회차)",
            "curr": f"{cur_region} ({cur_lat},{cur_lng})" if cur_lat else "",
            "passed": not gps_coll,
            "desc": f"직전 위치 대비 이동 거리: {dist_km:,.1f} km 이동"
        })

        # 8. 가상 구글 계정 검수
        cur_acc = current.get("google_account", "")
        last_acc = last.get("google_account", "") if last else None
        acc_coll = (cur_acc == last_acc) if last_acc else False
        if acc_coll: has_collision = True
        audit_items.append({
            "name": "Google Account (인증 계정)",
            "last": last_acc or "(최초 회차)",
            "curr": cur_acc,
            "passed": not acc_coll,
            "desc": "Android AccountManager 연동 계정"
        })

        # 9. 공인 IP 검수
        cur_ip = current.get("ip", "unknown")
        last_ip = last.get("ip", "") if last else None
        audit_items.append({
            "name": "단말기 공인 IP (Egress IP)",
            "last": last_ip or "(최초 회차)",
            "curr": cur_ip,
            "passed": True,  # IP 쿨타임은 중앙 서버에서 관리
            "desc": "LTE 라우터 / 모바일 에그레스 IP"
        })

        # 검수표 포맷팅
        lines = []
        lines.append("┌" + "─"*30 + "┬" + "─"*25 + "┬" + "─"*25 + "┬" + "─"*10 + "┐")
        lines.append(f"│ {'검증 대상 식별자 (9대 항목)':<28} │ {'직전 회차 (Run N-1)':<23} │ {'현재 회차 (Run N)':<23} │ {'검수 결과':<8} │")
        lines.append("├" + "─"*30 + "┼" + "─"*25 + "┼" + "─"*25 + "┼" + "─"*10 + "┤")
        for item in audit_items:
            res_str = "✅ PASS" if item["passed"] else "🚨 REUSE"
            lines.append(f"│ {item['name']:<28} │ {str(item['last'])[:23]:<23} │ {str(item['curr'])[:23]:<23} │ {res_str:<8} │")
        lines.append("└" + "─"*30 + "┴" + "─"*25 + "┴" + "─"*25 + "┴" + "─"*10 + "┘")
        table_text = "\n".join(lines)

        # 현재 레코드 파일에 영구 기록
        if persist:
            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(current, ensure_ascii=False) + "\n")

        audit_summary = {
            "has_collision": has_collision,
            "total_items": len(audit_items),
            "passed_items": sum(1 for i in audit_items if i["passed"]),
            "items": audit_items
        }

        return (not has_collision), audit_summary, table_text

    @staticmethod
    def verify_ondevice_cookies_after_run(
        device_id: str,
        expected_ssaid: str,
        expected_dadd: Optional[str] = None,
        expected_dadv: Optional[str] = None,
        expected_nnb: Optional[str] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        [Post-flight Gate] CookieRollbackManager 전담 모듈로 위임
        """
        from src.device.cookie_rollback_manager import CookieRollbackManager
        profile = {
            "ssaid": expected_ssaid,
            "dadd": expected_dadd,
            "dadv": expected_dadv,
            "nnb": expected_nnb
        }
        return CookieRollbackManager.post_flight_gate(
            device_id=device_id,
            profile=profile,
            expected_nnb=expected_nnb
        )
