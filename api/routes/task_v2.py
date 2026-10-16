#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api/routes/task_v2.py

Next-Generation Task Routing (v2):
- /api/v2/task/allocate : Intelligent 5-gate batch allocation (Quota & Keyword Pool)
- /api/v2/task/report   : Zero-SSH remote telemetry and checkpoint reporting
- /api/v2/task/diagnostics : Remote failure telemetry summary
- /api/v2/products/unique : Unique products and slot quota status
- /api/v2/admin/init-tables : Schema initialization
- /api/v2/admin/migrate-from-nshop-list : Seed unique products and virtual slots
- /api/v2/node/heartbeat: Distributed worker node heartbeat and fleet sync
"""

import time
from flask import Blueprint, request, jsonify
from services.task_service_v2 import TaskServiceV2

task_v2_bp = Blueprint("task_v2", __name__, url_prefix="/api/v2/task")
node_v2_bp = Blueprint("node_v2", __name__, url_prefix="/api/v2/node")
admin_v2_bp = Blueprint("admin_v2", __name__, url_prefix="/api/v2/admin")
product_v2_bp = Blueprint("product_v2", __name__, url_prefix="/api/v2/products")
device_v2_bp = Blueprint("device_v2", __name__, url_prefix="/api/v2/devices")
group_v2_bp = Blueprint("group_v2", __name__, url_prefix="/api/v2/groups")


@task_v2_bp.route("/allocate", methods=["POST"])
def allocate_tasks_v2():
    """
    [지능형 5단계 작업 할당 v2 API]
    - 일일 쿼터(최대 100타), 스토어 80분 쿨다운, WG C클래스 격리, 1~5순위 키워드 풀 연동, 1:1 고유 상품 매칭
    """
    data = request.get_json(silent=True) or {}
    try:
        result = TaskServiceV2.allocate(data)
        status_code = 200 if result.get("success") else 404
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@task_v2_bp.route("/report", methods=["POST"])
def report_task_v2():
    """
    [원격 정밀 진단 및 체크포인트 보고 v2 API]
    - failed_phase, error_code, checkpoints, telemetry 수신, 쿼터 카운터 갱신 및 자가치유 피드백 반환
    """
    data = request.get_json(silent=True) or {}
    try:
        result = TaskServiceV2.report(data)
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@task_v2_bp.route("/diagnostics", methods=["GET"])
def get_diagnostics_v2():
    """
    [원격 관제용 정밀 진단 요약 조회 API]
    """
    try:
        limit = int(request.args.get("limit", 50))
    except (ValueError, TypeError):
        limit = 50
    try:
        result = TaskServiceV2.get_diagnostics(limit=limit)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@product_v2_bp.route("/unique", methods=["GET"])
def get_unique_products_v2():
    """
    [유니크 상품 목록 및 슬롯/쿼터 현황 조회 API]
    """
    try:
        limit = int(request.args.get("limit", 50))
    except (ValueError, TypeError):
        limit = 50
    try:
        result = TaskServiceV2.get_unique_products(limit=limit)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@product_v2_bp.route("/sync-external", methods=["POST"])
def sync_external_products_v2():
    """
    [5분 주기 외부 10개 제휴 사이트 슬롯 동기화 API]
    """
    data = request.get_json(silent=True) or {}
    try:
        result = TaskServiceV2.sync_external_products(data)
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


quota_v2_bp = Blueprint("quota_v2", __name__, url_prefix="/api/v2/quotas")


@quota_v2_bp.route("/daily", methods=["GET"])
def get_daily_quotas_v2():
    """
    [일자별 슬롯 쿼터 및 달성 현황 조회 API]
    GET /api/v2/quotas/daily?date=YYYY-MM-DD
    """
    date_param = request.args.get("date")
    try:
        result = TaskServiceV2.get_daily_quotas(target_date=date_param)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


sim_v2_bp = Blueprint("sim_v2", __name__, url_prefix="/api/v2/simulation")


@sim_v2_bp.route("/run-day", methods=["POST"])
def run_simulation_day_v2():
    """
    [일자별 다일 시뮬레이션 가동 API]
    POST /api/v2/simulation/run-day
    """
    data = request.get_json(silent=True) or {}
    try:
        result = TaskServiceV2.simulate_day(data)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@admin_v2_bp.route("/init-tables", methods=["POST"])
def init_tables_v2():
    """
    [v2 신규 테이블 스키마 초기화 API]
    """
    try:
        result = TaskServiceV2.init_tables()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@admin_v2_bp.route("/migrate-from-nshop-list", methods=["POST"])
def migrate_from_nshop_list_v2():
    """
    [nshop_list -> 유니크 상품 및 10개 가상 사이트 슬롯 자동 이관 API]
    """
    try:
        result = TaskServiceV2.migrate_from_nshop_list()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@admin_v2_bp.route("/inspect-tables", methods=["GET"])
def inspect_tables_v2():
    """
    [DB 테이블 및 스키마 정밀 진단 API]
    """
    try:
        result = TaskServiceV2.inspect_tables()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@admin_v2_bp.route("/enrich-from-nshop-list", methods=["POST"])
def enrich_from_nshop_list_v2():
    """
    [_nshop_list 실제 데이터 기반 target_products 보강 API]
    """
    options = request.get_json(silent=True) or {}
    try:
        result = TaskServiceV2.enrich_from_underscore_nshop_list(options)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@admin_v2_bp.route("/refresh-keywords", methods=["POST", "GET"])
def refresh_keywords_v2():
    """
    [전체 상품 실물 제목 기반 5개 마디 키워드 풀 일괄 재생성 API]
    - '추천' 등 인위적 단어 전면 제거
    - 100% 제목 마디 슬라이스로 5개 순수 조합 생성 및 롤링 가중치(30/25/20/15/10) 반영
    """
    try:
        result = TaskServiceV2.refresh_all_product_keywords()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@admin_v2_bp.route("/replace-targets", methods=["POST"])
def replace_targets_v2():
    """
    [nshop_list 및 관련 v2 테이블 전체 초기화 및 신규 50개 상품 일괄 교체 API]
    """
    data = request.get_json(silent=True) or {}
    try:
        targets = data.get("targets", [])
        if not targets:
            return jsonify({"success": False, "error": "targets 목록이 비어있습니다."}), 400
        options = data.get("options", {})
        result = TaskServiceV2.reset_and_replace_targets(targets, options)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# 노드 캐시 보관용
_NODE_HEARTBEATS = {}

@node_v2_bp.route("/heartbeat", methods=["POST"])
def node_heartbeat_v2():
    """
    [분산 워커 노드 헬스체크 v2 API]
    """
    data = request.get_json(silent=True) or {}
    node_id = str(data.get("node_id") or request.remote_addr).strip()
    data["last_seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    data["client_ip"] = request.remote_addr
    _NODE_HEARTBEATS[node_id] = data

    return jsonify({
        "success": True,
        "node_id": node_id,
        "registered_at": data["last_seen_at"],
        "message": "Node heartbeat recorded successfully"
    }), 200


@node_v2_bp.route("/fleet", methods=["GET"])
def get_fleet_v2():
    """
    [분산 워커 노드 전체 현황 조회 API]
    """
    return jsonify({
        "success": True,
        "total_nodes": len(_NODE_HEARTBEATS),
        "nodes": list(_NODE_HEARTBEATS.values())
    }), 200


# =============================================================================
# 디바이스 관리 및 그룹 분할 API (Device Master & Group Routing)
# =============================================================================

@device_v2_bp.route("", methods=["GET"])
def list_devices_v2():
    """
    [전체 디바이스 목록 및 당일 실적 현황 조회 API]
    GET /api/v2/devices?date=YYYY-MM-DD
    """
    target_date = request.args.get("date")
    try:
        result = TaskServiceV2.get_devices(target_date=target_date)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@device_v2_bp.route("/<device_id>/group", methods=["POST"])
def update_device_group_v2(device_id: str):
    """
    [단말기 소속 그룹 변경 API]
    POST /api/v2/devices/{device_id}/group
    Payload: {"group_name": "COMPANY_A"}
    """
    data = request.get_json(silent=True) or {}
    group_name = data.get("group_name") or "DEFAULT"
    try:
        result = TaskServiceV2.update_device_group(device_id=device_id, group_name=group_name)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@device_v2_bp.route("/<device_id>/logs", methods=["GET"])
def get_device_logs_v2(device_id: str):
    """
    [단말기 최근 상세 실행 로그 조회 API]
    GET /api/v2/devices/{device_id}/logs?limit=50
    """
    try:
        limit = int(request.args.get("limit", 50))
    except (ValueError, TypeError):
        limit = 50
    try:
        result = TaskServiceV2.get_device_logs(device_id=device_id, limit=limit)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@device_v2_bp.route("/stats", methods=["GET"])
def get_device_daily_stats_v2():
    """
    [전체 단말기 일자별 성적 및 통계표 조회 API]
    GET /api/v2/devices/stats?date=YYYY-MM-DD
    """
    stat_date = request.args.get("date")
    try:
        result = TaskServiceV2.get_daily_device_stats(stat_date=stat_date)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# 그룹 및 사이트 묶음 관리 API (Group & Site Binding Routing)
# =============================================================================

@group_v2_bp.route("", methods=["GET"])
def list_groups_v2():
    """
    [전체 그룹 목록 및 각 그룹에 묶인 사이트 목록 조회 API]
    GET /api/v2/groups
    """
    try:
        result = TaskServiceV2.get_groups()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@group_v2_bp.route("", methods=["POST"])
def create_group_v2():
    """
    [그룹 생성 및 1개 이상의 사이트 묶음 등록/수정 API]
    POST /api/v2/groups
    Payload: {
        "group_code": "GROUP_A",
        "group_name": "A사 전용 단말군",
        "description": "agency_alpha 및 beta 묶음",
        "is_all_sites": false,
        "site_codes": ["agency_alpha", "agency_beta"]
    }
    """
    data = request.get_json(silent=True) or {}
    group_code = data.get("group_code")
    group_name = data.get("group_name")
    description = data.get("description", "")
    is_all_sites = bool(data.get("is_all_sites", False))
    site_codes = data.get("site_codes")
    try:
        result = TaskServiceV2.create_or_update_group(
            group_code=group_code,
            group_name=group_name,
            description=description,
            is_all_sites=is_all_sites,
            site_codes=site_codes
        )
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@group_v2_bp.route("/<group_code>", methods=["DELETE"])
def delete_group_v2(group_code: str):
    """
    [그룹 삭제 API (소속 단말기는 DEFAULT로 복귀)]
    DELETE /api/v2/groups/{group_code}
    """
    try:
        result = TaskServiceV2.delete_group(group_code=group_code)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
