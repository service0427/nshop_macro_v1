from flask import Blueprint, request, jsonify
from services.nnb_service import NNBService
from config import MIN_AGING_SECONDS, TARGET_NNB_POOL_SIZE

nnb_bp = Blueprint("nnb", __name__, url_prefix="/api/v1/nnb")

@nnb_bp.route("/harvest", methods=["POST"])
def harvest_packets():
    """
    [패킷 채굴] lcs.naver.com/m 초고속 패킷을 직접 호출하여 정품 NNB+BUC 발급 후 DB 저장
    Body: {"count": 1~100, "proxy": null, "device_id": null, "memo": null}
    """
    data = request.get_json(silent=True) or {}
    count = int(data.get("count", 1))
    proxy = data.get("proxy")
    device_id = data.get("device_id")
    memo = data.get("memo")

    if count < 1 or count > 100:
        return jsonify({"success": False, "error": "채굴 수량은 1~100 사이여야 합니다."}), 400

    try:
        results = NNBService.harvest_and_save(
            count=count,
            proxy=proxy,
            device_id=device_id,
            memo=memo
        )
        return jsonify({
            "success": True,
            "harvested_count": len(results),
            "items": results
        }), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@nnb_bp.route("/bank", methods=["POST"])
@nnb_bp.route("/register", methods=["POST"])
def bank_nnb():
    """
    [토큰 저금] 앱 웜업이나 단말기에서 수집된 신생아 정품 NNB/BUC를 DB 풀에 저금
    Body: {"nnb": "...", "buc": "...", "source": "APP_WARMUP", "device_id": "...", "memo": "..."}
    """
    data = request.get_json(silent=True) or {}
    nnb = data.get("nnb")
    if not nnb:
        return jsonify({"success": False, "error": "nnb 값은 필수입니다."}), 400

    buc = data.get("buc", "")
    source = data.get("source", "APP_WARMUP")
    device_id = data.get("device_id")
    ip = data.get("ip") or request.remote_addr
    memo = data.get("memo")

    try:
        result = NNBService.bank_nnb(
            nnb=nnb,
            buc=buc,
            source=source,
            device_id=device_id,
            ip=ip,
            memo=memo
        )
        return jsonify({"success": True, "data": result}), 200
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@nnb_bp.route("/topup", methods=["POST"])
def topup_pool():
    """
    [수위 조절기] 활성 NNB 수량이 목표치(target_size) 미달 시 패킷으로 즉시 자동 보충
    Body: {"target_size": 50, "device_id": null, "proxy": null}
    """
    data = request.get_json(silent=True) or {}
    target_size = int(data.get("target_size", TARGET_NNB_POOL_SIZE))
    device_id = data.get("device_id")
    proxy = data.get("proxy")

    try:
        res = NNBService.topup_pool(
            target_size=target_size,
            device_id=device_id,
            proxy=proxy
        )
        return jsonify({"success": True, **res}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@nnb_bp.route("/assign", methods=["GET", "POST"])
@nnb_bp.route("/allocate", methods=["GET", "POST"])
def assign_nnb_endpoint():
    """
    [NNB 단독 할당 API]
    - 키워드나 작업(task) 없이 20분(1200초) 이상 숙성된 NNB+BUC만 단독 할당
    - GET 쿼리 파라미터 및 POST JSON/Form 지원
    - 파라미터: device_id (선택), min_age_seconds (선택, 기본 1200초)
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if not data and request.form:
            data = request.form.to_dict()
    else:
        data = request.args.to_dict()

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
    memo = data.get("memo")

    try:
        result = NNBService.assign_nnb(
            device_id=device_id,
            ip=ip,
            min_age_seconds=min_age_seconds,
            memo=memo
        )
        status_code = 200 if result.get("success") else 404
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@nnb_bp.route("/acquire", methods=["POST"])
def acquire_nnb():
    """
    [작업 호출] 1200초 이상 숙성된 READY 토큰 인출
    - created_at 기준 1200초 초과된 것만 할당
    - use_count + 1 업데이트 및 last_used_at / used_target 갱신
    Body: {"min_age_seconds": 1200, "target": "스토어명/키워드", "device_id": null, "mark_as_used": false}
    """
    data = request.get_json(silent=True) or {}
    min_age_seconds = data.get("min_age_seconds")
    if min_age_seconds is not None:
        try:
            min_age_seconds = int(min_age_seconds)
        except ValueError:
            return jsonify({"success": False, "error": "min_age_seconds는 정수여야 합니다."}), 400
    else:
        min_age_seconds = MIN_AGING_SECONDS

    target = data.get("target")
    device_id = data.get("device_id")
    memo = data.get("memo")
    mark_as_used = bool(data.get("mark_as_used", False))

    try:
        result = NNBService.acquire_nnb_for_job(
            min_age_seconds=min_age_seconds,
            target=target,
            device_id=device_id,
            memo=memo,
            mark_as_used=mark_as_used
        )
        status_code = 200 if result.get("success") else 404
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@nnb_bp.route("/mark-used", methods=["POST"])
def mark_used():
    """
    [타격 확정] 작업 완료된 NNB를 USED 상태로 확정
    Body: {"nnb": "...", "target": "...", "memo": "..."}
    """
    data = request.get_json(silent=True) or {}
    nnb = data.get("nnb")
    if not nnb:
        return jsonify({"success": False, "error": "nnb 값은 필수입니다."}), 400

    target = data.get("target")
    memo = data.get("memo")

    try:
        updated = NNBService.mark_nnb_used(nnb=nnb, target=target, memo=memo)
        if updated:
            return jsonify({"success": True, "message": f"NNB({nnb})가 USED 상태로 확정되었습니다."}), 200
        else:
            return jsonify({"success": False, "message": f"일치하는 NNB({nnb})를 찾을 수 없습니다."}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@nnb_bp.route("/pool-status", methods=["GET"])
@nnb_bp.route("/status", methods=["GET"])
def pool_status():
    """
    [수위 및 상태 추적] AGING(숙성 중), READY(인출 가능), USED(타격 완료) 풀 현황
    """
    min_age_seconds = request.args.get("min_age_seconds")
    if min_age_seconds is not None:
        try:
            min_age_seconds = int(min_age_seconds)
        except ValueError:
            return jsonify({"success": False, "error": "min_age_seconds는 정수여야 합니다."}), 400
    else:
        min_age_seconds = MIN_AGING_SECONDS

    try:
        status_data = NNBService.get_pool_status(min_age_seconds=min_age_seconds)
        return jsonify({"success": True, **status_data}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@nnb_bp.route("/random", methods=["GET"])
def get_random_nnb():
    """
    [랜덤 조회] 1200초(20분) 초과된 nnb, buc를 랜덤으로 1건 (또는 count건) 조회
    - Query: min_age_seconds=1200, count=1, increment=false
    """
    from database import get_db_cursor
    min_age_seconds = int(request.args.get("min_age_seconds", MIN_AGING_SECONDS))
    count = min(max(int(request.args.get("count", 1)), 1), 50)
    increment = request.args.get("increment", "false").lower() in ("true", "1")

    try:
        with get_db_cursor(commit=increment) as (cur, conn):
            query = """
                SELECT id, nnb, buc, use_count, status, created_at,
                       TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age_seconds
                FROM nnbs
                WHERE status IN ('AGING', 'READY', 'ACTIVE')
                  AND created_at <= NOW() - INTERVAL %s SECOND
                ORDER BY RAND()
                LIMIT %s
            """
            cur.execute(query, (min_age_seconds, count))
            rows = cur.fetchall()

            for r in rows:
                if r["created_at"]:
                    r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")

            if not rows:
                return jsonify({
                    "success": False,
                    "message": f"1200초(20분) 이상 숙성된 NNB가 없습니다.",
                    "data": None
                }), 404

            if increment:
                ids = [r["id"] for r in rows]
                placeholders = ",".join(["%s"] * len(ids))
                cur.execute(f"UPDATE nnbs SET use_count = use_count + 1, last_used_at = NOW() WHERE id IN ({placeholders})", tuple(ids))

            if count == 1:
                return jsonify({"success": True, "data": rows[0]}), 200
            else:
                return jsonify({"success": True, "count": len(rows), "data": rows}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
