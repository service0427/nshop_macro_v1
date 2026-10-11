from flask import Blueprint, request, jsonify
from services.task_service import TaskService
from config import MIN_AGING_SECONDS

task_bp = Blueprint("task", __name__, url_prefix="/api/v1/task")

@task_bp.route("/assign", methods=["GET", "POST"])
def assign_task():
    """
    [작업 할당 API]
    - 20분(1200초) 이상 숙성된 nnb, buc 선점
    - nshop_list 에서 keyword(product_name), nv_mid(target_id), compare_id(mall_product_id) 랜덤 매칭
    - DB tasks 테이블에 task_id와 함께 자동 기록
    - 심플한 핵심 데이터 반환
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args.to_dict()

    raw_id = data.get("task_id") if data.get("task_id") is not None else data.get("id")
    if raw_id is not None and str(raw_id).strip() != "":
        try:
            task_id = int(raw_id)
        except ValueError:
            return jsonify({"success": False, "error": "task_id (또는 id)는 숫자(정수)여야 합니다."}), 400
    else:
        task_id = None

    min_age_seconds = data.get("min_age_seconds")
    if min_age_seconds is not None:
        try:
            min_age_seconds = max(1200, int(min_age_seconds))
        except ValueError:
            return jsonify({"success": False, "error": "min_age_seconds는 정수여야 합니다."}), 400
    else:
        min_age_seconds = 1200

    device_id = data.get("device_id")
    ip = data.get("ip") or request.headers.get("X-Forwarded-For", request.remote_addr)
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()
    nv_mid = data.get("nv_mid") or data.get("target_id")

    try:
        result = TaskService.assign_task(
            task_id=task_id,
            min_age_seconds=min_age_seconds,
            device_id=device_id,
            ip=ip,
            specific_nv_mid=nv_mid
        )
        status_code = 200 if result.get("success") else 404
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@task_bp.route("/complete", methods=["POST"])
@task_bp.route("/report", methods=["POST"])
def complete_task():
    """
    [작업 완료/결과 보고 API]
    - search_type ("m.search" 또는 "msearch")
    - serp_rank, shopping_rank, shopping_page, match_type, login_detected, duration_seconds 등 실시간 기록
    """
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    if not task_id:
        return jsonify({"success": False, "error": "task_id는 필수입니다."}), 400

    try:
        task_id = int(task_id)
    except ValueError:
        return jsonify({"success": False, "error": "task_id는 정수여야 합니다."}), 400

    try:
        res = TaskService.complete_task(task_id=task_id, payload=data)
        status_code = 200 if res.get("success") else 404
        return jsonify(res), status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@task_bp.route("/report", methods=["GET"])
def get_report():
    """특정 작업의 상세 보고 결과 조회"""
    task_id = request.args.get("task_id")
    if not task_id:
        return jsonify({"success": False, "error": "task_id 쿼리 파라미터가 필요합니다."}), 400

    try:
        task_id = int(task_id)
    except ValueError:
        return jsonify({"success": False, "error": "task_id는 정수여야 합니다."}), 400

    try:
        report = TaskService.get_task_report(task_id=task_id)
        if report:
            return jsonify({"success": True, "data": report}), 200
        else:
            return jsonify({"success": False, "message": f"task_id({task_id})에 해당하는 보고서를 찾을 수 없습니다."}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@task_bp.route("/history", methods=["GET"])
def task_history():
    """최근 작업 할당 이력 조회 (모니터링용)"""
    limit = min(max(int(request.args.get("limit", 30)), 1), 100)
    try:
        history = TaskService.get_task_history(limit=limit)
        return jsonify({"success": True, "count": len(history), "items": history}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
